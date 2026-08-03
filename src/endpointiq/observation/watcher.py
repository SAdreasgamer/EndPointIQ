"""File system watcher with debouncing, filtering, and content hashing.

Watches a project directory for changes and emits batched events
through the EventBus. Handles:
- Debouncing rapid changes (300ms default)
- Filtering ignored paths (.git, node_modules, etc.)
- Content hash comparison to skip unchanged files
- Batching multiple changes into single event
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import hashlib
import logging
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


@dataclass
class FileChangeEvent:
    """Represents a single file change detected by the watcher."""

    type: str  # "created" | "modified" | "deleted" | "moved"
    path: str
    old_path: str | None = None  # for renames/moves
    content_hash: str = ""

    @property
    def is_deletion(self) -> bool:
        return self.type == "deleted"


@dataclass
class FileFilter:
    """Filters files based on ignore patterns (gitignore-style).

    Supports glob patterns for ignoring directories and file extensions.
    """

    ignore_patterns: list[str] = field(default_factory=list)

    # Binary/non-code extensions to always skip
    BINARY_EXTENSIONS: set[str] = field(
        default_factory=lambda: {
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
            ".woff", ".woff2", ".ttf", ".eot",
            ".zip", ".tar", ".gz", ".bz2",
            ".exe", ".dll", ".so", ".dylib",
            ".pdf", ".doc", ".docx",
            ".mp3", ".mp4", ".wav", ".avi",
            ".db", ".sqlite", ".sqlite3",
        }
    )

    # Code extensions we care about
    CODE_EXTENSIONS: set[str] = field(
        default_factory=lambda: {
            ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
            ".py", ".pyi",
            ".java",
            ".go",
            ".cs",
            ".json", ".yaml", ".yml", ".toml",
            ".md", ".txt",
        }
    )

    def should_include(self, path: str) -> bool:
        """Check if a file path should be included (not filtered out)."""
        p = Path(path)

        # Skip binary files
        if p.suffix.lower() in self.BINARY_EXTENSIONS:
            return False

        # Skip hidden files/dirs (except .env-like configs)
        parts = p.parts
        for part in parts:
            if part.startswith(".") and part not in {".env", ".env.example"}:
                for pattern in self.ignore_patterns:
                    if part == pattern or part.startswith(pattern.rstrip("/")):
                        return False

        # Check ignore patterns
        path_str = str(p)
        for pattern in self.ignore_patterns:
            # Check if any path component matches the pattern
            if fnmatch.fnmatch(p.name, pattern):
                return False
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return False
            if fnmatch.fnmatch(path_str, f"*/{pattern}/*"):
                return False

        return True


class _WatchdogHandler(FileSystemEventHandler):
    """Internal watchdog event handler that collects changes into a buffer."""

    def __init__(self, filter: FileFilter, buffer: dict, lock: threading.Lock):
        self.filter = filter
        self.buffer = buffer
        self.lock = lock

    def on_created(self, event: FileSystemEvent):
        src_path = str(event.src_path)
        if not event.is_directory and self.filter.should_include(src_path):
            with self.lock:
                self.buffer[src_path] = FileChangeEvent(
                    type="created",
                    path=src_path,
                    content_hash=self._hash_file(src_path),
                )

    def on_modified(self, event: FileSystemEvent):
        src_path = str(event.src_path)
        if not event.is_directory and self.filter.should_include(src_path):
            with self.lock:
                new_hash = self._hash_file(src_path)
                existing = self.buffer.get(src_path)
                # Skip if hash unchanged (spurious event)
                if existing and existing.content_hash == new_hash:
                    return
                self.buffer[src_path] = FileChangeEvent(
                    type="modified",
                    path=src_path,
                    content_hash=new_hash,
                )

    def on_deleted(self, event: FileSystemEvent):
        src_path = str(event.src_path)
        if not event.is_directory and self.filter.should_include(src_path):
            with self.lock:
                self.buffer[src_path] = FileChangeEvent(
                    type="deleted",
                    path=src_path,
                )

    def on_moved(self, event: FileSystemEvent):
        src_path = str(event.src_path)
        dest_path = str(event.dest_path)
        if not event.is_directory:
            with self.lock:
                if self.filter.should_include(src_path):
                    self.buffer[src_path] = FileChangeEvent(
                        type="deleted",
                        path=src_path,
                    )
                if self.filter.should_include(dest_path):
                    self.buffer[dest_path] = FileChangeEvent(
                        type="created",
                        path=dest_path,
                        content_hash=self._hash_file(dest_path),
                    )

    @staticmethod
    def _hash_file(path: str) -> str:
        """Compute SHA-256 hash of file content."""
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except (OSError, FileNotFoundError):
            return ""


BatchCallback = Callable[[list[FileChangeEvent]], Coroutine]


class RepositoryWatcher:
    """Watches a project directory for file changes with debouncing and batching.

    Usage:
        watcher = RepositoryWatcher(Path("/path/to/project"))
        watcher.on_batch(my_async_handler)
        await watcher.start()
        # ... later ...
        await watcher.stop()
    """

    def __init__(
        self,
        root_path: Path,
        ignore_patterns: list[str] | None = None,
        debounce_seconds: float = 0.3,
    ):
        self.root_path = root_path.resolve()
        self.debounce_seconds = debounce_seconds
        self.filter = FileFilter(
            ignore_patterns=ignore_patterns
            or [
                ".git", "node_modules", "__pycache__", ".venv",
                "*.pyc", "*.lock", "dist", "build",
            ]
        )
        self._observer = Observer()
        self._buffer: dict[str, FileChangeEvent] = {}
        self._lock = threading.Lock()
        self._callbacks: list[BatchCallback] = []
        self._running = False
        self._debounce_task: asyncio.Task | None = None

    def on_batch(self, callback: BatchCallback) -> None:
        """Register an async callback for batched file changes.

        The callback receives a list of FileChangeEvent objects,
        called after debounce period with no new changes.
        """
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start watching the directory for changes."""
        if self._running:
            return

        handler = _WatchdogHandler(self.filter, self._buffer, self._lock)
        self._observer.schedule(handler, str(self.root_path), recursive=True)
        self._observer.start()
        self._running = True

        # Start the debounce loop
        self._debounce_task = asyncio.create_task(self._debounce_loop())
        logger.info(f"Watcher started on {self.root_path}")

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._debounce_task:
            self._debounce_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._debounce_task
            self._observer.stop()
        self._observer.join()
        logger.info("Watcher stopped")

    async def _debounce_loop(self) -> None:
        """Periodically flush the buffer after debounce period."""
        while self._running:
            await asyncio.sleep(self.debounce_seconds)
            await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush accumulated changes to callbacks."""
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer.values())
            self._buffer.clear()

        if batch and self._callbacks:
            logger.debug(f"Flushing {len(batch)} file change(s)")
            for callback in self._callbacks:
                try:
                    await callback(batch)
                except Exception as e:
                    logger.error(f"Batch callback error: {e}")

    @property
    def is_running(self) -> bool:
        return self._running
