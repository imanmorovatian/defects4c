from typing import Any, Dict, List

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

DEFECTS4C_BASE_URL = "http://127.0.0.1:11111"
REQUEST_TIMEOUT = 20
LOCAL_UI_HOST = "127.0.0.1"
LOCAL_UI_PORT = 8000

app = FastAPI(title="Defects4C Explorer")


def _get_json(path: str) -> Dict[str, Any]:
    try:
        response = requests.get(
            f"{DEFECTS4C_BASE_URL}{path}",
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Defects4C API at {DEFECTS4C_BASE_URL}: {exc}",
        ) from exc


def get_filtered_defects() -> List[str]:
    defects_data = _get_json("/list_defects_bugid")
    if defects_data.get("status") != "success":
        raise HTTPException(status_code=502, detail=f"Unexpected defects payload: {defects_data}")

    return [
        defect_id
        for defect_id in defects_data.get("defects", [])
        if "llvm___llvm" not in defect_id
    ]


def get_defect(defect_id: str) -> Dict[str, Any]:
    defect_data = _get_json(f"/get_defect/{defect_id}")
    if defect_data.get("status") != "success":
        raise HTTPException(status_code=502, detail=f"Unexpected defect payload: {defect_data}")
    return defect_data


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Defects4C Explorer</title>
    <style>
      :root {
        --bg: #f6f7f9;
        --panel: #ffffff;
        --border: #d8dde6;
        --text: #1f2937;
        --muted: #667085;
        --accent: #0f766e;
        --accent-soft: #e6fffb;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: sans-serif;
      }

      .page {
        max-width: 1200px;
        margin: 0 auto;
        padding: 24px;
      }

      .panel {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 16px;
      }

      .controls {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        align-items: end;
        margin-bottom: 16px;
      }

      label {
        display: block;
        font-size: 14px;
        color: var(--muted);
        margin-bottom: 8px;
      }

      select,
      button {
        font: inherit;
      }

      select {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: #fff;
      }

      button {
        padding: 10px 14px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: #fff;
        cursor: pointer;
      }

      button.active {
        border-color: var(--accent);
        background: var(--accent-soft);
        color: var(--accent);
      }

      .button-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 16px 0;
      }

      .overview-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 16px 0;
      }

      .stat {
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 12px;
      }

      .stat h3 {
        margin: 0 0 8px;
        font-size: 13px;
        color: var(--muted);
        font-weight: 600;
      }

      .stat div {
        font-size: 15px;
        line-height: 1.4;
        word-break: break-word;
      }

      .section-title {
        margin: 0 0 10px;
        font-size: 18px;
      }

      .subtle {
        color: var(--muted);
      }

      .kv-table {
        width: 100%;
        border-collapse: collapse;
      }

      .kv-table td {
        padding: 10px 8px;
        border-top: 1px solid var(--border);
        vertical-align: top;
      }

      .kv-table td:first-child {
        width: 240px;
        color: var(--muted);
      }

      .json-block {
        margin: 0;
        padding: 12px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: #fbfcfd;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-x: auto;
      }

      .stack {
        display: grid;
        gap: 12px;
      }

      .hidden {
        display: none;
      }

      #status {
        margin-top: 12px;
        color: var(--muted);
      }
    </style>
  </head>
  <body>
    <div class="page">
      <div class="panel">
        <h1 style="margin-top: 0;">Defects4C Explorer</h1>
        <p class="subtle" style="margin-top: 0;">
          Pick a defect, read the high-level summary, then switch to the raw sections.
        </p>

        <div class="controls">
          <div>
            <label for="defect-select">Filtered defects</label>
            <select id="defect-select"></select>
          </div>
          <button id="reload-button" type="button">Reload defect</button>
        </div>

        <div class="button-row" id="view-buttons">
          <button type="button" data-view="overview" class="active">Overview</button>
          <button type="button" data-view="prompt">Prompt Data</button>
          <button type="button" data-view="additional">Additional Info</button>
          <button type="button" data-view="raw">Raw JSON</button>
        </div>

        <div id="status">Loading defects...</div>
      </div>

      <div class="overview-grid" id="overview-grid"></div>

      <div class="panel stack" id="detail-panel">
        <section id="view-overview">
          <h2 class="section-title">Overview</h2>
          <div id="overview-content"></div>
        </section>

        <section id="view-prompt" class="hidden">
          <h2 class="section-title">Prompt Data</h2>
          <div id="prompt-content"></div>
        </section>

        <section id="view-additional" class="hidden">
          <h2 class="section-title">Additional Info</h2>
          <div id="additional-content"></div>
        </section>

        <section id="view-raw" class="hidden">
          <h2 class="section-title">Raw JSON</h2>
          <pre class="json-block" id="raw-content"></pre>
        </section>
      </div>
    </div>

    <script>
      const defectSelect = document.getElementById("defect-select");
      const statusNode = document.getElementById("status");
      const reloadButton = document.getElementById("reload-button");
      const overviewGrid = document.getElementById("overview-grid");
      const overviewContent = document.getElementById("overview-content");
      const promptContent = document.getElementById("prompt-content");
      const additionalContent = document.getElementById("additional-content");
      const rawContent = document.getElementById("raw-content");

      let currentDefect = null;

      function escapeHtml(value) {
        return String(value)
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      }

      function prettyValue(value) {
        if (value === null || value === undefined) {
          return '<span class="subtle">None</span>';
        }
        if (typeof value === "string") {
          if (value.length > 500) {
            return `<pre class="json-block">${escapeHtml(value)}</pre>`;
          }
          return escapeHtml(value);
        }
        if (typeof value === "number" || typeof value === "boolean") {
          return escapeHtml(value);
        }
        return `<pre class="json-block">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
      }

      function renderTable(obj) {
        const entries = Object.entries(obj || {});
        if (!entries.length) {
          return '<div class="subtle">No data available.</div>';
        }

        return `
          <table class="kv-table">
            <tbody>
              ${entries.map(([key, value]) => `
                <tr>
                  <td>${escapeHtml(key)}</td>
                  <td>${prettyValue(value)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        `;
      }

      function renderOverview(defect) {
        const promptData = defect.prompt_data || {};
        const additionalInfo = defect.additional_info || {};
        const promptItems = Array.isArray(promptData.prompt) ? promptData.prompt.length : 0;

        const stats = [
          ["Bug ID", defect.bug_id || defect.defect_id || "Unknown"],
          ["SHA", defect.sha_id || "Unknown"],
          ["Total Defects", defect.total_defects_available ?? "Unknown"],
          ["Prompt Entries", promptItems],
          ["Has Metadata", additionalInfo.metadata ? "Yes" : "No"],
          ["Has Guidance", additionalInfo.guidance ? "Yes" : "No"],
          ["Has Prefix/Suffix", additionalInfo.prefix_suffix ? "Yes" : "No"],
          ["Cached Source", additionalInfo.has_source_content ? "Yes" : "No"],
        ];

        overviewGrid.innerHTML = stats.map(([label, value]) => `
          <div class="stat">
            <h3>${escapeHtml(label)}</h3>
            <div>${prettyValue(value)}</div>
          </div>
        `).join("");

        const highLevel = {
          defect_id: defect.defect_id,
          bug_id: defect.bug_id,
          sha_id: defect.sha_id,
          total_defects_available: defect.total_defects_available,
          prompt_data_keys: Object.keys(promptData),
          additional_info_keys: Object.keys(additionalInfo),
        };

        overviewContent.innerHTML = renderTable(highLevel);
        promptContent.innerHTML = renderTable(promptData);
        additionalContent.innerHTML = renderTable(additionalInfo);
        rawContent.textContent = JSON.stringify(defect, null, 2);
      }

      async function loadDefects() {
        statusNode.textContent = "Loading defects...";
        const response = await fetch("/api/defects");
        const payload = await response.json();

        if (!response.ok) {
          throw new Error(payload.detail || "Failed to load defects");
        }

        defectSelect.innerHTML = payload.defects
          .map(defectId => `<option value="${escapeHtml(defectId)}">${escapeHtml(defectId)}</option>`)
          .join("");

        if (!payload.defects.length) {
          statusNode.textContent = "No defects available.";
          return;
        }

        await loadDefect(payload.defects[0]);
      }

      async function loadDefect(defectId) {
        statusNode.textContent = `Loading ${defectId}...`;
        const response = await fetch(`/api/defects/${encodeURIComponent(defectId)}`);
        const payload = await response.json();

        if (!response.ok) {
          throw new Error(payload.detail || `Failed to load ${defectId}`);
        }

        currentDefect = payload;
        defectSelect.value = defectId;
        renderOverview(payload);
        statusNode.textContent = `Showing ${defectId}`;
      }

      function setView(viewName) {
        document.querySelectorAll("[data-view]").forEach(button => {
          button.classList.toggle("active", button.dataset.view === viewName);
        });

        ["overview", "prompt", "additional", "raw"].forEach(name => {
          const section = document.getElementById(`view-${name}`);
          section.classList.toggle("hidden", name !== viewName);
        });
      }

      defectSelect.addEventListener("change", async (event) => {
        try {
          await loadDefect(event.target.value);
        } catch (error) {
          statusNode.textContent = error.message;
        }
      });

      reloadButton.addEventListener("click", async () => {
        if (!defectSelect.value) {
          return;
        }
        try {
          await loadDefect(defectSelect.value);
        } catch (error) {
          statusNode.textContent = error.message;
        }
      });

      document.getElementById("view-buttons").addEventListener("click", (event) => {
        const button = event.target.closest("[data-view]");
        if (!button) {
          return;
        }
        setView(button.dataset.view);
      });

      loadDefects().catch((error) => {
        statusNode.textContent = error.message;
      });
    </script>
  </body>
</html>
"""


@app.get("/api/defects", response_class=JSONResponse)
def defects() -> Dict[str, Any]:
    filtered_defects = get_filtered_defects()
    return {
        "status": "success",
        "defects": filtered_defects,
        "total_count": len(filtered_defects),
    }


@app.get("/api/defects/{defect_id:path}", response_class=JSONResponse)
def defect(defect_id: str) -> Dict[str, Any]:
    return get_defect(defect_id)


if __name__ == "__main__":
    print(f"Open http://{LOCAL_UI_HOST}:{LOCAL_UI_PORT} in your browser")
    uvicorn.run(app, host=LOCAL_UI_HOST, port=LOCAL_UI_PORT)
