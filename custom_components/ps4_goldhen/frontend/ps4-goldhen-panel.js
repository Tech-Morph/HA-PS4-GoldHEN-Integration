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
    // panel.config can contain our entry_id
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entries = [];
    this._loading = false;
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

  _render() {
    this.shadowRoot.innerHTML = html`
      <style>
        :host { display: block; padding: 16px; font-family: sans-serif; background: var(--primary-background-color); color: var(--primary-text-color); height: 100vh; overflow-y: auto; }
        .header { display: flex; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--divider-color); padding-bottom: 8px; }
        .path { flex: 1; font-weight: bold; font-family: monospace; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 8px; border-bottom: 2px solid var(--divider-color); }
        td { padding: 8px; border-bottom: 1px solid var(--divider-color); vertical-align: middle; }
        tr:hover { background: var(--secondary-background-color); }
        .icon { width: 24px; vertical-align: middle; margin-right: 8px; }
        .folder { color: var(--primary-color); cursor: pointer; text-decoration: underline; }
        .file { color: var(--primary-text-color); }
        .actions button { cursor: pointer; padding: 4px 8px; margin-left: 4px; }
        .loading { font-style: italic; color: var(--secondary-text-color); }
      </style>
      <div class="header">
        <div class="path">PS4 FTP: ${this._path}</div>
        <button @click="${() => this._loadDir("/")}">Root</button>
        <button @click="${() => this._loadDir(this._path.split("/").slice(0, -1).join("/") || "/")}">Up</button>
        <button @click="${() => this._loadDir()}">Refresh</button>
      </div>
      ${this._loading ? '<div class="loading">Loading PS4 files...</div>' : ""}
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
                <button data-action="delete" data-path="${e.path}" data-isdir="${e.is_dir}" data-name="${e.name}">🗑️</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    // Event delegation for table clicks
    this.shadowRoot.querySelector("table").onclick = (ev) => {
      const target = ev.target;
      if (target.classList.contains("folder")) {
        this._loadDir(target.dataset.path);
      } else if (target.dataset.action === "delete") {
        this._deleteEntry({ name: target.dataset.name, path: target.dataset.path, is_dir: target.dataset.isdir === "true" });
      }
    };
    
    // Header buttons
    const headerBtns = this.shadowRoot.querySelectorAll(".header button");
    headerBtns[0].onclick = () => this._loadDir("/");
    headerBtns[1].onclick = () => this._loadDir(this._path.split("/").slice(0, -1).join("/") || "/");
    headerBtns[2].onclick = () => this._loadDir();
  }
}

customElements.define("ps4-goldhen-panel", PS4GoldHENPanel);
