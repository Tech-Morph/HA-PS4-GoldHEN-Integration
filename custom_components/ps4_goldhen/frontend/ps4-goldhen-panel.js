const html = (strings, ...values) =>
  strings.reduce((acc, str, i) => acc + str + (values[i] ?? ""), "");

class PS4GoldHENPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._init();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });

    this._initialized = false;
    this._loading = false;
    this._tab = "ftp";

    this._entries = [];
    this._selectedEntryId = null;

    // FTP state
    this._path = "/";
    this._ftpEntries = [];
    this._editing = null;

    // BinLoader state
    this._payloads = [];
    this._selectedPayload = "";
    this._payloadDir = "";
    this._binHost = "";
    this._binPort = "";
    this._binTimeout = "30";
    this._binStatus = "";
  }

  async _init() {
    await this._loadEntries();
    await this._loadPayloads();
    if (this._selectedEntryId) await this._loadDir("/");
    this._render();
  }

  _setLoading(v) {
    this._loading = v;
    this._render();
  }

  async _loadEntries() {
    if (!this._hass) return;
    try {
      const resp = await this._hass.callWS({ type: "ps4_goldhen/list_entries" });
      this._entries = resp.entries || [];
      const configured = this._panel?.config?.entry_id;
      const first = this._entries[0]?.entry_id || null;
      this._selectedEntryId = configured || this._selectedEntryId || first;

      const entry = this._selectedEntry();
      if (entry) {
        this._binHost = entry.ps4_host || "";
        this._binPort = String(entry.binloader_port ?? "");
      }
    } catch (e) {
      this._entries = [];
      this._selectedEntryId = null;
      alert(`Failed to load PS4 entries: ${e.message || e}`);
    }
  }

  _selectedEntry() {
    return this._entries.find((e) => e.entry_id === this._selectedEntryId) || null;
  }

  // --- Signed path helper (kept for FTP downloads/uploads) ---
  async _signedPath(path) {
    const resp = await this._hass.callWS({ type: "auth/sign_path", path });
    return resp.path;
  }

  async _signedFetch(path, options = {}) {
    const signed = await this._signedPath(path);
    return fetch(signed, { credentials: "same-origin", ...options });
  }

  async _loadPayloads() {
    if (!this._hass) return;
    try {
      const resp = await this._hass.callWS({ type: "ps4_goldhen/list_payloads" });
      this._payloads = resp.payloads || [];
      this._payloadDir = resp.payload_dir || "";
      if (!this._selectedPayload && this._payloads.length) {
        this._selectedPayload = this._payloads[0];
      }
    } catch (e) {
      this._payloads = [];
      this._payloadDir = "";
      this._selectedPayload = "";
      this._binStatus = `Failed to list payloads: ${e.message || e}`;
    }
  }

  // FTP
  async _loadDir(path = this._path) {
    if (!this._hass || !this._selectedEntryId) return;
    this._setLoading(true);
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_list_dir",
        entry_id: this._selectedEntryId,
        path: path,
      });
      this._path = result.path;
      this._ftpEntries = result.entries;
    } catch (e) {
      alert(`FTP Error: ${e.message || e}`);
    } finally {
      this._setLoading(false);
    }
  }

  async _deleteEntry(entry) {
    if (!confirm(`Delete ${entry.name}?`)) return;
    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_delete",
        entry_id: this._selectedEntryId,
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

    const parts = this._path.split("/").filter((p) => p);
    const parentPath = "/" + parts.join("/");
    const toPath = (parentPath === "/" ? "" : parentPath) + "/" + newName;

    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_rename",
        entry_id: this._selectedEntryId,
        from_path: entry.path,
        to_path: toPath,
      });
      this._loadDir();
    } catch (e) {
      alert(`Rename failed: ${e.message || e}`);
    }
  }

  async _editEntry(entry) {
    this._setLoading(true);
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_get_text",
        entry_id: this._selectedEntryId,
        path: entry.path,
      });
      this._editing = { path: entry.path, name: entry.name, content: result.content };
    } catch (e) {
      alert(`Read failed: ${e.message || e}`);
    } finally {
      this._setLoading(false);
    }
  }

  async _saveFile() {
    const textarea = this.shadowRoot.querySelector("#editor-textarea");
    const content = textarea ? textarea.value : "";
    this._setLoading(true);

    try {
      await this._hass.callWS({
        type: "ps4_goldhen/ftp_put_text",
        entry_id: this._selectedEntryId,
        path: this._editing.path,
        content: content,
      });
      this._editing = null;
      await this._loadDir();
    } catch (e) {
      alert(`Save failed: ${e.message || e}`);
    } finally {
      this._setLoading(false);
    }
  }

  async _downloadEntry(entry) {
    this._setLoading(true);
    try {
      const rel = `/api/ps4_goldhen/ftp/download?entry_id=${this._selectedEntryId}&path=${encodeURIComponent(
        entry.path
      )}`;

      const response = await this._signedFetch(rel, { method: "GET" });
      if (!response.ok) throw new Error(await response.text());

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = entry.name;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (e) {
      alert(`Download failed: ${e.message || e}`);
    } finally {
      this._setLoading(false);
    }
  }

  async _uploadFileToFtp() {
    const fileInput = this.shadowRoot.querySelector("#ftp-upload-input");
    if (!fileInput || !fileInput.files.length) return;

    const file = fileInput.files[0];
    this._setLoading(true);

    const formData = new FormData();
    formData.append("entry_id", this._selectedEntryId);
    formData.append("path", this._path);
    formData.append("file", file);

    try {
      const response = await this._signedFetch("/api/ps4_goldhen/ftp/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await response.text());
      await this._loadDir();
    } catch (e) {
      alert(`Upload failed: ${e.message || e}`);
    } finally {
      this._setLoading(false);
    }
  }

  // BinLoader
  async _sendPayload() {
    const entry = this._selectedEntry();
    if (!entry) {
      alert("Select a PS4 first.");
      return;
    }
    const payload = (this.shadowRoot.querySelector("#payload-select")?.value || "").trim();
    if (!payload) {
      alert("Select a payload first.");
      return;
    }

    const host = (this.shadowRoot.querySelector("#bin-host")?.value || "").trim() || entry.ps4_host;
    const port = parseInt((this.shadowRoot.querySelector("#bin-port")?.value || "").trim() || entry.binloader_port, 10);
    const timeout = parseFloat((this.shadowRoot.querySelector("#bin-timeout")?.value || "30").trim());

    this._setLoading(true);
    this._binStatus = "Sending payload...";
    this._render();

    try {
      await this._hass.callService("ps4_goldhen", "send_payload", {
        payload_file: payload,
        ps4_host: host,
        binloader_port: port,
        timeout: timeout,
      });
      this._binStatus = "Payload sent successfully.";
    } catch (e) {
      this._binStatus = `Send failed: ${e.message || e}`;
      alert(this._binStatus);
    } finally {
      this._setLoading(false);
    }
  }

  _render() {
    const entry = this._selectedEntry();
    const entryLabel = entry ? `${entry.title || entry.ps4_host} (${entry.ps4_host})` : "No PS4 configured";

    this.shadowRoot.innerHTML = html`
      <style>
        :host { display:block; padding:16px; font-family:sans-serif; background:var(--primary-background-color); color:var(--primary-text-color); height:100vh; overflow-y:auto; }
        .topbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; padding-bottom:12px; border-bottom:1px solid var(--divider-color); margin-bottom:12px; }
        .logo { height:44px; width:auto; display:block; }
        .picker { display:flex; gap:8px; align-items:center; background:var(--secondary-background-color); padding:8px 10px; border-radius:6px; flex-wrap:wrap; }
        select, input[type="text"], input[type="number"] { padding:6px 8px; border-radius:6px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); }
        .tabs { display:flex; gap:8px; margin:12px 0 16px 0; flex-wrap:wrap; }
        .tabbtn { cursor:pointer; padding:8px 12px; border-radius:999px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); }
        .tabbtn.active { border-color:var(--primary-color); box-shadow:0 0 0 2px rgba(3,169,244,0.25); }
        .loading { font-style:italic; color:var(--secondary-text-color); margin:8px 0; }
        .card { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:10px; padding:12px; margin-bottom:12px; }
        .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:8px 0; }
        .muted { color:var(--secondary-text-color); font-size:13px; }

        .header { display:flex; align-items:center; margin-bottom:16px; border-bottom:1px solid var(--divider-color); padding-bottom:8px; gap:8px; flex-wrap:wrap; }
        .path { flex:1; font-weight:bold; font-family:monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:200px; }
        .nav-btns { display:flex; gap:4px; }
        .upload-section { display:flex; align-items:center; gap:8px; background:var(--secondary-background-color); padding:4px 8px; border-radius:4px; }
        table { width:100%; border-collapse:collapse; margin-top:8px; }
        th { text-align:left; padding:8px; border-bottom:2px solid var(--divider-color); }
        td { padding:8px; border-bottom:1px solid var(--divider-color); vertical-align:middle; }
        tr:hover { background:var(--secondary-background-color); }
        .folder { color:var(--primary-color); cursor:pointer; text-decoration:underline; }
        .actions { display:flex; gap:4px; }
        .actions button, .nav-btns button, .btn { cursor:pointer; padding:6px 10px; background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:6px; color:var(--primary-text-color); }
        .actions button:hover, .nav-btns button:hover, .btn:hover { background:var(--secondary-background-color); }

        .editor-overlay { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.7); display:flex; align-items:center; justify-content:center; z-index:1000; }
        .editor-container { background:var(--primary-background-color); width:90%; height:90%; display:flex; flex-direction:column; padding:16px; border-radius:8px; box-shadow:0 4px 20px rgba(0,0,0,0.5); }
        #editor-textarea { flex:1; font-family:Consolas,Monaco,monospace; font-size:14px; padding:12px; border:1px solid var(--divider-color); background:var(--secondary-background-color); color:var(--primary-text-color); resize:none; outline:none; }
        .editor-actions { margin-top:16px; display:flex; justify-content:flex-end; gap:12px; }
        .editor-actions button { padding:8px 20px; border-radius:6px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); cursor:pointer; }
        .btn-save { background:var(--primary-color)!important; color:#fff!important; border:none!important; }
      </style>

      <div class="topbar">
        <img class="logo" src="/api/ps4_goldhen/frontend/goldhen_logo.png" alt="GoldHEN">
        <div class="picker">
          <div>
            <div class="muted">Selected PS4</div>
            <div style="font-weight:600">${entryLabel}</div>
          </div>
          <select id="entry-select">
            ${this._entries
              .map((e) => {
                const label = `${e.title || e.ps4_host} — ${e.ps4_host}`;
                const sel = e.entry_id === this._selectedEntryId ? "selected" : "";
                return `<option value="${e.entry_id}" ${sel}>${label}</option>`;
              })
              .join("")}
          </select>
          <button class="btn" id="btn-reload-entries">Reload</button>
        </div>
      </div>

      <div class="tabs">
        <button class="tabbtn ${this._tab === "ftp" ? "active" : ""}" data-tab="ftp">FTP</button>
        <button class="tabbtn ${this._tab === "binloader" ? "active" : ""}" data-tab="binloader">BinLoader</button>
      </div>

      ${this._loading ? `<div class="loading">Processing...</div>` : ""}

      ${this._tab === "ftp" ? this._renderFtp() : ""}
      ${this._tab === "binloader" ? this._renderBinLoader() : ""}

      ${this._editing ? this._renderEditor() : ""}
    `;

    const sel = this.shadowRoot.querySelector("#entry-select");
    if (sel) {
      sel.onchange = async () => {
        this._selectedEntryId = sel.value;
        this._editing = null;
        this._path = "/";
        this._ftpEntries = [];

        const entry = this._selectedEntry();
        if (entry) {
          this._binHost = entry.ps4_host || "";
          this._binPort = String(entry.binloader_port ?? "");
        }

        await this._loadDir("/");
        this._render();
      };
    }

    const reloadBtn = this.shadowRoot.querySelector("#btn-reload-entries");
    if (reloadBtn) {
      reloadBtn.onclick = async () => {
        this._setLoading(true);
        await this._loadEntries();
        await this._loadPayloads();
        this._setLoading(false);
        if (this._selectedEntryId) await this._loadDir("/");
      };
    }

    this.shadowRoot.querySelectorAll(".tabbtn").forEach((b) => {
      b.onclick = () => {
        this._tab = b.dataset.tab;
        this._render();
      };
    });

    if (this._tab === "ftp") this._bindFtpEvents();

    if (this._tab === "binloader") {
      const btn = this.shadowRoot.querySelector("#btn-send-payload");
      if (btn) btn.onclick = () => this._sendPayload();

      const refreshPayloads = this.shadowRoot.querySelector("#btn-refresh-payloads");
      if (refreshPayloads) refreshPayloads.onclick = async () => {
        this._setLoading(true);
        await this._loadPayloads();
        this._setLoading(false);
      };
    }

    if (this._editing) {
      const cancel = this.shadowRoot.querySelector("#btn-cancel");
      const save = this.shadowRoot.querySelector("#btn-save");
      if (cancel) cancel.onclick = () => { this._editing = null; this._render(); };
      if (save) save.onclick = () => this._saveFile();
    }
  }

  _renderFtp() {
    return html`
      <div class="header">
        <div class="path">PS4 FTP: ${this._path}</div>
        <div class="nav-btns">
          <button id="btn-root">Root</button>
          <button id="btn-back">Back</button>
          <button id="btn-refresh">Refresh</button>
        </div>
        <div class="upload-section">
          <input type="file" id="ftp-upload-input" style="display:none">
          <button id="btn-ftp-select">Select File</button>
          <button id="btn-ftp-upload">Upload to Current Folder</button>
        </div>
      </div>

      <table>
        <thead>
          <tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr>
        </thead>
        <tbody>
          ${this._ftpEntries.map(e => `
            <tr>
              <td>
                <span class="${e.is_dir ? "folder" : "file"}" data-path="${e.path}" data-isdir="${e.is_dir}">
                  ${e.is_dir ? "📁" : "📄"} ${e.name}
                </span>
              </td>
              <td>${e.is_dir ? "-" : (e.size / 1024 / 1024).toFixed(2) + " MB"}</td>
              <td>${e.modified}</td>
              <td class="actions">
                ${!e.is_dir ? `<button data-action="download" data-path="${e.path}" data-name="${e.name}">💾</button>` : ""}
                ${!e.is_dir ? `<button data-action="edit" data-path="${e.path}" data-name="${e.name}">✏️</button>` : ""}
                <button data-action="rename" data-path="${e.path}" data-name="${e.name}">🏷️</button>
                <button data-action="delete" data-path="${e.path}" data-isdir="${e.is_dir}" data-name="${e.name}">🗑️</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  _renderBinLoader() {
    return html`
      <div class="card">
        <h3>Send payload</h3>
        <div class="row">
          <select id="payload-select" style="min-width:320px;">
            ${this._payloads.map(p => {
              const sel = p === this._selectedPayload ? "selected" : "";
              return `<option value="${p}" ${sel}>${p}</option>`;
            }).join("")}
          </select>
          <button class="btn" id="btn-refresh-payloads">Refresh payload list</button>
        </div>
        <div class="muted">Payload directory on HA: ${this._payloadDir || "(unknown)"}</div>
        <div class="row" style="margin-top:10px;">
          <input id="bin-host" type="text" placeholder="PS4 Host" value="${this._binHost}" style="min-width:240px;">
          <input id="bin-port" type="number" placeholder="Port" value="${this._binPort}" style="width:160px;">
          <input id="bin-timeout" type="number" placeholder="Timeout (s)" value="${this._binTimeout}" style="width:160px;">
          <button class="btn" id="btn-send-payload">Send</button>
        </div>
      </div>

      ${this._binStatus ? `<div class="card"><h3>Status</h3><div>${this._binStatus}</div></div>` : ""}
    `;
  }

  _bindFtpEvents() {
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
        else if (action === "rename") this._renameEntry({ name, path, is_dir: isDir });
        else if (action === "edit") this._editEntry({ name, path, is_dir: isDir });
        else if (action === "download") this._downloadEntry({ name, path, is_dir: isDir });
      };
    }

    const root = this.shadowRoot.querySelector("#btn-root");
    const back = this.shadowRoot.querySelector("#btn-back");
    const refresh = this.shadowRoot.querySelector("#btn-refresh");
    if (root) root.onclick = () => this._loadDir("/");
    if (back) back.onclick = () => this._loadDir(this._path.split("/").slice(0, -1).join("/") || "/");
    if (refresh) refresh.onclick = () => this._loadDir();

    const btnSelect = this.shadowRoot.querySelector("#btn-ftp-select");
    const uploadInput = this.shadowRoot.querySelector("#ftp-upload-input");
    const btnUpload = this.shadowRoot.querySelector("#btn-ftp-upload");

    if (btnSelect && uploadInput) btnSelect.onclick = () => uploadInput.click();
    if (btnUpload) btnUpload.onclick = () => this._uploadFileToFtp();

    if (uploadInput && btnUpload) {
      uploadInput.onchange = () => {
        btnUpload.textContent = uploadInput.files.length
          ? `Upload: ${uploadInput.files[0].name}`
          : "Upload to Current Folder";
      };
    }
  }

  _renderEditor() {
    return html`
      <div class="editor-overlay">
        <div class="editor-container">
          <div style="margin-bottom:10px">
            <strong>Editing: ${this._editing.name}</strong><br>
            <small class="muted">${this._editing.path}</small>
          </div>
          <textarea id="editor-textarea" spellcheck="false">${this._editing.content}</textarea>
          <div class="editor-actions">
            <button id="btn-cancel">Cancel</button>
            <button id="btn-save" class="btn-save">Save to PS4</button>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define("ps4-goldhen-panel", PS4GoldHENPanel);
