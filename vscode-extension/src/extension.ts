/**
 * EndpointIQ VS Code Extension
 *
 * Thin TypeScript client — zero business logic. Pure API client
 * that talks to the EndpointIQ FastAPI server on localhost:8421.
 *
 * Features:
 * - Sidebar tree view showing all discovered endpoints
 * - Commands: Analyze, Security Review, Performance Review, Show Dependencies
 * - Report webview panel with formatted HTML
 * - Status bar showing endpoint count and server status
 */

import * as vscode from "vscode";
import * as http from "http";

// ── API Client ───────────────────────────────────────

class EndpointIQClient {
  private baseUrl: string;
  private projectId: string | null = null;

  constructor() {
    const config = vscode.workspace.getConfiguration("endpointiq");
    this.baseUrl = config.get("serverUrl", "http://127.0.0.1:8421");
  }

  async healthCheck(): Promise<{ status: string; version: string } | null> {
    try {
      return await this.request("GET", "/api/health");
    } catch {
      return null;
    }
  }

  async registerProject(path: string): Promise<any> {
    const data = await this.request("POST", "/api/projects", { path });
    this.projectId = data.id;
    return data;
  }

  async listEndpoints(): Promise<any[]> {
    if (!this.projectId) {
      return [];
    }
    return await this.request(
      "GET",
      `/api/endpoints?project_id=${this.projectId}`
    );
  }

  async runAnalysis(endpoint: string, goalType: string): Promise<any> {
    if (!this.projectId) {
      throw new Error("No project registered");
    }
    return await this.request("POST", "/api/analysis", {
      project_id: this.projectId,
      endpoint,
      goal_type: goalType,
    });
  }

  async getGraph(endpoint: string): Promise<any> {
    if (!this.projectId) {
      throw new Error("No project registered");
    }
    const encoded = encodeURIComponent(endpoint);
    return await this.request(
      "GET",
      `/api/graph/${encoded}?project_id=${this.projectId}`
    );
  }

  private request(method: string, path: string, body?: any): Promise<any> {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const options: http.RequestOptions = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method,
        headers: { "Content-Type": "application/json" },
        timeout: 120000,
      };

      const req = http.request(options, (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          try {
            const parsed = JSON.parse(data);
            if (res.statusCode && res.statusCode >= 400) {
              reject(
                new Error(parsed.detail || `HTTP ${res.statusCode}`)
              );
            } else {
              resolve(parsed);
            }
          } catch {
            reject(new Error(`Invalid JSON: ${data.slice(0, 100)}`));
          }
        });
      });

      req.on("error", (err) =>
        reject(new Error(`Cannot connect to EndpointIQ server: ${err.message}`))
      );
      req.on("timeout", () => {
        req.destroy();
        reject(new Error("Request timed out"));
      });

      if (body) {
        req.write(JSON.stringify(body));
      }
      req.end();
    });
  }
}

// ── Endpoint Tree View ───────────────────────────────

class EndpointItem extends vscode.TreeItem {
  constructor(
    public readonly endpointName: string,
    public readonly endpointType: string,
    public readonly filePath: string
  ) {
    super(endpointName, vscode.TreeItemCollapsibleState.None);
    this.tooltip = `${endpointName} — ${filePath}`;
    this.description = filePath;
    this.contextValue = "endpoint";

    // Icon based on HTTP method
    const method = endpointName.split(" ")[0];
    const iconMap: Record<string, string> = {
      GET: "symbol-method",
      POST: "add",
      PUT: "edit",
      DELETE: "trash",
      PATCH: "edit",
    };
    this.iconPath = new vscode.ThemeIcon(iconMap[method] || "circle");
  }
}

class EndpointTreeProvider
  implements vscode.TreeDataProvider<EndpointItem>
{
  private _onDidChange = new vscode.EventEmitter<
    EndpointItem | undefined
  >();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private endpoints: EndpointItem[] = [];

  refresh(endpoints: any[]): void {
    this.endpoints = endpoints.map(
      (ep) => new EndpointItem(ep.name, ep.type, ep.file_path)
    );
    this._onDidChange.fire(undefined);
  }

  getTreeItem(element: EndpointItem): vscode.TreeItem {
    return element;
  }

  getChildren(): EndpointItem[] {
    return this.endpoints;
  }
}

// ── Report Webview ───────────────────────────────────

