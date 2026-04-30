import { app } from "/scripts/app.js";
import { $el } from "/scripts/ui.js";

const NODE_TYPE = "FMIYDPixivGallery";
const WIDGET_URLS = "selected_urls";
const WIDGET_URL = "selected_url";
const WIDGET_NONCE = "selection_nonce";
const WIDGET_RT = "pixiv_refresh_token";
const WIDGET_COOKIE = "pixiv_cookie";
const WIDGET_UID = "pixiv_user_id";
const GALLERY_PATH = "/fmiyd/pixiv_gallery";
const GALLERY_HTML_CACHE_TAG = "20260426c";

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
function dirty(node) {
  node.setDirtyCanvas?.(true);
  app.canvas?.setDirty?.(true, true);
  app.graph?.change?.();
}
function isPixivNode(node) {
  return !!(node && (node.type === NODE_TYPE || node.comfyClass === NODE_TYPE));
}
function findPixivNodeByIdOrFallback(nodeId) {
  const graph = app?.graph;
  if (graph) {
    if (typeof graph.getNodeById === "function") {
      try {
        const byNum = graph.getNodeById(Number(nodeId));
        if (isPixivNode(byNum)) return byNum;
      } catch (e) {}
      try {
        const byRaw = graph.getNodeById(nodeId);
        if (isPixivNode(byRaw)) return byRaw;
      } catch (e) {}
    }
    if (Array.isArray(graph._nodes)) {
      const idStr = String(nodeId || "");
      const byId = graph._nodes.find((n) => isPixivNode(n) && String(n.id) === idStr);
      if (byId) return byId;
    }
  }
  const canvas = app?.canvas;
  if (canvas?.selected_nodes) {
    const list = Array.isArray(canvas.selected_nodes) ? canvas.selected_nodes : Object.values(canvas.selected_nodes);
    const picked = list.find((n) => isPixivNode(n));
    if (picked) return picked;
  }
  if (Array.isArray(graph?._nodes)) {
    const all = graph._nodes.filter((n) => isPixivNode(n));
    if (all.length === 1) return all[0];
  }
  return null;
}
function creds(node) {
  return {
    refresh_token: String(findWidget(node, WIDGET_RT)?.value || "").trim(),
    cookie: String(findWidget(node, WIDGET_COOKIE)?.value || "").trim(),
    user_id: String(findWidget(node, WIDGET_UID)?.value || "").trim(),
  };
}
function applyCreds(node, c) {
  const m = [[WIDGET_RT, c.refresh_token], [WIDGET_COOKIE, c.cookie], [WIDGET_UID, c.user_id]];
  m.forEach(([k, v]) => {
    const w = findWidget(node, k);
    if (!w) return;
    w.value = String(v || "");
    if (typeof w.callback === "function") w.callback(w.value);
  });
  rebuild(node);
  dirty(node);
}
function pushCreds(node) {
  const iframe = node?.__fmiydPixivState?.iframeEl;
  if (!iframe?.contentWindow) return;
  iframe.contentWindow.postMessage({ type: "fmiyd_pixiv_creds", ...creds(node) }, "*");
}
function setSelectedUrls(node, urls, singleUrl, nonce) {
  const w = findWidget(node, WIDGET_URLS);
  const ws = findWidget(node, WIDGET_URL);
  const wn = findWidget(node, WIDGET_NONCE);
  const val = JSON.stringify(Array.isArray(urls) ? urls : []);
  const one = String(singleUrl || (Array.isArray(urls) && urls[0] ? urls[0] : "")).trim();
  if (w) {
    w.value = val;
    if (typeof w.callback === "function") w.callback(w.value);
  }
  if (ws) {
    ws.value = one;
    if (typeof ws.callback === "function") ws.callback(ws.value);
  }
  if (wn) {
    wn.value = String(nonce || Date.now());
    if (typeof wn.callback === "function") wn.callback(wn.value);
  }
  const st = node?.__fmiydPixivState?.statusEl;
  if (st) {
    const u = one || "";
    st.textContent = u ? ("已选中: " + u.slice(0, 120)) : "未选中图片";
  }
  rebuild(node);
  dirty(node);
}

