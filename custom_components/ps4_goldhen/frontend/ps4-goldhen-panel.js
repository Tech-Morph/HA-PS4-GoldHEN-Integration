/**
 * PS4 GoldHEN FTP File Browser Panel
 * A lightweight web component for Home Assistant.
 */

const html = (strings, ...values) => strings.reduce((acc, str, i) => acc + str + (values[i] || ""), "");

class PS4GoldHENPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (this._path === undefined) {
      this._path = "/";
      this._loadDir();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entries = [];
    this._loading = false;
    this._editing = null; // { path: string, name: string, content: string }
  }

  async _loadDir(path = this._path) {
    if (!this._hass) return;
    this._loading = true;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_list_dir",
        entry_id: this._panel.config.entry_id,
        path: path,
      });
      this._path = result.path;
      this._entries = result.entries;
    } catch (e) {
      alert(`FTP Error: ${e.message || e}`);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _deleteEntry(entry) {
    if (!confirm(`Delete ${entry.name}?`)) return;
    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_delete",
        entry_id: this._panel.config.entry_id,
        path: entry.path,
        is_dir: entry.is_dir,
      });
      this._loadDir();
    } catch (e) {
      alert(`Delete failed: ${e.message || e}`);
    }
  }

  async _renameEntry(entry) {
    const newName = prompt(`Rename ${entry.name} to:`, entry.name);
    if (!newName || newName === entry.name) return;
    
    const parts = this._path.split("/").filter(p => p);
    const parentPath = "/" + parts.join("/");
    const toPath = (parentPath === "/" ? "" : parentPath) + "/" + newName;

    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_rename",
        entry_id: this._panel.config.entry_id,
        from_path: entry.path,
        to_path: toPath,
      });
      this._loadDir();
    } catch (e) {
      alert(`Rename failed: ${e.message || e}`);
    }
  }

  async _editEntry(entry) {
    this._loading = true;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_get_text",
        entry_id: this._panel.config.entry_id,
        path: entry.path,
      });
      this._editing = { path: entry.path, name: entry.name, content: result.content };
    } catch (e) {
      alert(`Read failed: ${e.message || e}`);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _saveFile() {
    const textarea = this.shadowRoot.querySelector("#editor-textarea");
    const content = textarea ? textarea.value : "";
    this._loading = true;
    this._render();
    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_put_text",
        entry_id: this._panel.config.entry_id,
        path: this._editing.path,
        content: content,
      });
      this._editing = null;
      this._loadDir();
    } catch (e) {
      alert(`Save failed: ${e.message || e}`);
      this._loading = false;
      this._render();
    }
  }

  _downloadEntry(entry) {
    const url = `/api/ps4_goldhen/ftp/download?entry_id=${this._panel.config.entry_id}&path=${encodeURIComponent(entry.path)}`;
    window.open(url, "_blank");
  }

  _render() {
    this.shadowRoot.innerHTML = html`
      <style>
        :host { display: block; padding: 16px; font-family: sans-serif; background: var(--primary-background-color); color: var(--primary-text-color); height: 100vh; overflow-y: auto; }
        .header { display: flex; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--divider-color); padding-bottom: 8px; gap: 8px; }
        .path { flex: 1; font-weight: bold; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 8px; border-bottom: 2px solid var(--divider-color); }
        td { padding: 8px; border-bottom: 1px solid var(--divider-color); vertical-align: middle; }
        tr:hover { background: var(--secondary-background-color); }
        .folder { color: var(--primary-color); cursor: pointer; text-decoration: underline; }
        .file { color: var(--primary-text-color); }
        .actions { display: flex; gap: 4px; }
        .actions button { cursor: pointer; padding: 4px 8px; background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 4px; color: var(--primary-text-color); }
        .actions button:hover { background: var(--secondary-background-color); }
        .loading { font-style: italic; color: var(--secondary-text-color); margin-bottom: 8px; }
        
        /* Editor Overlay */
        .editor-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .editor-container { background: var(--primary-background-color); width: 90%; height: 90%; display: flex; flex-direction: column; padding: 16px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        .editor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        #editor-textarea { flex: 1; font-family: 'Consolas', 'Monaco', monospace; font-size: 14px; padding: 12px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); resize: none; outline: none; }
        .editor-actions { margin-top: 16px; display: flex; justify-content: flex-end; gap: 12px; }
        .editor-actions button { padding: 8px 20px; cursor: pointer; border-radius: 4px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        .btn-save { background: var(--primary-color) !important; color: white !important; border: none !important; }
      </style>

      <div class="header">
        <div class="path">PS4 FTP: ${this._path}</div>
        <button id="btn-root">Root</button>
        <button id="btn-back">Back</button>
        <button id="btn-refresh">Refresh</button>
      </div>

      ${this._loading ? '<div class="loading">Processing...</div>' : ""}

      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Size</th>
            <th>Modified</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${this._entries.map(e => `
            <tr>
              <td>
                <span class="${e.is_dir ? 'folder' : 'file'}" data-path="${e.path}" data-isdir="${e.is_dir}">
                  ${e.is_dir ? "📁" : "📄"} ${e.name}
                </span>
              </td>
              <td>${e.is_dir ? "-" : (e.size / 1024 / 1024).toFixed(2) + " MB"}</td>
              <td>${e.modified}</td>
              <td class="actions">
                ${!e.is_dir ? `<button data-action="download" data-path="${e.path}" title="Download">💾</button>` : ""}
                ${!e.is_dir ? `<button data-action="edit" data-path="${e.path}" data-name="${e.name}" title="Edit">✏️</button>` : ""}
                <button data-action="rename" data-path="${e.path}" data-name="${e.name}" title="Rename">🏷️</button>
                <button data-action="delete" data-path="${e.path}" data-isdir="${e.is_dir}" data-name="${e.name}" title="Delete">🗑️</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>

      ${this._editing ? html`
        <div class="editor-overlay">
          <div class="editor-container">
            <div class="editor-header">
              <div>
                <strong>Editing: ${this._editing.name}</strong><br>
                <small style="color: var(--secondary-text-color)">${this._editing.path}</small>
              </div>
            </div>
            <textarea id="editor-textarea" spellcheck="false">${this._editing.content}</textarea>
            <div class="editor-actions">
              <button id="btn-cancel">Cancel</button>
              <button id="btn-save" class="btn-save">Save to PS4</button>
            </div>
          </div>
        </div>
      ` : ""}
    `;

    // Event delegation for table clicks
    const table = this.shadowRoot.querySelector("table");
    if (table) {
      table.onclick = (ev) => {
        const btn = ev.target.closest("button");
        const span = ev.target.closest("span.folder");
        
        if (span) {
          this._loadDir(span.dataset.path);
          return;
        }
        
        if (!btn) return;
        const action = btn.dataset.action;
        const path = btn.dataset.path;
        const name = btn.dataset.name;
        const isDir = btn.dataset.isdir === "true";

        if (action === "delete") this._deleteEntry({ name, path, is_dir: isDir });
        else if (action === "rename") this._renameEntry({ name, path });
        else if (action === "edit") this._editEntry({ name, path });
        else if (action === "download") this._downloadEntry({ path });
      };
    }

    // Header buttons
    const btnRoot = this.shadowRoot.querySelector("#btn-root");
    const btnUp = this.shadowRoot.querySelector("#btn-up");
    const btnRefresh = this.shadowRoot.querySelector("#btn-refresh");

    if (btnRoot) btnRoot.onclick = () => this._loadDir("/");
    if (btnUp) btnUp.onclick = () => this._loadDir(this._path.split("/").slice(0, -1).join("/") || "/");
    if (btnRefresh) btnRefresh.onclick = () => this._loadDir();

    // Editor buttons
    if (this._editing) {
      const btnCancel = this.shadowRoot.querySelector("#btn-cancel");
      const btnSave = this.shadowRoot.querySelector("#btn-save");
      if (btnCancel) btnCancel.onclick = () => { this._editing = null; this._render(); };
      if (btnSave) btnSave.onclick = () => this._saveFile();
    }
  }
}

customElements.define("ps4-goldhen-panel", PS4GoldHENPanel);