function renderReport(
  panel: vscode.WebviewPanel,
  report: any
): void {
  const findings = report.findings || [];
  const severityColors: Record<string, string> = {
    critical: "#ff4444",
    high: "#ff8800",
    medium: "#ffcc00",
    low: "#4488ff",
    info: "#44cc44",
  };

  const findingsHtml = findings
    .map(
      (f: any) => `
    <div class="finding" style="border-left: 4px solid ${severityColors[f.severity] || "#888"};">
      <div class="finding-header">
        <span class="severity" style="color: ${severityColors[f.severity] || "#888"};">
          ${(f.severity || "info").toUpperCase()}
        </span>
        <span class="title">${escapeHtml(f.title || "")}</span>
      </div>
      <p class="description">${escapeHtml(f.description || "")}</p>
      ${f.file_path ? `<p class="file">📄 ${escapeHtml(f.file_path)}${f.line_number ? `:${f.line_number}` : ""}</p>` : ""}
      ${f.recommendation ? `<p class="recommendation">💡 ${escapeHtml(f.recommendation)}</p>` : ""}
    </div>`
    )
    .join("\n");

  panel.webview.html = `<!DOCTYPE html>
<html>
<head>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; color: var(--vscode-foreground); background: var(--vscode-editor-background); }
    h1 { font-size: 1.4em; margin-bottom: 4px; }
    .summary { color: var(--vscode-descriptionForeground); margin-bottom: 20px; }
    .meta { display: flex; gap: 16px; margin-bottom: 20px; font-size: 0.85em; color: var(--vscode-descriptionForeground); }
    .meta span { background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 2px 8px; border-radius: 4px; }
    .finding { padding: 12px 16px; margin: 8px 0; background: var(--vscode-editor-inactiveSelectionBackground); border-radius: 6px; }
    .finding-header { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; }
    .severity { font-weight: 700; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.5px; }
    .title { font-weight: 600; font-size: 1em; }
    .description { margin: 4px 0; font-size: 0.9em; line-height: 1.5; }
    .file { font-size: 0.8em; color: var(--vscode-textLink-foreground); }
    .recommendation { font-size: 0.85em; color: var(--vscode-descriptionForeground); font-style: italic; }
    .empty { text-align: center; padding: 40px; color: var(--vscode-descriptionForeground); }
  </style>
</head>
<body>
  <h1>📋 ${escapeHtml(report.goal_type || "Full")} Analysis: ${escapeHtml(report.endpoint || "")}</h1>
  <p class="summary">${escapeHtml(report.summary || "")}</p>
  <div class="meta">
    <span>🔍 ${report.findings_count || 0} findings</span>
    <span>⏱ ${report.duration_ms || 0}ms</span>
    <span>✅ ${report.status || "completed"}</span>
  </div>
  ${findings.length > 0 ? findingsHtml : '<div class="empty">No issues found! ✨</div>'}
</body>
</html>`;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Extension Activation ─────────────────────────────

export async function activate(
  context: vscode.ExtensionContext
): Promise<void> {
  const client = new EndpointIQClient();
  const treeProvider = new EndpointTreeProvider();
  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );

  // Register tree view
  vscode.window.registerTreeDataProvider(
    "endpointiq.endpoints",
    treeProvider
  );

  // Status bar
  statusBar.text = "$(shield) EndpointIQ: Connecting...";
  statusBar.show();
  context.subscriptions.push(statusBar);

  // ── Initialize ──

  async function initialize(): Promise<void> {
    const health = await client.healthCheck();
    if (!health) {
      statusBar.text = "$(shield) EndpointIQ: Server offline";
      statusBar.tooltip =
        'Start the server with: uv run eiq serve';
      vscode.window.showWarningMessage(
        'EndpointIQ server not running. Start it with: uv run eiq serve'
      );
      return;
    }

    statusBar.text = `$(shield) EndpointIQ: v${health.version}`;

    // Auto-register workspace
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      try {
        const project = await client.registerProject(
          folders[0].uri.fsPath
        );
        statusBar.text = `$(shield) EndpointIQ: ${project.endpoints_count} endpoints`;
        statusBar.tooltip = `${project.framework} project — ${project.nodes_count} nodes`;

        // Load endpoints into tree
        const endpoints = await client.listEndpoints();
        treeProvider.refresh(endpoints);
      } catch (err: any) {
        statusBar.text = "$(shield) EndpointIQ: Index failed";
        vscode.window.showErrorMessage(
          `EndpointIQ indexing failed: ${err.message}`
        );
      }
    }
  }

  // ── Commands ──

  const analyzeCmd = vscode.commands.registerCommand(
    "endpointiq.analyzeEndpoint",
    async (item?: EndpointItem) => {
      const endpoint =
        item?.endpointName ||
        (await vscode.window.showInputBox({
          prompt: "Enter endpoint (e.g., POST /api/users)",
          placeHolder: "GET /api/users",
        }));
      if (!endpoint) { return; }

      const panel = vscode.window.createWebviewPanel(
        "endpointiq.report",
        `EndpointIQ: ${endpoint}`,
        vscode.ViewColumn.Beside,
        { enableScripts: true }
      );

      panel.webview.html =
        '<body style="padding:40px;text-align:center;color:var(--vscode-descriptionForeground);">Analyzing...</body>';

      try {
        const report = await client.runAnalysis(endpoint, "full");
        renderReport(panel, report);
      } catch (err: any) {
        panel.webview.html = `<body style="padding:40px;color:#ff4444;">Error: ${escapeHtml(err.message)}</body>`;
      }
    }
  );

  const securityCmd = vscode.commands.registerCommand(
    "endpointiq.securityReview",
    async (item?: EndpointItem) => {
      const endpoint =
        item?.endpointName ||
        (await vscode.window.showInputBox({
          prompt: "Enter endpoint for security review",
        }));
      if (!endpoint) { return; }

      const panel = vscode.window.createWebviewPanel(
        "endpointiq.report",
        `🔒 Security: ${endpoint}`,
        vscode.ViewColumn.Beside,
        { enableScripts: true }
      );

      panel.webview.html =
        '<body style="padding:40px;text-align:center;">Running security review...</body>';

      try {
        const report = await client.runAnalysis(endpoint, "security");
        renderReport(panel, report);
      } catch (err: any) {
        panel.webview.html = `<body style="padding:40px;color:#ff4444;">Error: ${escapeHtml(err.message)}</body>`;
      }
    }
  );

  const performanceCmd = vscode.commands.registerCommand(
    "endpointiq.performanceReview",
    async (item?: EndpointItem) => {
      const endpoint =
        item?.endpointName ||
        (await vscode.window.showInputBox({
          prompt: "Enter endpoint for performance review",
        }));
      if (!endpoint) { return; }

      const panel = vscode.window.createWebviewPanel(
        "endpointiq.report",
        `⚡ Performance: ${endpoint}`,
        vscode.ViewColumn.Beside,
        { enableScripts: true }
      );

      panel.webview.html =
        '<body style="padding:40px;text-align:center;">Running performance review...</body>';

      try {
        const report = await client.runAnalysis(endpoint, "performance");
        renderReport(panel, report);
      } catch (err: any) {
        panel.webview.html = `<body style="padding:40px;color:#ff4444;">Error: ${escapeHtml(err.message)}</body>`;
      }
    }
  );

  const depsCmd = vscode.commands.registerCommand(
    "endpointiq.showDependencies",
    async (item?: EndpointItem) => {
      const endpoint =
        item?.endpointName ||
        (await vscode.window.showInputBox({
          prompt: "Enter endpoint to show dependencies",
        }));
      if (!endpoint) { return; }

      try {
        const graph = await client.getGraph(endpoint);
        const panel = vscode.window.createWebviewPanel(
          "endpointiq.graph",
          `🔗 Graph: ${endpoint}`,
          vscode.ViewColumn.Beside,
          { enableScripts: true }
        );

        const nodesHtml = (graph.nodes || [])
          .map(
            (n: any) =>
              `<li><strong>${escapeHtml(n.qualified_name || n.id)}</strong> <span style="opacity:0.6">(${escapeHtml(n.type || "")})</span> ${n.file_path ? `— ${escapeHtml(n.file_path)}` : ""}</li>`
          )
          .join("");

        panel.webview.html = `<!DOCTYPE html>
<html><head><style>
  body { font-family: -apple-system, sans-serif; padding: 20px; color: var(--vscode-foreground); }
  h2 { font-size: 1.2em; }
  li { margin: 6px 0; }
  .meta { font-size: 0.85em; color: var(--vscode-descriptionForeground); }
</style></head><body>
  <h2>🔗 Dependency Graph: ${escapeHtml(endpoint)}</h2>
  <p class="meta">${graph.node_count} nodes, ${graph.edge_count} edges</p>
  <ul>${nodesHtml}</ul>
</body></html>`;
      } catch (err: any) {
        vscode.window.showErrorMessage(`Failed to load graph: ${err.message}`);
      }
    }
  );

  const refreshCmd = vscode.commands.registerCommand(
    "endpointiq.refreshEndpoints",
    async () => {
      await initialize();
      vscode.window.showInformationMessage("EndpointIQ: Endpoints refreshed");
    }
  );

  context.subscriptions.push(
    analyzeCmd,
    securityCmd,
    performanceCmd,
    depsCmd,
    refreshCmd
  );

  // Initialize on activation
  const config = vscode.workspace.getConfiguration("endpointiq");
  if (config.get("autoIndex", true)) {
    initialize();
  }
}

export function deactivate(): void {
  // Cleanup
}