function openModal(node) {
  const c = creds(node);
  const bg = document.createElement("div");
  bg.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;";
  const box = document.createElement("div");
  box.style.cssText = "background:#1e1e1e;border:1px solid #444;border-radius:10px;padding:16px 18px;max-width:520px;width:100%;color:#ddd;font-size:13px;";
  box.innerHTML = "<div style='font-weight:600;margin-bottom:8px;color:#9cf;'>登录 Pixiv（refresh_token / cookie）</div>";
  function field(label, val, rows) {
    const l = document.createElement("label");
    l.textContent = label;
    l.style.cssText = "display:block;margin:8px 0 4px;color:#aaa;";
    box.appendChild(l);
    let el;
    if (rows > 1) { el = document.createElement("textarea"); el.rows = rows; }
    else { el = document.createElement("input"); el.type = "text"; }
    el.value = val || "";
    el.style.cssText = "width:100%;padding:8px;border-radius:6px;border:1px solid #555;background:#252525;color:#eee;box-sizing:border-box;font-size:11px;";
    box.appendChild(el);
    return el;
  }
  const rt = field("refresh_token（可留空）", c.refresh_token, 3);
  const ck = field("cookie（可只填 PHPSESSID）", c.cookie || "PHPSESSID=...", 3);
  const uid = field("user_id（Cookie 模式建议填）", c.user_id, 1);

  const row = document.createElement("div");
  row.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:14px;";
  const cancel = document.createElement("button");
  cancel.className = "comfy-button";
  cancel.textContent = "取消";
  cancel.onclick = () => document.body.removeChild(bg);
  const save = document.createElement("button");
  save.className = "comfy-button";
  save.textContent = "保存并同步到画廊";
  save.onclick = () => {
    applyCreds(node, { refresh_token: rt.value.trim(), cookie: ck.value.trim(), user_id: uid.value.trim() });
    pushCreds(node);
    document.body.removeChild(bg);
  };
  row.appendChild(cancel); row.appendChild(save);
  box.appendChild(row);
  bg.appendChild(box);
  bg.onclick = (e) => { if (e.target === bg) document.body.removeChild(bg); };
  document.body.appendChild(bg);
}

window.addEventListener("message", (ev) => {
  if (!ev.data || ev.data.type !== "fmiyd_pixiv_selection") return;
  const nodeId = String(ev.data.node_id || "");
  const node = findPixivNodeByIdOrFallback(nodeId);
  if (!node) return;
  const urls = Array.isArray(ev.data.urls) ? ev.data.urls : [];
  const singleUrl = String(ev.data.url || urls[0] || "").trim();
  setSelectedUrls(node, singleUrl ? [singleUrl] : [], singleUrl, ev.data.nonce);
});

app.registerExtension({
  name: "FMIYD.PixivGalleryEmbed",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      orig?.apply(this, arguments);
      const node = this;
      [WIDGET_URLS, WIDGET_URL, WIDGET_NONCE, WIDGET_RT, WIDGET_COOKIE, WIDGET_UID].forEach((n) => hideWidget(findWidget(node, n)));
      setTimeout(() => [WIDGET_URLS, WIDGET_URL, WIDGET_NONCE, WIDGET_RT, WIDGET_COOKIE, WIDGET_UID].forEach((n) => hideWidget(findWidget(node, n))), 0);
      // 打开工作流时先清空旧选择，避免首次运行误用历史 URL。
      setSelectedUrls(node, [], "", Date.now());
      node.setSize?.([780, 900]);

      const root = $el("div", { style: { width: "100%", height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", borderRadius: "6px" } });
      const row = $el("div", { style: { display: "flex", gap: "8px", marginBottom: "4px" } });
      const b1 = $el("button", { className: "comfy-button", textContent: "Pixiv 账号", onclick: () => openModal(node) });
      const b2 = $el("button", { className: "comfy-button", textContent: "同步账号到画廊", onclick: () => pushCreds(node) });
      row.appendChild(b1); row.appendChild(b2); root.appendChild(row);
      const st = $el("div", { textContent: "填写凭据后点「同步」。", style: { fontSize: "11px", color: "#888", marginBottom: "6px", padding: "0 2px" } });
      root.appendChild(st);
      const wrap = $el("div", { style: { flex: "1 1 auto", minHeight: "200px", border: "1px solid #555", borderRadius: "6px", overflow: "hidden", backgroundColor: "#111" } });
      const iframe = document.createElement("iframe");
      iframe.src = `${GALLERY_PATH}?node_id=${encodeURIComponent(String(node.id))}&v=${encodeURIComponent(GALLERY_HTML_CACHE_TAG)}`;
      iframe.style.cssText = "width:100%;height:100%;border:0;";
      iframe.onload = () => pushCreds(node);
      wrap.appendChild(iframe);
      root.appendChild(wrap);
      node.__fmiydPixivState = { iframeEl: iframe, statusEl: st };
      node.addDOMWidget("fmiyd_pixiv_gallery_widget", "div", root, { onDraw: () => {} });
    };
  },
});
