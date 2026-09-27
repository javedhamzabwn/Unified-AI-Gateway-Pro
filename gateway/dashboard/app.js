/* Unified AI Gateway Pro dashboard — vanilla JS, no external dependencies. */
"use strict";

const state = {
  token: sessionStorage.getItem("uag_token") || "",
  tab: "overview",
  usageDays: "1",
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showLogin(msg) {
  document.getElementById("login-overlay").classList.add("show");
  if (msg) document.getElementById("login-err").textContent = msg;
}
function hideLogin() {
  document.getElementById("login-overlay").classList.remove("show");
  document.getElementById("login-err").textContent = "";
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({
    headers: {
      "Authorization": "Bearer " + state.token,
      "Content-Type": "application/json",
    },
  }, opts || {}));
  if (res.status === 401) {
    showLogin("Invalid or missing admin token.");
    throw new Error("unauthorized");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data.error && data.error.message) || ("HTTP " + res.status));
  return data;
}

function pill(text, kind) {
  return '<span class="pill ' + kind + '">' + esc(text) + "</span>";
}
function okPill(v) { return v ? pill("enabled", "ok") : pill("disabled", "mut"); }
function healthPill(h) {
  if (!h) return pill("unknown", "mut");
  return h.ok ? pill("healthy", "ok") : pill("unhealthy", "bad");
}
function fmtInt(n) { return Number(n || 0).toLocaleString("en-US"); }
function fmtMoney(n) { return "$" + Number(n || 0).toFixed(4); }
function fmtMs(n) { return n == null ? "—" : Math.round(n) + " ms"; }
function fmtUptime(s) {
  s = Math.floor(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? h + "h " + m + "m" : m + "m " + (s % 60) + "s";
}
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(typeof ts === "number" ? ts * 1000 : ts);
  return isNaN(d) ? esc(ts) : d.toLocaleString();
}

/* ---------------- tabs ---------------- */
document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  state.tab = btn.dataset.tab;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-" + state.tab).classList.add("active");
  refreshTab();
});

document.getElementById("btn-login").addEventListener("click", async () => {
  const tok = document.getElementById("login-token").value.trim();
  if (!tok) return;
  state.token = tok;
  sessionStorage.setItem("uag_token", tok);
  try {
    await api("/admin/status");
    hideLogin();
    document.getElementById("login-token").value = "";
    refreshAll();
  } catch (e) { /* login overlay already shows the error */ }
});
document.getElementById("login-token").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("btn-login").click();
});
document.getElementById("btn-logout").addEventListener("click", () => {
  state.token = "";
  sessionStorage.removeItem("uag_token");
  showLogin();
});

/* ---------------- overview ---------------- */
async function renderOverview() {
  const dot = document.getElementById("status-dot");
  try {
    const [status, usage, health, failures] = await Promise.all([
      api("/admin/status"),
      api("/admin/usage?days=1"),
      api("/admin/health"),
      api("/admin/requests?limit=5&status=error"),
    ]);
    dot.className = status.status === "ok" ? "ok" : "bad";
    const t = usage.totals || {};
    const sr = t.requests ? Math.round(100 * (t.requests - (t.errors || 0)) / t.requests) : null;
    document.getElementById("ov-cards").innerHTML =
      card("Gateway", esc(status.status), "uptime " + fmtUptime(status.uptime_s) + " · pid " + esc(status.pid)) +
      card("Requests (today)", fmtInt(t.requests), "success rate " + (sr == null ? "—" : sr + "%")) +
      card("Tokens (today)", fmtInt(t.prompt_tokens) + " in / " + fmtInt(t.completion_tokens) + " out", "") +
      card("Est. cost (today)", fmtMoney(t.cost_usd), "estimates, not bills") +
      card("Providers", status.providers_enabled + " / " + status.providers_total + " enabled", "") +
      card("API keys", fmtInt(status.keys_total), status.models_enabled + " / " + status.models_total + " models enabled");

    const provs = health.providers || {};
    const names = Object.keys(provs);
    document.getElementById("ov-health").innerHTML = names.length
      ? '<table><tr><th>Provider</th><th>Status</th><th>Latency</th><th>Detail</th><th>Checked</th></tr>' +
        names.map(n => {
          const h = provs[n] || {};
          return "<tr><td class='mono'>" + esc(n) + "</td><td>" + healthPill(h) + "</td><td>" +
            fmtMs(h.latency_ms) + "</td><td>" + esc(h.detail || "") + "</td><td>" +
            fmtTime(h.checked_at) + "</td></tr>";
        }).join("") + "</table>"
      : '<div class="empty">No providers configured.</div>';

    const fails = failures.requests || [];
    document.getElementById("ov-failures").innerHTML = fails.length
      ? '<table><tr><th>Time</th><th>Provider</th><th>Model</th><th>Error</th><th>Latency</th></tr>' +
        fails.map(r => "<tr><td>" + fmtTime(r.ts) + "</td><td class='mono'>" + esc(r.provider) +
          "</td><td class='mono'>" + esc(r.model) + "</td><td>" + esc(r.error || "") +
          "</td><td>" + fmtMs(r.latency_ms) + "</td></tr>").join("") + "</table>"
      : '<div class="empty">No recent failures. Nice.</div>';
  } catch (e) { dot.className = "bad"; }
}
function card(label, value, sub) {
  return '<div class="card"><div class="label">' + esc(label) + '</div><div class="value">' +
    value + '</div>' + (sub ? '<div class="sub">' + sub + "</div>" : "") + "</div>";
}

