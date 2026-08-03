"""Typed async event bus for internal component communication.

Components emit and listen to events through this bus instead of
importing each other directly. This keeps the architecture loosely coupled.

Example:
    bus = EventBus()
    bus.on(Events.ENDPOINT_DISCOVERED, my_handler)
    await bus.emit(Events.ENDPOINT_DISCOVERED, endpoint=ep)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for async event handlers
EventHandler = Callable[..., Coroutine[Any, Any, None]]


class Events:
    """Event name constants.

    Using a class with string constants keeps event names
    centralized and IDE-discoverable.
    """

    # Watcher events
    WATCHER_BATCH = "watcher:batch"

    # Parser events
    PARSER_PARSED = "parser:parsed"
    PARSER_ERROR = "parser:error"

    # Indexer events
    INDEXER_STARTED = "indexer:started"
    INDEXER_UPDATED = "indexer:updated"
    INDEXER_COMPLETED = "indexer:completed"

    # Graph events
    GRAPH_UPDATED = "graph:updated"
    GRAPH_NODE_ADDED = "graph:node_added"
    GRAPH_PRUNED = "graph:pruned"

    # Endpoint events
    ENDPOINT_DISCOVERED = "endpoint:discovered"
    ENDPOINT_REMOVED = "endpoint:removed"

    # Analysis events
    ANALYSIS_STARTED = "analysis:started"
    ANALYSIS_PROGRESS = "analysis:progress"
    ANALYSIS_COMPLETED = "analysis:completed"
    ANALYSIS_FAILED = "analysis:failed"

    # Framework events
    FRAMEWORK_DETECTED = "framework:detected"


class EventBus:
    """Async event bus for internal communication between components.

    Supports:
    - Multiple handlers per event
    - Async handlers (fire-and-forget)
    - Handler error isolation (one handler's error doesn't break others)
    """

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._emit_count: int = 0

    def on(self, event: str, handler: EventHandler) -> None:
        """Register an async handler for an event.

        Args:
            event: Event name from Events class.
            handler: Async callable that receives event kwargs.
        """
        self._handlers[event].append(handler)
        logger.debug(f"Handler registered for '{event}': {handler.__name__}")

    def off(self, event: str, handler: EventHandler) -> None:
        """Remove a handler for an event."""
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h is not handler]

    async def emit(self, event: str, **kwargs) -> None:
        """Emit an event to all registered handlers.

        Handlers run concurrently. Exceptions in individual handlers
        are caught and logged, not propagated.

        Args:
            event: Event name from Events class.
            **kwargs: Data to pass to handlers.
        """
        handlers = self._handlers.get(event, [])
        if not handlers:
            return

        self._emit_count += 1
        logger.debug(f"Emitting '{event}' to {len(handlers)} handler(s)")

        results = await asyncio.gather(
            *[self._safe_call(handler, event, **kwargs) for handler in handlers],
            return_exceptions=True,
        )

        # Log any errors from handlers
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Handler {handlers[i].__name__} failed for '{event}': {result}"
                )

    async def _safe_call(self, handler: EventHandler, event: str, **kwargs) -> None:
        """Call a handler with error isolation."""
        try:
            await handler(**kwargs)
        except Exception as e:
            logger.error(f"Error in handler for '{event}': {e}")
            raise

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all events."""
        return sum(len(handlers) for handlers in self._handlers.values())

    @property
    def total_emits(self) -> int:
        """Total number of events emitted since creation."""
        return self._emit_count

    def clear(self) -> None:
        """Remove all handlers. Useful for testing."""
        self._handlers.clear()
        self._emit_count = 0
