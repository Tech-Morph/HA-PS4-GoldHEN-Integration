/**
 * PS4 GoldHEN Integration Control Panel
 * Handles payload sending, local PKG installation (RPI), and GoldHEN Direct Install.
 */
class PS4GoldHENPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (this._path === undefined) {
      this._path = "/";
      this._loadData();
    }
  }

  set panel(panel) {
    this._panel = panel;
    this._mode = panel.config.mode || "dashboard";
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entries = [];
    this._payloads = [];
    this._loading = false;
    this._statusMsg = "";
    this._selectedPayload = "";
    this._installMethod = "rpi"; // Default install method
  }

  async _loadData() {
    if (!this._hass || !this._panel) return;
    this._loading = true;
    this._render();
    try {
      if (this._mode === "ftp") {
        await this._loadDir();
      } else {
        await this._loadPayloads();
      }
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _loadPayloads() {
    try {
      const resp = await fetch("/api/ps4_goldhen/payloads", {
        headers: {
          "Authorization": "Bearer " + this._hass.auth.data.access_token
        }
      });
      if (resp.ok) {
        this._payloads = await resp.json();
      }
    } catch (err) {
      console.error("Payload Fetch Error:", err);
    }
  }

  async _loadDir(path = this._path) {
    this._path = path;
    try {
      const result = await this._hass.callWS({
        type: "ps4_goldhen/ftp_list_dir",
        entry_id: this._panel.config.entry_id,
        path: path,
      });
      this._entries = result.entries || [];
    } catch (err) {
      this._statusMsg = `FTP Error: ${err.message}`;
    }
  }

  async _handleSendPayload() {
    if (!this._selectedPayload) return;
    this._statusMsg = `Sending payload: ${this._selectedPayload}...`;
    this._render();
    try {
      await this._hass.callService("ps4_goldhen", "send_payload", {
        payload_file: this._selectedPayload
      });
      this._statusMsg = "Payload sent successfully!";
    } catch (err) {
      this._statusMsg = `Error: ${err.message}`;
    }
    this._render();
  }

  async _handleUploadPkg() {
    const fileInput = this.shadowRoot.getElementById("pkg-upload");
    const file = fileInput.files[0];
    if (!file) return;

    this._statusMsg = `Uploading ${file.name} to HA...`;
    this._render();

    const formData = new FormData();
    formData.append("file", file);

    try {
      const resp = await fetch("/api/ps4_goldhen/upload", {
        method: "POST",
        body: formData,
        headers: {
          "Authorization": "Bearer " + this._hass.auth.data.access_token
        }
      });
      if (resp.ok) {
        const res = await resp.json();
        this._statusMsg = `File uploaded. Triggering ${this._installMethod.toUpperCase()} install...`;
        this._render();
        await this._hass.callService("ps4_goldhen", "install_pkg", {
          url: res.filename,
          method: this._installMethod
        });
        this._statusMsg = "Installation triggered successfully!";
      } else {
        this._statusMsg = `Upload failed: ${await resp.text()}`;
      }
    } catch (err) {
      this._statusMsg = `Error: ${err.message}`;
    }
    fileInput.value = "";
    this._render();
  }

  async _handleInstallFtp(name, method) {
    const fullPath = (this._path === "/" ? "" : this._path) + "/" + name;
    if (!confirm(`Install ${name} via ${method.toUpperCase()}?`)) return;

    this._statusMsg = `Triggering ${method.toUpperCase()} install for ${name}...`;
    this._render();

    let ps4Ip = "PS4_IP";
    const sensor = Object.values(this._hass.states).find(s => s.entity_id.includes("goldhen_ftp"));
    if (sensor && sensor.attributes.ps4_host) {
        ps4Ip = sensor.attributes.ps4_host;
    }

    try {
      await this._hass.callService("ps4_goldhen", "install_pkg", {
        url: `ftp://ps4:ps4@${ps4Ip}:2121${fullPath}`,
        method: method
      });
      this._statusMsg = `${method.toUpperCase()} install triggered!`;
    } catch (err) {
      this._statusMsg = `Error: ${err.message}`;
    }
    this._render();
  }

  _render() {
    const isDashboard = this._mode === "dashboard";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 16px;
          color: var(--primary-text-color);
          background: var(--primary-background-color);
          min-height: 100vh;
          font-family: sans-serif;
        }
        ha-card {
          padding: 16px;
          margin-bottom: 24px;
          border-radius: 8px;
          background: var(--ha-card-background, var(--card-background-color, white));
          box-shadow: var(--ha-card-box-shadow, 0 2px 5px rgba(0,0,0,0.1));
        }
        h1 {
          margin: 0 0 16px 0;
          font-size: 24px;
          border-bottom: 2px solid var(--primary-color);
          padding-bottom: 8px;
        }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
          gap: 20px;
        }
        .section {
          padding: 16px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--secondary-background-color);
        }
        .status {
          margin-top: 12px;
          font-weight: bold;
          color: var(--primary-color);
          padding: 10px;
          border-radius: 4px;
          background: var(--primary-background-color);
          border: 1px solid var(--primary-color);
        }
        select, button, input {
          width: 100%;
          padding: 12px;
          margin-top: 8px;
          border-radius: 4px;
          border: 1px solid var(--divider-color);
          font-size: 14px;
          box-sizing: border-box;
        }
        button {
          background: var(--primary-color);
          color: white;
          border: none;
          cursor: pointer;
          font-weight: bold;
          transition: opacity 0.2s;
        }
        button:hover {
          opacity: 0.8;
        }
        button:disabled {
          background: var(--disabled-text-color);
          cursor: not-allowed;
        }
        .radio-group {
          display: flex;
          gap: 16px;
          margin-top: 12px;
          align-items: center;
        }
        .radio-group label {
          display: flex;
          align-items: center;
          gap: 4px;
          cursor: pointer;
          font-size: 14px;
        }
        .radio-group input {
          width: auto;
          margin: 0;
        }
        .ftp-table {
          width: 100%;
          border-collapse: collapse;
          margin-top: 16px;
        }
        .ftp-table th, .ftp-table td {
          text-align: left;
          padding: 12px 8px;
          border-bottom: 1px solid var(--divider-color);
        }
        .breadcrumb {
          margin-bottom: 16px;
          padding: 8px;
          background: var(--secondary-background-color);
          border-radius: 4px;
        }
        .breadcrumb span {
          color: var(--primary-color);
          cursor: pointer;
          font-weight: bold;
        }
        .action-link {
          color: var(--primary-color);
          cursor: pointer;
          text-decoration: underline;
          margin-right: 12px;
          font-weight: 500;
        }
      </style>

      <ha-card>
        <h1>PS4 GoldHEN ${isDashboard ? "Dashboard" : "FTP Browser"}</h1>
        
        ${this._statusMsg ? `
          <div class="status">
            ℹ️ ${this._statusMsg}
          </div>
        ` : ""}

        ${isDashboard ? `
          <div class="grid">
            <div class="section">
              <h3>🚀 Payloads</h3>
              <p>Send a binary payload (.bin/.elf) to port 9090.</p>
              <select id="payload-select">
                <option value="">Select a payload...</option>
                ${this._payloads.map(p => `
                  <option value="${p}" ${this._selectedPayload === p ? 'selected' : ''}>${p}</option>
                `).join('')}
              </select>
              <button id="send-payload-btn" ${!this._selectedPayload ? 'disabled' : ''}>
                Send Payload
              </button>
            </div>

            <div class="section">
              <h3>📦 Install PKG</h3>
              <p>Upload and install a .pkg file from your computer.</p>
              <input type="file" id="pkg-upload" accept=".pkg">
              <div class="radio-group">
                <label>
                  <input type="radio" name="method" value="rpi" ${this._installMethod === 'rpi' ? 'checked' : ''}>
                  RPI App
                </label>
                <label>
                  <input type="radio" name="method" value="goldhen" ${this._installMethod === 'goldhen' ? 'checked' : ''}>
                  GoldHEN Direct
                </label>
              </div>
              <button id="upload-pkg-btn">Start Installation</button>
            </div>
          </div>
        ` : `
          <div class="breadcrumb" id="breadcrumbs">
            <span data-path="/">root</span>
            ${this._path.split('/').filter(p => p).map((p, i, arr) => `
               / <span data-path="/${arr.slice(0, i + 1).join('/')}">${p}</span>
            `).join('')}
          </div>

          ${this._loading ? '<p>Loading directory...</p>' : `
            <table class="ftp-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Size</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                ${this._entries.map(e => `
                  <tr>
                    <td>${e.is_dir ? '📁' : '📄'} ${e.name}</td>
                    <td>${e.size || '-'}</td>
                    <td>
                      ${e.is_dir ? `
                        <span class="action-link" data-action="open" data-name="${e.name}">Open</span>
                      ` : (e.name.endsWith('.pkg') ? `
                        <span class="action-link" data-action="install-rpi" data-name="${e.name}">RPI</span>
                        <span class="action-link" data-action="install-gold" data-name="${e.name}">GoldHEN</span>
                      ` : '')}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          `}
        `}
      </ha-card>
    `;

    if (isDashboard) {
      this.shadowRoot.getElementById("payload-select")?.addEventListener("change", (e) => {
        this._selectedPayload = e.target.value;
        this._render();
      });

      this.shadowRoot.querySelectorAll('input[name="method"]').forEach(radio => {
        radio.addEventListener("change", (e) => {
            this._installMethod = e.target.value;
        });
      });

      this.shadowRoot.getElementById("send-payload-btn")?.addEventListener("click", () => this._handleSendPayload());
      this.shadowRoot.getElementById("upload-pkg-btn")?.addEventListener("click", () => this._handleUploadPkg());
    } else {
      this.shadowRoot.getElementById("breadcrumbs")?.querySelectorAll("span").forEach(s => {
        s.onclick = () => {
          this._loadDir(s.dataset.path);
          this._render();
        };
      });

      this.shadowRoot.querySelectorAll('.action-link[data-action="open"]').forEach(btn => {
        btn.onclick = () => {
          this._path = (this._path === "/" ? "" : this._path) + "/" + btn.dataset.name;
          this._loadDir(this._path);
          this._render();
        };
      });

      this.shadowRoot.querySelectorAll('.action-link[data-action="install-rpi"]').forEach(btn => {
        btn.onclick = () => this._handleInstallFtp(btn.dataset.name, "rpi");
      });

      this.shadowRoot.querySelectorAll('.action-link[data-action="install-gold"]').forEach(btn => {
        btn.onclick = () => this._handleInstallFtp(btn.dataset.name, "goldhen");
      });
    }
  }
}

customElements.define("ps4-goldhen-panel", PS4GoldHENPanel);
