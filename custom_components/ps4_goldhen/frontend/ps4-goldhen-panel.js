/**
 * PS4 GoldHEN Integration Control Panel
 * A lightweight web component for Home Assistant.
 */
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
    this._uploading = false;
    this._statusMsg = "";
  }

  async _loadDir(path = this._path) {
    if (!this._hass) return;
    this._loading = true;
    this._path = path;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_list_dir",
        entry_id: this._panel.config.entry_id,
        path: path,
      });
      this._entries = result.entries || [];
    } catch (err) {
      console.error("FTP List Dir Error:", err);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _handleUploadPkg() {
    const fileInput = this.shadowRoot.getElementById("pkg-upload");
    const file = fileInput.files[0];
    if (!file) {
      alert("Please select a .pkg file first.");
      return;
    }

    this._uploading = true;
    this._statusMsg = `Uploading ${file.name}...`;
    this._render();

    const formData = new FormData();
    formData.append("file", file);
    formData.append("entry_id", this._panel.config.entry_id);

    try {
      const resp = await fetch("/api/ps4_goldhen/pkg/upload", {
        method: "POST",
        body: formData,
        headers: {
          "Authorization": "Bearer " + this._hass.auth.data.access_token,
        },
      });

      if (resp.ok) {
        this._statusMsg = "Upload successful! Installation triggered.";
      } else {
        const errText = await resp.text();
        this._statusMsg = `Upload failed: ${errText}`;
      }
    } catch (err) {
      this._statusMsg = `Error: ${err.message}`;
    } finally {
      this._uploading = false;
      fileInput.value = "";
      this._render();
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 16px;
          color: var(--primary-text-color);
          background-color: var(--primary-background-color);
          min-height: 100%;
        }
        ha-card {
          padding: 16px;
          margin-bottom: 24px;
          display: block;
          background: var(--ha-card-background, var(--card-background-color, white));
          box-shadow: var(--ha-card-box-shadow, 0 2px 2px 0 rgba(0,0,0,0.14), 0 1px 5px 0 rgba(0,0,0,0.12), 0 3px 1px -2px rgba(0,0,0,0.2));
          border-radius: var(--ha-card-border-radius, 4px);
        }
        h1 { margin: 0 0 16px 0; font-size: 24px; }
        h3 { margin: 0 0 12px 0; font-size: 18px; }
        .upload-section {
          border: 2px dashed var(--divider-color);
          padding: 20px;
          border-radius: 8px;
          text-align: center;
          background: var(--secondary-background-color);
        }
        .file-list {
          width: 100%;
          border-collapse: collapse;
          margin-top: 16px;
        }
        .file-list th, .file-list td {
          text-align: left;
          padding: 12px 8px;
          border-bottom: 1px solid var(--divider-color);
        }
        .breadcrumb {
          margin-bottom: 16px;
          font-size: 1.1em;
          padding: 8px;
          background: var(--secondary-background-color);
          border-radius: 4px;
        }
        .breadcrumb span {
          color: var(--primary-color);
          cursor: pointer;
          font-weight: bold;
        }
        .action-btn {
          color: var(--primary-color);
          cursor: pointer;
          text-decoration: underline;
          margin-right: 12px;
          font-weight: 500;
        }
        .status {
          margin-top: 12px;
          font-weight: 500;
          color: var(--primary-color);
        }
        button {
          padding: 10px 20px;
          background: var(--primary-color);
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
          font-weight: bold;
          margin-top: 10px;
        }
        button:disabled {
          background: var(--disabled-text-color);
          cursor: not-allowed;
        }
        input[type="file"] {
          margin-bottom: 10px;
          display: block;
          width: 100%;
          max-width: 300px;
          margin-left: auto;
          margin-right: auto;
        }
      </style>
      
      <ha-card>
        <h1>PS4 GoldHEN Control Panel</h1>
        
        <div class="upload-section">
          <h3>Install Local PKG from Device</h3>
          <p>Directly upload a .pkg file from this device to Home Assistant. It will be served locally to your PS4 for installation.</p>
          <input type="file" id="pkg-upload" accept=".pkg">
          <button id="upload-btn" ${this._uploading ? 'disabled' : ''}>
            ${this._uploading ? 'Uploading...' : 'Upload & Install'}
          </button>
          <div class="status">${this._statusMsg}</div>
        </div>
      </ha-card>

      <ha-card>
        <h3>PS4 FTP File Browser</h3>
        <div class="breadcrumb" id="breadcrumbs">
          <span data-path="/">/</span>
          ${this._path.split('/').filter(p => p).map((p, i, arr) => `
            / <span data-path="/${arr.slice(0, i + 1).join('/')}">${p}</span>
          `).join('')}
        </div>

        ${this._loading ? '<p>Loading FTP directory...</p>' : `
          <table class="file-list">
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${this._entries.length === 0 ? '<tr><td colspan="3">No files found or FTP connection failed.</td></tr>' : 
                this._entries.map(entry => `
                <tr>
                  <td>${entry.type === 'dir' ? '📁' : '📄'} ${entry.name}</td>
                  <td>${entry.size || '-'}</td>
                  <td>
                    ${entry.type === 'dir' ? 
                      `<span class="action-btn" data-action="open" data-name="${entry.name}">Open</span>` : 
                      (entry.name.endsWith('.pkg') ? `<span class="action-btn" data-action="install" data-name="${entry.name}">Install</span>` : '')
                    }
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </ha-card>
    `;

    // Event Listeners
    this.shadowRoot.getElementById("upload-btn")?.addEventListener("click", () => this._handleUploadPkg());
    
    this.shadowRoot.getElementById("breadcrumbs")?.querySelectorAll("span").forEach(span => {
      span.addEventListener("click", () => this._loadDir(span.dataset.path));
    });

    this.shadowRoot.querySelectorAll('.action-btn[data-action="open"]').forEach(btn => {
      btn.addEventListener("click", () => {
        const newPath = (this._path === '/' ? '' : this._path) + '/' + btn.dataset.name;
        this._loadDir(newPath);
      });
    });

    this.shadowRoot.querySelectorAll('.action-btn[data-action="install"]').forEach(btn => {
      btn.addEventListener("click", async () => {
        const fullPath = (this._path === '/' ? '' : this._path) + '/' + btn.dataset.name;
        if (!confirm(`Install ${btn.dataset.name} via RPI?`)) return;
        try {
          // Trigger the ps4_goldhen.install_pkg service
          await this._hass.callService("ps4_goldhen", "install_pkg", {
            url: `ftp://ps4:ps4@${this._hass.states[this._panel.config.entry_id]?.attributes?.host || 'PS4_IP'}:2121${fullPath}`
          });
          alert("Installation request sent to RPI.");
        } catch (err) {
          alert("Error: " + err.message);
        }
      });
    });
  }
}
customElements.define("ps4-goldhen-panel", PS4GoldHENPanel);
