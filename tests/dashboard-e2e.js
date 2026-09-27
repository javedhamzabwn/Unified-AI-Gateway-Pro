/* Dashboard E2E: run the REAL production dashboard (index.html + app.js,
 * unmodified) in jsdom against the LIVE gateway on 127.0.0.1:8123.
 *
 * Why jsdom: the sandbox's hardened Chromium blocks ALL local-network
 * navigation (ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS), even for
 * browser-initiated startup navigations and even with the documented
 * enterprise opt-out policy. That is a platform security boundary; this
 * script instead executes the exact production JS against the real API.
 *
 * Covers: login flow, all 8 tabs render, add-key via UI form (masked-only),
 * model toggle via UI, JS error capture.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const { JSDOM, VirtualConsole } = require("jsdom");

const BASE = "http://127.0.0.1:8123";
const TOKEN = "test-admin-token-12345";
const REPO = path.join(os.homedir(), "workspace/Unified-AI-Gateway-Pro/gateway/dashboard");

const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
virtualConsole.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

const html = fs.readFileSync(path.join(REPO, "index.html"), "utf8");

const dom = new JSDOM(html, {
  url: BASE + "/",
  runScripts: "dangerously",
  resources: "usable", // load the real app.js over HTTP from the gateway
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    // dashboard uses fetch + alert/confirm; wire to Node.
    // Browsers resolve relative URLs against the document base; replicate that.
    window.fetch = (input, init) => {
      let url = input;
      if (typeof url === "string" && url.startsWith("/")) {
        url = new URL(url, window.location.href).href;
      }
      return fetch(url, init);
    };
    window.alert = (m) => { throw new Error("alert() fired: " + m); };
    window.confirm = () => true;
  },
});

const { document } = dom.window;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, cond, extra = "") {
  results.push({ name, ok: !!cond, extra });
  console.log(`${cond ? "ok  " : "FAIL"}  ${name}${extra ? " :: " + extra : ""}`);
}

(async () => {
  await sleep(1500); // let DOMContentLoaded + initial render settle

  // 1. login overlay visible on fresh load (no token in sessionStorage)
  check("login overlay shown when no token",
    document.getElementById("login-overlay").classList.contains("show"));

  // 2. log in via the real UI
  document.getElementById("login-token").value = TOKEN;
  document.getElementById("btn-login").click();
  await sleep(2500);
  check("login dismisses overlay",
    !document.getElementById("login-overlay").classList.contains("show"));
  check("session token stored",
    dom.window.sessionStorage.getItem("uag_token") === TOKEN);

  // 3. walk every tab via the real tab buttons
  const tabs = ["overview", "providers", "models", "keys", "requests", "usage", "logs", "settings"];
  for (const tab of tabs) {
    const btn = document.querySelector(`button[data-tab="${tab}"]`);
    if (!btn) { check(`tab button ${tab} exists`, false); continue; }
    btn.click();
    await sleep(1500);
    const sec = document.getElementById("tab-" + tab);
    const active = sec.classList.contains("active");
    const len = (sec.textContent || "").trim().length;
    check(`tab ${tab} activates+renders`, active && len > 20, `${len} chars`);
  }

  // 4. add a key through the real form; assert masked-only display
  document.querySelector('button[data-tab="keys"]').click();
  await sleep(1200);
  const SECRET = "sk-e2e-ui-secret-0123456789abcdef";
  document.getElementById("key-provider").value = "kilo";
  document.getElementById("key-label").value = "e2e-ui-key";
  document.getElementById("key-secret").value = SECRET;
  document.getElementById("key-form").dispatchEvent(
    new dom.window.Event("submit", { cancelable: true, bubbles: true }));
  await sleep(2000);
  const keysText = document.getElementById("keys-table").textContent || "";
  check("key added via UI appears in table", keysText.includes("e2e-ui-key"));
  check("raw secret NEVER rendered in DOM", !document.documentElement.innerHTML.includes(SECRET));
  check("masked form shown", keysText.includes("••••") || keysText.includes("sk-"));

  // 5. toggle a model via the real UI (models table buttons)
  document.querySelector('button[data-tab="models"]').click();
  await sleep(1500);
  const modelBtn = document.querySelector("#models-table [data-model-toggle]");
  if (modelBtn) {
    const modelId = modelBtn.getAttribute("data-model-toggle");
    // dashboard's own logic: button says "Disable" when the model is enabled
    const wasEnabled = modelBtn.textContent.trim() === "Disable";
    modelBtn.click();
    await sleep(2000);
    const res = await fetch(`${BASE}/v1/models`);
    const ids = (await res.json()).data.map((m) => m.id);
    const nowListed = ids.includes(modelId);
    check(`model toggle flips listing (${modelId})`, wasEnabled ? !nowListed : nowListed,
      `wasEnabled=${wasEnabled} nowListed=${nowListed}`);
    // restore original state
    const btn2 = document.querySelector(`#models-table [data-model-toggle="${modelId}"]`);
    if (btn2) { btn2.click(); await sleep(1500); }
  } else {
    check("model toggle button exists", false);
  }

  // 6. requests tab shows the earlier live traffic
  document.querySelector('button[data-tab="requests"]').click();
  await sleep(1500);
  const reqText = document.getElementById("requests-table").textContent || "";
  check("requests tab lists traffic", reqText.length > 50, `${reqText.length} chars`);

  // 7. no JS errors during the whole run
  check("zero JS/console errors", errors.length === 0, errors.slice(0, 3).join(" | "));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n==== DASHBOARD E2E: ${failed.length === 0 ? "PASS" : "FAIL (" + failed.length + ")"} ====`);
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((e) => { console.error("E2E crashed:", e); process.exit(2); });
