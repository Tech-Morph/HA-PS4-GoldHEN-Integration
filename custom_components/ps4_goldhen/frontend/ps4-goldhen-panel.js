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

    this._path = "/";
    this._ftpEntries = [];
    this._editing = null;

    this._installStatus = "";
  }

  async _init() {
    await this._loadEntries();
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
    } catch (e) {
      this._entries = [];
      this._selectedEntryId = null;
      alert(`Failed to load PS4 entries: ${e.message || e}`);
    }
  }

  _selectedEntry() {
    return this._entries.find((e) => e.entry_id === this._selectedEntryId) || null;
  }

  // --- Signed path helper (avoids Bearer header problems) ---
  async _signedPath(path) {
    const resp = await this._hass.callWS({ type: "auth/sign_path", path });
    return resp.path;
  }

  async _signedFetch(path, options = {}) {
    const signed = await this._signedPath(path);
    return fetch(signed, { credentials: "same-origin", ...options });
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

  // Installer
  async _installFromUrl() {
    const entry = this._selectedEntry();
    if (!entry) {
      alert("Select a PS4 first.");
      return;
    }

    const url = (this.shadowRoot.querySelector("#pkg-url")?.value || "").trim();
    const portStr = (this.shadowRoot.querySelector("#pkg-port")?.value || "").trim();
    if (!url) {
      alert("Enter a PKG URL.");
      return;
    }

    this._setLoading(true);
    this._installStatus = "Sending install request...";
    this._render();

    try {
      const msg = {
        type: "ps4_goldhen/rpi_install_url",
        entry_id: this._selectedEntryId,
        url: url,
      };
      if (portStr) msg.port = parseInt(portStr, 10);

      await this._hass.callWS(msg);
      this._installStatus = "Install request sent. Check PS4 download/install progress.";
    } catch (e) {
      this._installStatus = `Install failed: ${e.message || e}`;
      alert(this._installStatus);
    } finally {
      this._setLoading(false);
    }
  }

  async _uploadAndInstallLocalPkg() {
    const entry = this._selectedEntry();
    if (!entry) {
      alert("Select a PS4 first.");
      return;
    }

    const fileInput = this.shadowRoot.querySelector("#local-pkg-input");
    if (!fileInput || !fileInput.files.length) {
      alert("Choose a .pkg file first.");
      return;
    }

    const portStr = (this.shadowRoot.querySelector("#local-pkg-port")?.value || "").trim();
    const file = fileInput.files[0];

    this._setLoading(true);
    this._installStatus = `Uploading ${file.name}...`;
    this._render();

    try {
      // Mint one-time upload token (WS is already authenticated)
      const tok = await this._hass.callWS({
        type: "ps4_goldhen/rpi_begin_upload",
        entry_id: this._selectedEntryId,
      });

      const formData = new FormData();
      if (portStr) formData.append("port", portStr);
      formData.append("file", file);

      // Tokenized endpoint (LAN-only + one-time token)
      const resp = await fetch(`/api/ps4_goldhen/rpi/upload_install/${tok.token}`, {
        method: "POST",
        body: formData,
      });

      const text = await resp.text();
      if (!resp.ok) throw new Error(text);

      const data = JSON.parse(text);
      this._installStatus = `Upload complete. Install started on PS4 (${data.ps4_host}:${data.ps4_port}).`;
    } catch (e) {
      this._installStatus = `Upload/install failed: ${e.message || e}`;
      alert(this._installStatus);
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
        .title { font-weight:700; font-size:18px; }
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
        <div class="title">PS4 GoldHEN Dashboard</div>
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
        <button class="tabbtn ${this._tab === "installer" ? "active" : ""}" data-tab="installer">Installer</button>
      </div>

      ${this._loading ? `<div class="loading">Processing...</div>` : ""}

      ${this._tab === "ftp" ? this._renderFtp() : ""}
      ${this._tab === "installer" ? this._renderInstaller() : ""}

      ${this._editing ? this._renderEditor() : ""}
    `;

    const sel = this.shadowRoot.querySelector("#entry-select");
    if (sel) {
      sel.onchange = async () => {
        this._selectedEntryId = sel.value;
        this._editing = null;
        this._path = "/";
        this._ftpEntries = [];
        await this._loadDir("/");
      };
    }

    const reloadBtn = this.shadowRoot.querySelector("#btn-reload-entries");
    if (reloadBtn) {
      reloadBtn.onclick = async () => {
        this._setLoading(true);
        await this._loadEntries();
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

    if (this._tab === "installer") {
      const btnInstallUrl = this.shadowRoot.querySelector("#btn-install-url");
      if (btnInstallUrl) btnInstallUrl.onclick = () => this._installFromUrl();

      const btnLocalInstall = this.shadowRoot.querySelector("#btn-install-local");
      if (btnLocalInstall) btnLocalInstall.onclick = () => this._uploadAndInstallLocalPkg();
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

  _renderInstaller() {
    return html`
      <div class="card">
        <h3>Install from URL</h3>
        <div class="row">
          <input id="pkg-url" type="text" placeholder="http://server/game.pkg" style="min-width:420px; flex:1;">
          <input id="pkg-port" type="number" placeholder="Port (optional)" style="width:240px;">
          <button class="btn" id="btn-install-url">Install URL</button>
        </div>
        <div class="muted">Sends URL to PS4 installer (port 12800 by default).</div>
      </div>

      <div class="card">
        <h3>Install local file (select from this device)</h3>
        <div class="row">
          <input id="local-pkg-input" type="file" accept=".pkg" style="min-width:420px; flex:1;">
          <input id="local-pkg-port" type="number" placeholder="Port override (optional)" style="width:240px;">
          <button class="btn" id="btn-install-local">Upload & Install</button>
        </div>
        <div class="muted">Large PKGs require free space in /config on HAOS while the PS4 downloads.</div>
      </div>

      ${this._installStatus ? `<div class="card"><h3>Status</h3><div>${this._installStatus}</div></div>` : ""}
    `;
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
