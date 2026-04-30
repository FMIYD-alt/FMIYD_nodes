import { app } from "/scripts/app.js";
import { $el } from "/scripts/ui.js";

const NODE_TYPE = "FMIYDDanbooruGallery";
const WIDGET_URLS = "selected_urls";
const WIDGET_URL = "selected_url";
const WIDGET_NONCE = "selection_nonce";
const WIDGET_TAGS = "selected_tags";
const WIDGET_LOGIN = "danbooru_login";
const WIDGET_API_KEY = "danbooru_api_key";
const GALLERY_PATH = "/fmiyd/danbooru_gallery";
const GALLERY_HTML_CACHE_TAG = "20260426j";
const LOCAL_STATE_KEY = "fmiyd_danbooru_node_state_v1";

function findWidget(node, name) {
  if (!node) return null;
  if (Array.isArray(node.widgets)) {
    const w = node.widgets.find((x) => x && x.name === name);
    if (w) return w;
  }
  return null;
}
function hideWidget(w) {
  if (!w) return;
  w.computeSize = () => [0, -4];
  w.draw = () => {};
  w.type = "hidden";
}
function rebuild(node) {
  if (!Array.isArray(node?.widgets)) return;
  if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
  node.widgets.forEach((w, i) => {
    if (w && Object.prototype.hasOwnProperty.call(w, "value")) node.widgets_values[i] = w.value;
  });
}
function loadLocalState() {
  try {
    const raw = localStorage.getItem(LOCAL_STATE_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : {};
  } catch (e) {
    return {};
  }
}
function saveLocalState(partial) {
  try {
    const cur = loadLocalState();
    const next = { ...cur, ...(partial || {}) };
    localStorage.setItem(LOCAL_STATE_KEY, JSON.stringify(next));
  } catch (e) {}
}
function dirty(node) {
  node.setDirtyCanvas?.(true);
  app.canvas?.setDirty?.(true, true);
  app.graph?.change?.();
}
function isNode(node) {
  return !!(node && (node.type === NODE_TYPE || node.comfyClass === NODE_TYPE));
}
function findNode(nodeId) {
  const g = app?.graph;
  if (g && typeof g.getNodeById === "function") {
    try {
      const n = g.getNodeById(Number(nodeId));
      if (isNode(n)) return n;
    } catch (e) {}
  }
  if (Array.isArray(g?._nodes)) {
    const idStr = String(nodeId || "");
    const n = g._nodes.find((x) => isNode(x) && String(x.id) === idStr);
    if (n) return n;
    const all = g._nodes.filter((x) => isNode(x));
    if (all.length === 1) return all[0];
  }
  return null;
}
function creds(node) {
  return {
    login: String(findWidget(node, WIDGET_LOGIN)?.value || "").trim(),
    api_key: String(findWidget(node, WIDGET_API_KEY)?.value || "").trim(),
  };
}
function applyCreds(node, c) {
  const map = [[WIDGET_LOGIN, c.login], [WIDGET_API_KEY, c.api_key]];
  map.forEach(([k, v]) => {
    const w = findWidget(node, k);
    if (!w) return;
    w.value = String(v || "");
    if (typeof w.callback === "function") w.callback(w.value);
  });
  rebuild(node);
  dirty(node);
  saveLocalState({ login: String(c?.login || ""), api_key: String(c?.api_key || "") });
}
function setSelection(node, urls, singleUrl, nonce, tags, persist = true) {
  const w1 = findWidget(node, WIDGET_URLS);
  const w2 = findWidget(node, WIDGET_URL);
  const w3 = findWidget(node, WIDGET_NONCE);
  const w4 = findWidget(node, WIDGET_TAGS);
  const one = String(singleUrl || "").trim();
  if (w1) {
    w1.value = JSON.stringify(Array.isArray(urls) ? urls : []);
    if (typeof w1.callback === "function") w1.callback(w1.value);
  }
  if (w2) {
    w2.value = one;
    if (typeof w2.callback === "function") w2.callback(w2.value);
  }
  if (w3) {
    w3.value = String(nonce || Date.now());
    if (typeof w3.callback === "function") w3.callback(w3.value);
  }
  if (w4) {
    w4.value = String(tags || "");
    if (typeof w4.callback === "function") w4.callback(w4.value);
  }
  const st = node?.__fmiydDanbooruState?.statusEl;
  if (st) st.textContent = one ? ("已选中: " + one.slice(0, 120)) : "未选中图片";
  rebuild(node);
  dirty(node);
  if (persist) {
    saveLocalState({
      selected_urls: Array.isArray(urls) ? urls : [],
      selected_url: one,
      selection_nonce: String(nonce || Date.now()),
      selected_tags: String(tags || ""),
    });
  }
}
function pushCreds(node) {
  const iframe = node?.__fmiydDanbooruState?.iframeEl;
  if (!iframe?.contentWindow) return;
  iframe.contentWindow.postMessage({ type: "fmiyd_danbooru_creds", ...creds(node) }, "*");
}
function pushRestoreState(node) {
  const iframe = node?.__fmiydDanbooruState?.iframeEl;
  if (!iframe?.contentWindow) return;
  const s = loadLocalState();
  iframe.contentWindow.postMessage(
    {
      type: "fmiyd_danbooru_restore_state",
      gallery_state: s.gallery_state || {},
    },
    "*"
  );
}
function openModal(node) {
  const c = creds(node);
  const bg = document.createElement("div");
  bg.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;";
  const box = document.createElement("div");
  box.style.cssText = "background:#1e1e1e;border:1px solid #444;border-radius:10px;padding:16px 18px;max-width:520px;width:100%;color:#ddd;font-size:13px;";
  box.innerHTML = "<div style='font-weight:600;margin-bottom:8px;color:#9cf;'>D站账号（可选）</div>";
  function field(label, val, isPwd) {
    const l = document.createElement("label");
    l.textContent = label;
    l.style.cssText = "display:block;margin:8px 0 4px;color:#aaa;";
    box.appendChild(l);
    const el = document.createElement("input");
    el.type = isPwd ? "password" : "text";
    el.value = val || "";
    el.style.cssText = "width:100%;padding:8px;border-radius:6px;border:1px solid #555;background:#252525;color:#eee;box-sizing:border-box;font-size:12px;";
    box.appendChild(el);
    return el;
  }
  const inLogin = field("login", c.login, false);
  const inKey = field("api_key", c.api_key, true);
  const row = document.createElement("div");
  row.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:14px;";
  const cancel = document.createElement("button");
  cancel.className = "comfy-button";
  cancel.textContent = "取消";
  cancel.onclick = () => document.body.removeChild(bg);
  const save = document.createElement("button");
  save.className = "comfy-button";
  save.textContent = "保存并同步";
  save.onclick = () => {
    applyCreds(node, { login: inLogin.value.trim(), api_key: inKey.value.trim() });
    pushCreds(node);
    document.body.removeChild(bg);
  };
  row.appendChild(cancel);
  row.appendChild(save);
  box.appendChild(row);
  bg.appendChild(box);
  bg.onclick = (e) => { if (e.target === bg) document.body.removeChild(bg); };
  document.body.appendChild(bg);
}

window.addEventListener("message", (ev) => {
  if (!ev.data) return;
  if (ev.data.type === "fmiyd_danbooru_selection") {
    const node = findNode(String(ev.data.node_id || ""));
    if (!node) return;
    const urls = Array.isArray(ev.data.urls) ? ev.data.urls : [];
    const one = String(ev.data.url || urls[0] || "").trim();
    setSelection(node, one ? urls : [], one, ev.data.nonce, ev.data.tags || "");
    return;
  }
  if (ev.data.type === "fmiyd_danbooru_set_creds") {
    const node = findNode(String(ev.data.node_id || ""));
    if (!node) return;
    applyCreds(node, { login: String(ev.data.login || ""), api_key: String(ev.data.api_key || "") });
    pushCreds(node);
    return;
  }
  if (ev.data.type === "fmiyd_danbooru_state_sync") {
    const st = ev.data.state && typeof ev.data.state === "object" ? ev.data.state : {};
    saveLocalState({ gallery_state: st });
  }
});

app.registerExtension({
  name: "FMIYD.DanbooruGalleryEmbed",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      orig?.apply(this, arguments);
      const node = this;
      [WIDGET_URLS, WIDGET_URL, WIDGET_NONCE, WIDGET_TAGS, WIDGET_LOGIN, WIDGET_API_KEY].forEach((n) => hideWidget(findWidget(node, n)));
      setTimeout(() => [WIDGET_URLS, WIDGET_URL, WIDGET_NONCE, WIDGET_TAGS, WIDGET_LOGIN, WIDGET_API_KEY].forEach((n) => hideWidget(findWidget(node, n))), 0);
      setSelection(node, [], "", Date.now(), "", false);
      const persisted = loadLocalState();
      if (persisted && typeof persisted === "object") {
        const pUrls = Array.isArray(persisted.selected_urls) ? persisted.selected_urls : [];
        const pOne = String(persisted.selected_url || pUrls[0] || "").trim();
        const pNonce = String(persisted.selection_nonce || Date.now());
        const pTags = String(persisted.selected_tags || "");
        if (String(persisted.login || "").trim() || String(persisted.api_key || "").trim()) {
          applyCreds(node, { login: String(persisted.login || ""), api_key: String(persisted.api_key || "") });
        }
        if (pOne || pUrls.length || pTags) {
          setSelection(node, pOne ? pUrls : [], pOne, pNonce, pTags);
        }
      }
      node.setSize?.([780, 900]);

      const root = $el("div", { style: { width: "100%", height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", borderRadius: "6px" } });
      const st = $el("div", { textContent: "账号、黑名单等在画廊内「设置」中统一管理。", style: { fontSize: "11px", color: "#888", marginBottom: "6px", padding: "0 2px" } });
      root.appendChild(st);
      const wrap = $el("div", { style: { flex: "1 1 auto", minHeight: "200px", border: "1px solid #555", borderRadius: "6px", overflow: "hidden", backgroundColor: "#111" } });
      const iframe = document.createElement("iframe");
      iframe.src = `${GALLERY_PATH}?node_id=${encodeURIComponent(String(node.id))}&v=${encodeURIComponent(GALLERY_HTML_CACHE_TAG)}`;
      iframe.style.cssText = "width:100%;height:100%;border:0;";
      iframe.onload = () => {
        pushCreds(node);
        pushRestoreState(node);
      };
      wrap.appendChild(iframe);
      root.appendChild(wrap);
      node.__fmiydDanbooruState = { iframeEl: iframe, statusEl: st };
      node.addDOMWidget("fmiyd_danbooru_gallery_widget", "div", root, { onDraw: () => {} });
    };
  },
});