/* ---------------- providers ---------------- */
async function renderProviders() {
  const el = document.getElementById("providers-table");
  const data = await api("/admin/providers");
  const provs = data.providers || [];
  if (!provs.length) { el.innerHTML = '<div class="empty">No providers configured.</div>'; return; }
  let usageByProv = {};
  try {
    const u = await api("/admin/usage?days=30");
    (u.by_provider || []).forEach(p => { usageByProv[p.provider] = p; });
  } catch (e) {}
  el.innerHTML = '<table><tr><th>Provider</th><th>Status</th><th>Enabled</th><th>Base URL</th>' +
    "<th>Keys</th><th>Models</th><th>Req (30d)</th><th>Err (30d)</th><th>Latency</th></tr>" +
    provs.map(p => {
      const u = usageByProv[p.name] || {};
      const h = p.health || {};
      return "<tr><td class='mono'><b>" + esc(p.name) + "</b></td><td>" + healthPill(p.health) +
        "</td><td>" + okPill(p.enabled) + "</td><td class='mono'>" + esc(p.base_url) +
        "</td><td>" + fmtInt(p.key_count) + "</td><td>" + fmtInt(p.model_count) +
        "</td><td>" + fmtInt(u.requests) + "</td><td>" + fmtInt(u.errors) +
        "</td><td>" + fmtMs(h.latency_ms) + "</td></tr>";
    }).join("") + "</table>";
}
document.getElementById("btn-prov-refresh").addEventListener("click", renderProviders);

/* ---------------- models ---------------- */
async function renderModels() {
  const el = document.getElementById("models-table");
  const data = await api("/admin/models");
  const models = data.models || [];
  if (!models.length) { el.innerHTML = '<div class="empty">No models configured.</div>'; return; }
  el.innerHTML = '<table><tr><th>Model</th><th>Provider</th><th>Status</th><th>Context</th>' +
    "<th>Price in/out per 1k</th><th>Capabilities</th><th>Priority</th><th>Fallbacks</th><th></th></tr>" +
    models.map(m => "<tr><td class='mono'><b>" + esc(m.id) + "</b><br><span style='color:var(--muted)'>" +
      esc(m.display_name || "") + "</span></td><td class='mono'>" + esc(m.provider) + "</td><td>" +
      okPill(m.enabled) + "</td><td>" + (m.context_window ? fmtInt(m.context_window) : "—") + "</td><td class='mono'>" +
      fmtMoney(m.input_price_per_1k) + " / " + fmtMoney(m.output_price_per_1k) + "</td><td>" +
      esc((m.capabilities || []).join(", ")) + "</td><td>" + esc(m.priority) + "</td><td class='mono'>" +
      esc((m.fallbacks || []).join(", ")) + "</td>" +
      "<td><button class='btn ghost small' data-model-toggle='" + esc(m.id) + "'>" +
      (m.enabled ? "Disable" : "Enable") + "</button></td></tr>").join("") + "</table>";
}
document.getElementById("models-table").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-model-toggle]");
  if (!btn) return;
  const id = btn.getAttribute("data-model-toggle");
  const enabling = btn.textContent.trim() === "Enable";
  if (!confirm((enabling ? "Enable" : "Disable") + " model " + id + "?")) return;
  await api("/admin/models/" + encodeURIComponent(id), {
    method: "PATCH", body: JSON.stringify({ enabled: enabling }),
  });
  renderModels();
});
document.getElementById("btn-models-refresh").addEventListener("click", renderModels);

/* ---------------- keys ---------------- */
async function loadKeyProviders() {
  const data = await api("/admin/providers");
  const sel = document.getElementById("key-provider");
  const filt = document.getElementById("key-filter");
  sel.innerHTML = (data.providers || []).map(p =>
    '<option value="' + esc(p.name) + '">' + esc(p.name) + "</option>").join("");
  const cur = filt.value;
  filt.innerHTML = '<option value="">All providers</option>' + (data.providers || []).map(p =>
    '<option value="' + esc(p.name) + '">' + esc(p.name) + "</option>").join("");
  filt.value = cur;
}
async function renderKeys() {
  const el = document.getElementById("keys-table");
  const prov = document.getElementById("key-filter").value;
  const data = await api("/admin/keys" + (prov ? "?provider=" + encodeURIComponent(prov) : ""));
  const keys = data.keys || [];
  if (!keys.length) { el.innerHTML = '<div class="empty">No API keys stored.</div>'; return; }
  el.innerHTML = '<table><tr><th>Label</th><th>Provider</th><th>Masked key</th><th>Status</th>' +
    "<th>Requests</th><th>Errors</th><th>Last used</th><th>Last error</th><th></th></tr>" +
    keys.map(k => "<tr><td><b>" + esc(k.label) + "</b><br><span class='mono' style='color:var(--muted)'>" +
      esc(k.id) + "</span></td><td class='mono'>" + esc(k.provider) + "</td><td class='mono'>" +
      esc(k.masked) + "</td><td>" + okPill(k.enabled) +
      (k.cooling_until && k.cooling_until * 1000 > Date.now() ? " " + pill("cooling", "warn") : "") +
      "</td><td>" + fmtInt(k.total_requests) + "</td><td>" + fmtInt(k.total_errors) +
      "</td><td>" + fmtTime(k.last_used_at) + "</td><td style='max-width:260px;overflow:hidden;text-overflow:ellipsis'>" +
      esc(k.last_error || "") + "</td><td style='white-space:nowrap'>" +
      "<button class='btn ghost small' data-key-toggle='" + esc(k.id) + "' data-enabled='" + (k.enabled ? 1 : 0) + "'>" +
      (k.enabled ? "Disable" : "Enable") + "</button> " +
      "<button class='btn danger small' data-key-del='" + esc(k.id) + "'>Delete</button></td></tr>"
    ).join("") + "</table>";
}
document.getElementById("key-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const provider = document.getElementById("key-provider").value;
  const label = document.getElementById("key-label").value.trim();
  const secret = document.getElementById("key-secret").value;
  if (!provider || !label || secret.length < 8) { alert("Provider, label and a key of 8+ chars are required."); return; }
  await api("/admin/keys", { method: "POST", body: JSON.stringify({ provider, label, api_key: secret }) });
  document.getElementById("key-label").value = "";
  document.getElementById("key-secret").value = "";
  renderKeys();
});
document.getElementById("keys-table").addEventListener("click", async (e) => {
  const tgl = e.target.closest("[data-key-toggle]");
  const del = e.target.closest("[data-key-del]");
  if (tgl) {
    const id = tgl.getAttribute("data-key-toggle");
    const enabling = tgl.getAttribute("data-enabled") !== "1";
    await api("/admin/keys/" + encodeURIComponent(id), {
      method: "PATCH", body: JSON.stringify({ enabled: enabling }),
    });
    renderKeys();
  } else if (del) {
    const id = del.getAttribute("data-key-del");
    if (!confirm("Delete key " + id + "? This cannot be undone.")) return;
    await api("/admin/keys/" + encodeURIComponent(id), { method: "DELETE" });
    renderKeys();
  }
});
document.getElementById("key-filter").addEventListener("change", renderKeys);
document.getElementById("btn-keys-refresh").addEventListener("click", renderKeys);

/* ---------------- requests ---------------- */
async function renderRequests() {
  const el = document.getElementById("requests-table");
  const status = document.getElementById("req-status").value;
  const limit = document.getElementById("req-limit").value;
  const data = await api("/admin/requests?limit=" + limit + (status ? "&status=" + status : ""));
  const rows = data.requests || [];
  if (!rows.length) { el.innerHTML = '<div class="empty">No requests recorded.</div>'; return; }
  el.innerHTML = '<table><tr><th>Time</th><th>Request ID</th><th>Provider</th><th>Model</th>' +
    "<th>Status</th><th>Latency</th><th>Tokens in/out</th><th>Est. cost</th><th>Error</th></tr>" +
    rows.map(r => "<tr><td>" + fmtTime(r.ts) + "</td><td class='mono'>" + esc((r.request_id || "").slice(0, 12)) +
      "</td><td class='mono'>" + esc(r.provider) + "</td><td class='mono'>" + esc(r.model) +
      "</td><td>" + (r.status === "ok" ? pill("ok", "ok") : pill("error", "bad")) + "</td><td>" +
      fmtMs(r.latency_ms) + "</td><td>" + fmtInt(r.prompt_tokens) + " / " + fmtInt(r.completion_tokens) +
      "</td><td>" + fmtMoney(r.cost_usd) + "</td><td style='max-width:280px;overflow:hidden;text-overflow:ellipsis'>" +
      esc(r.error || "") + "</td></tr>").join("") + "</table>";
}
["req-status", "req-limit"].forEach(id =>
  document.getElementById(id).addEventListener("change", renderRequests));
document.getElementById("btn-req-refresh").addEventListener("click", renderRequests);

/* ---------------- usage ---------------- */
document.querySelectorAll("#tab-usage [data-days]").forEach(b =>
  b.addEventListener("click", () => { state.usageDays = b.getAttribute("data-days"); renderUsage(); }));
async function renderUsage() {
  const data = await api("/admin/usage?days=" + state.usageDays);
  const t = data.totals || {};
  const sr = t.requests ? Math.round(100 * (t.requests - (t.errors || 0)) / t.requests) : null;
  document.getElementById("usage-cards").innerHTML =
    card("Requests", fmtInt(t.requests), "errors: " + fmtInt(t.errors)) +
    card("Success rate", sr == null ? "—" : sr + "%", "") +
    card("Tokens", fmtInt(t.prompt_tokens) + " in / " + fmtInt(t.completion_tokens) + " out", "") +
    card("Est. cost", fmtMoney(t.cost_usd), "estimates, not bills");
  const bp = data.by_provider || [];
  document.getElementById("usage-by-provider").innerHTML = bp.length
    ? "<table><tr><th>Provider</th><th>Requests</th><th>Errors</th><th>Tokens in/out</th><th>Est. cost</th></tr>" +
      bp.map(p => "<tr><td class='mono'><b>" + esc(p.provider) + "</b></td><td>" + fmtInt(p.requests) +
        "</td><td>" + fmtInt(p.errors) + "</td><td>" + fmtInt(p.prompt_tokens) + " / " +
        fmtInt(p.completion_tokens) + "</td><td>" + fmtMoney(p.cost_usd) + "</td></tr>").join("") + "</table>"
    : '<div class="empty">No usage in this period.</div>';
  const bm = data.by_model || [];
  document.getElementById("usage-by-model").innerHTML = bm.length
    ? "<table><tr><th>Model</th><th>Requests</th><th>Errors</th><th>Tokens in/out</th><th>Est. cost</th></tr>" +
      bm.map(p => "<tr><td class='mono'><b>" + esc(p.model) + "</b></td><td>" + fmtInt(p.requests) +
        "</td><td>" + fmtInt(p.errors) + "</td><td>" + fmtInt(p.prompt_tokens) + " / " +
        fmtInt(p.completion_tokens) + "</td><td>" + fmtMoney(p.cost_usd) + "</td></tr>").join("") + "</table>"
    : '<div class="empty">No usage in this period.</div>';
}

/* ---------------- logs ---------------- */
async function renderLogs() {
  const lines = document.getElementById("log-lines").value;
  const data = await api("/admin/logs?lines=" + lines);
  const el = document.getElementById("logs-pre");
  el.textContent = (data.lines || []).join("\n") || "No log lines.";
}
document.getElementById("btn-logs-refresh").addEventListener("click", renderLogs);

/* ---------------- settings ---------------- */
async function renderSettings() {
  const data = await api("/admin/config");
  const cfg = data.config || {};
  const el = document.getElementById("settings-table");
  const skip = { providers: 1, models: 1 };
  el.innerHTML = "<table><tr><th>Setting</th><th>Value</th></tr>" +
    Object.keys(cfg).filter(k => !skip[k]).map(k => {
      let v = cfg[k];
      if (k === "admin_token") v = "(never shown)";
      else if (Array.isArray(v)) v = v.length ? v.join(", ") : "—";
      else if (typeof v === "object" && v !== null) v = JSON.stringify(v);
      return "<tr><td class='mono'>" + esc(k) + "</td><td class='mono'>" + esc(v) + "</td></tr>";
    }).join("") + "</table>" +
    "<p class='note'>Providers: " + (cfg.providers || []).length +
    " · Models: " + (cfg.models || []).length +
    ". Edit config/gateway.json and restart to change providers; models can be toggled above.</p>";
}
document.getElementById("btn-cfg-refresh").addEventListener("click", renderSettings);

/* ---------------- boot ---------------- */
async function refreshTab() {
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "providers") await renderProviders();
    else if (state.tab === "models") await renderModels();
    else if (state.tab === "keys") { await loadKeyProviders(); await renderKeys(); }
    else if (state.tab === "requests") await renderRequests();
    else if (state.tab === "usage") await renderUsage();
    else if (state.tab === "logs") await renderLogs();
    else if (state.tab === "settings") await renderSettings();
  } catch (e) { /* 401 handled by api(); other errors stay silent to avoid nagging */ }
}
function refreshAll() { refreshTab(); }
setInterval(() => { if (state.tab === "overview" && state.token) renderOverview().catch(() => {}); }, 10000);

if (!state.token) showLogin();
else api("/admin/status").then(() => refreshAll()).catch(() => {});
