/**
 * FMIYD 画师图鉴画廊节点
 * 将画师作品以内嵌画廊展示，点击图片后通过 postMessage 回填节点的 prompt（存放画师tag）。
 */
import { app } from "/scripts/app.js";
import { $el } from "/scripts/ui.js";

/** 旧版曾把 D 站账号写入 localStorage；现已改为仅节点参数。启动时清除残留，避免误用他人/历史凭据。 */
try {
    localStorage.removeItem("fmiyd_danbooru_account");
} catch (e) {}

const NODE_TYPE_ARTIST = "FMIYDArtistGallery";
const PROMPT_WIDGET_NAME = "prompt";
const GALLERY_PATH = "/fmiyd/artist_gallery";

/** ComfyUI 新版前端的 Toast（节点内提示）；不可用时返回 false */
function fmiydShowAppToast({ severity = "info", summary = "画师图鉴", detail = "", life = 3800 } = {}) {
    try {
        const toast = app?.extensionManager?.toast;
        if (toast && typeof toast.add === "function") {
            toast.add({
                severity,
                summary,
                detail: detail || "",
                life,
            });
            return true;
        }
    } catch (e) {}
    return false;
}

/** Danbooru 凭据（与 nodes.py 一致；仅保存在节点参数中，由「D站账号」弹窗编辑） */
const DANBOORU_ACCOUNT_KEYS = ["danbooru_login", "danbooru_api_key"];

/** 仅当「随机画师串开启」时由后端使用 */
const RANDOM_TAG_COUNT_KEY = "random_tag_count";
/** 仅当「随机权值开启」时由后端使用 */
const WEIGHT_SETTING_KEYS = [
    "weight_min",
    "weight_max",
    "weight_step",
    "weight_threshold",
    "min_tags_above_threshold",
    "max_tags_above_threshold",
];
/** 弹窗可编辑并隐藏的参数（与 nodes.py 一致） */
const GALLERY_SETTING_KEYS = [RANDOM_TAG_COUNT_KEY, ...WEIGHT_SETTING_KEYS];
/**
 * 与 nodes.py INPUT_TYPES 中各字段 default 一致：仅在新节点「首次放置」时作为初始值。
 * 用户修改并保存工作流后，始终以节点内已保存的值为准，不再自动恢复为下述数字。
 */
const GALLERY_INITIAL_VALUES = {
    [RANDOM_TAG_COUNT_KEY]: 4,
    weight_min: 0.05,
    weight_max: 1.0,
    weight_step: 0.05,
    weight_threshold: 0.8,
    min_tags_above_threshold: 1,
    max_tags_above_threshold: 3,
};
/** 与 nodes.py FLOAT 项一致；用于序列化前四舍五入，减少 JSON 浮点漂移 */
const GALLERY_FLOAT_KEYS = ["weight_min", "weight_max", "weight_step", "weight_threshold"];

function getDanbooruAccountFromNode(node) {
    const out = {};
    for (const k of DANBOORU_ACCOUNT_KEYS) {
        const w = findWidget(node, k);
        if (w) out[k] = w.value;
    }
    return out;
}

function applyDanbooruAccountToNode(node, data) {
    if (!data || !node?.widgets) return;
    for (const k of DANBOORU_ACCOUNT_KEYS) {
        if (data[k] === undefined || data[k] === null) continue;
        const w = findWidget(node, k);
        if (!w) continue;
        w.value = String(data[k]);
    }
    for (const k of DANBOORU_ACCOUNT_KEYS) {
        const w = findWidget(node, k);
        if (w && typeof w.callback === "function") w.callback(w.value);
    }
    rebuildWidgetsValuesFromWidgets(node);
    markNodeAndGraphDirty(node);
}

/** 父页取消某一 idx 后，同步 iframe 内画廊的选中态（与在画廊里第二次点卡片取消选中一致） */
function pushRemoveSelectionIdxToIframe(node, idx) {
    const iframe = node?.__fmiydArtistState?.iframeEl;
    if (!iframe?.contentWindow) return;
    const payload = {
        type: "fmiyd_remove_selection_idx",
        node_id: String(node.id),
        idx: Number(idx),
    };
    /** 下一帧再发，确保 iframe 文档已就绪（部分 Comfy 嵌入下更稳） */
    requestAnimationFrame(() => {
        try {
            iframe.contentWindow.postMessage(payload, "*");
        } catch (e) {}
    });
}

/** 将节点上的 D 站账号同步到内嵌画廊 iframe（用于在线缩略图 API，不经 localStorage） */
function pushDanbooruCredsToIframe(node) {
    const iframe = node?.__fmiydArtistState?.iframeEl;
    if (!iframe?.contentWindow) return;
    const acc = getDanbooruAccountFromNode(node);
    iframe.contentWindow.postMessage(
        {
            type: "fmiyd_danbooru_creds",
            login: String(acc.danbooru_login ?? "").trim(),
            api_key: String(acc.danbooru_api_key ?? "").trim(),
        },
        "*"
    );
}

function findWidget(node, name) {
    if (!node) return null;
    if (Array.isArray(node.widgets)) {
        const w = node.widgets.find((x) => x && x.name === name);
        if (w) return w;
    }
    if (Array.isArray(node.inputs)) {
        for (const inp of node.inputs) {
            if (inp && inp.name === name && inp.widget) return inp.widget;
        }
    }
    return null;
}

/**
 * 按 node.widgets 顺序整表重建 widgets_values，避免 Comfy / LiteGraph 下标与序列化数组短暂不一致
 * （表现为仅个别 FLOAT 如 weight_max、weight_threshold 保存后恢复默认）。
 */
function rebuildWidgetsValuesFromWidgets(node) {
    if (!Array.isArray(node?.widgets)) return;
    if (!Array.isArray(node.widgets_values)) {
        node.widgets_values = [];
    }
    for (let i = 0; i < node.widgets.length; i++) {
        const w = node.widgets[i];
        if (w && Object.prototype.hasOwnProperty.call(w, "value")) {
            node.widgets_values[i] = w.value;
        }
    }
}

function syncWidgetValueToGraph(node, w, v) {
    if (!w || !node) return;
    w.value = v;
    if (typeof w.callback === "function") w.callback(v);
    rebuildWidgetsValuesFromWidgets(node);
}

function markNodeAndGraphDirty(node) {
    try {
        node.setDirtyCanvas?.(true);
        if (app?.canvas?.setDirty) app.canvas.setDirty(true, true);
    } catch (e) {}
    if (app.graph) app.graph.change();
}

/** 不在节点上展示该控件（值仍参与执行；由「画师串 / 权值随机设置」弹窗编辑） */
function hideNodeWidget(w) {
    if (!w) return;
    w.computeSize = () => [0, -4];
    w.draw = () => {};
    w.type = "hidden";
    try {
        Object.defineProperty(w, "hidden", { value: true, writable: false });
    } catch (e) {}
}

function hideGallerySettingsWidgets(node) {
    if (!Array.isArray(node?.widgets)) return;
    for (const name of GALLERY_SETTING_KEYS) {
        hideNodeWidget(findWidget(node, name));
    }
    for (const name of DANBOORU_ACCOUNT_KEYS) {
        hideNodeWidget(findWidget(node, name));
    }
}

function getGallerySettingsFromNode(node) {
    const out = {};
    for (const k of GALLERY_SETTING_KEYS) {
        const w = findWidget(node, k);
        if (w) out[k] = w.value;
    }
    return out;
}

/** 弹窗展示用：优先节点当前已保存值；仅当读不到有效数字时才用 GALLERY_INITIAL_VALUES */
function getGallerySettingsForModal(node) {
    const fromNode = getGallerySettingsFromNode(node);
    const cur = {};
    for (const k of GALLERY_SETTING_KEYS) {
        const raw = fromNode[k];
        const num = Number(raw);
        if (raw !== undefined && raw !== null && Number.isFinite(num)) {
            cur[k] =
                k === RANDOM_TAG_COUNT_KEY || k === "min_tags_above_threshold" || k === "max_tags_above_threshold"
                    ? Math.round(num)
                    : num;
        } else {
            cur[k] = GALLERY_INITIAL_VALUES[k];
        }
    }
    return cur;
}

function applyGallerySettingsToNode(node, data) {
    if (!data || !node?.widgets) return;
    for (const k of GALLERY_SETTING_KEYS) {
        if (data[k] === undefined || data[k] === null) continue;
        const w = findWidget(node, k);
        if (!w) continue;
        let v = Number(data[k]);
        if (!Number.isFinite(v)) continue;
        if (k === RANDOM_TAG_COUNT_KEY || k === "min_tags_above_threshold" || k === "max_tags_above_threshold") {
            v = Math.round(v);
        } else if (GALLERY_FLOAT_KEYS.includes(k)) {
            v = Math.round(v * 10000) / 10000;
        }
        w.value = v;
    }
    for (const k of GALLERY_SETTING_KEYS) {
        const w = findWidget(node, k);
        if (w && typeof w.callback === "function") w.callback(w.value);
    }
    rebuildWidgetsValuesFromWidgets(node);
    markNodeAndGraphDirty(node);
}

function openGallerySettingsModal(node) {
    /** 只读当前节点已持久化的参数；改动保存后随工作流保留，不会自动回到初始值 */
    const cur = getGallerySettingsForModal(node);

    const useRandArtist = !!findWidget(node, "use_random_artist_prompt")?.value;
    const useRandWeight = !!findWidget(node, "use_random_weight")?.value;

    const backdrop = document.createElement("div");
    backdrop.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;";

    const box = document.createElement("div");
    box.style.cssText =
        "background:#1e1e1e;border:1px solid #444;border-radius:10px;padding:16px 18px;max-width:420px;width:100%;color:#ddd;font-family:system-ui,sans-serif;font-size:13px;box-shadow:0 8px 32px rgba(0,0,0,.5);";

    const title = document.createElement("div");
    title.textContent = "画师串与权值随机（执行图时生效）";
    title.style.cssText = "font-weight:600;margin-bottom:4px;color:#b8d4ff;";
    box.appendChild(title);

    const hint = document.createElement("div");
    hint.innerHTML =
        "「随机画师串」与「随机权值」<b>相互独立</b>，各自由节点上两个开关控制。<br/>" +
        "• 画师串长度：仅当<b>随机画师串开启</b>时参与出图。<br/>" +
        "• 权值相关项：仅当<b>随机权值开启</b>时参与出图。<br/>" +
        "下方数字为<strong>当前节点已保存</strong>的值；新节点首次与 Comfy 侧<strong>初始值</strong>一致。<b>保存工作流后</b>会一直保持你改过的值，不会自动恢复。";
    hint.style.cssText = "font-size:11px;color:#888;line-height:1.45;margin-bottom:14px;";
    box.appendChild(hint);

    const rows = [
        { key: RANDOM_TAG_COUNT_KEY, label: "随机画师串长度（tag 个数）", step: "1", min: "1", max: "50" },
        /** 与 nodes.py FLOAT max=5 一致；权值可写 1.2、2 等强调写法 */
        { key: "weight_min", label: "权值下限", step: "0.01", min: "0", max: "5" },
        { key: "weight_max", label: "权值上限", step: "0.01", min: "0", max: "5" },
        { key: "weight_step", label: "步长（点间隔）", step: "0.01", min: "0.01", max: "0.5" },
        { key: "weight_threshold", label: "高权阈值（高于此值）", step: "0.01", min: "0", max: "5" },
        { key: "min_tags_above_threshold", label: "高权 tag 至少几个", step: "1", min: "0", max: "50" },
        { key: "max_tags_above_threshold", label: "高权 tag 至多几个", step: "1", min: "0", max: "50" },
    ];

    const inputs = {};
    rows.forEach((r) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;";
        const lab = document.createElement("label");
        lab.textContent = r.label;
        lab.style.flex = "1";
        lab.style.minWidth = "0";
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = r.step;
        inp.min = r.min;
        inp.max = r.max;
        inp.value = cur[r.key] != null ? String(cur[r.key]) : "";
        inp.style.cssText =
            "width:110px;padding:6px 8px;border-radius:6px;border:1px solid #555;background:#252525;color:#eee;";
        if (r.key === RANDOM_TAG_COUNT_KEY) {
            if (!useRandArtist) {
                inp.style.opacity = "0.6";
                inp.title = "「随机画师串」关闭时此项不参与出图，可先改好再保存为预设";
            }
        } else if (WEIGHT_SETTING_KEYS.indexOf(r.key) >= 0) {
            if (!useRandWeight) {
                inp.style.opacity = "0.6";
                inp.title = "「随机权值」关闭时此项不参与出图，可先改好再保存为预设";
            }
        }
        inputs[r.key] = inp;
        row.appendChild(lab);
        row.appendChild(inp);
        box.appendChild(row);
    });

    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:16px;";

    const btnCancel = document.createElement("button");
    btnCancel.textContent = "取消";
    btnCancel.style.cssText = "padding:8px 14px;border-radius:6px;border:1px solid #555;background:#333;color:#ccc;cursor:pointer;";
    btnCancel.onclick = () => document.body.removeChild(backdrop);

    const btnSave = document.createElement("button");
    btnSave.textContent = "保存";
    btnSave.style.cssText = "padding:8px 14px;border-radius:6px;border:1px solid #3a6ea5;background:#2d4a6f;color:#fff;cursor:pointer;";
    btnSave.onclick = () => {
        const data = {};
        for (const r of rows) {
            const v = Number(inputs[r.key].value);
            if (!isFinite(v)) {
                alert("请填写有效数字：" + r.label);
                return;
            }
            data[r.key] = v;
        }
        if (data.random_tag_count < 1 || data.random_tag_count > 50) {
            alert("随机画师串长度应在 1～50");
            return;
        }
        if (data.min_tags_above_threshold > data.max_tags_above_threshold) {
            alert("「高权至少」不能大于「高权至多」");
            return;
        }
        applyGallerySettingsToNode(node, data);
        document.body.removeChild(backdrop);
    };

    btnRow.appendChild(btnCancel);
    btnRow.appendChild(btnSave);
    box.appendChild(btnRow);

    backdrop.appendChild(box);
    backdrop.onclick = (ev) => {
        if (ev.target === backdrop) document.body.removeChild(backdrop);
    };
    document.body.appendChild(backdrop);
}

function openDanbooruAccountModal(node) {
    const cur = { ...getDanbooruAccountFromNode(node) };

    const backdrop = document.createElement("div");
    backdrop.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;";

    const box = document.createElement("div");
    box.style.cssText =
        "background:#1e1e1e;border:1px solid #444;border-radius:10px;padding:16px 18px;max-width:420px;width:100%;color:#ddd;font-family:system-ui,sans-serif;font-size:13px;box-shadow:0 8px 32px rgba(0,0,0,.5);";

    const title = document.createElement("div");
    title.textContent = "Danbooru（D站）账号";
    title.style.cssText = "font-weight:600;margin-bottom:4px;color:#b8d4ff;";
    box.appendChild(title);

    const hint = document.createElement("div");
    hint.innerHTML =
        "写入当前节点隐藏参数 <code>danbooru_login</code> / <code>danbooru_api_key</code>（可选）。服务端<strong>优先匿名</strong>访问 D 站；若遇 <b>403/限流</b>且此处已填写，会自动用账号重试。<b>请勿分享</b>含 API Key 的工作流。";
    hint.style.cssText = "font-size:11px;color:#888;line-height:1.45;margin-bottom:14px;";
    box.appendChild(hint);

    function addField(label, key, password) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;flex-direction:column;gap:6px;margin-bottom:12px;";
        const lab = document.createElement("label");
        lab.textContent = label;
        lab.style.color = "#aaa";
        const inp = document.createElement("input");
        inp.type = password ? "password" : "text";
        inp.autocomplete = "off";
        inp.spellcheck = false;
        inp.value = cur[key] != null ? String(cur[key]) : "";
        inp.style.cssText =
            "width:100%;padding:8px;border-radius:6px;border:1px solid #555;background:#252525;color:#eee;box-sizing:border-box;";
        row.appendChild(lab);
        row.appendChild(inp);
        box.appendChild(row);
        return inp;
    }

    const inLogin = addField("登录名（login）", "danbooru_login", false);
    const inKey = addField("API Key", "danbooru_api_key", true);

    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:16px;";

    const btnCancel = document.createElement("button");
    btnCancel.textContent = "取消";
    btnCancel.style.cssText =
        "padding:8px 14px;border-radius:6px;border:1px solid #555;background:#333;color:#ccc;cursor:pointer;";
    btnCancel.onclick = () => document.body.removeChild(backdrop);

    const btnSave = document.createElement("button");
    btnSave.textContent = "保存";
    btnSave.style.cssText =
        "padding:8px 14px;border-radius:6px;border:1px solid #3a6ea5;background:#2d4a6f;color:#fff;cursor:pointer;";
    btnSave.onclick = () => {
        const data = {
            danbooru_login: inLogin.value.trim(),
            danbooru_api_key: inKey.value.trim(),
        };
        applyDanbooruAccountToNode(node, data);
        pushDanbooruCredsToIframe(node);
        document.body.removeChild(backdrop);
    };

    btnRow.appendChild(btnCancel);
    btnRow.appendChild(btnSave);
    box.appendChild(btnRow);

    backdrop.appendChild(box);
    backdrop.onclick = (ev) => {
        if (ev.target === backdrop) document.body.removeChild(backdrop);
    };
    document.body.appendChild(backdrop);
}

function findNodeById(graph, nodeId) {
    if (!graph || nodeId == null) return null;
    const idStr = String(nodeId);
    if (typeof graph.getNodeById === "function") {
        try {
            return graph.getNodeById(Number(nodeId)) || graph.getNodeById(nodeId);
        } catch (e) {}
    }
    if (graph._nodes) {
        return graph._nodes.find((n) => n && String(n.id) === idStr);
    }
    return null;
}

function formatWeightedTag(tag, weight) {
    const w = Number(weight);
    if (!tag) return "";
    if (!isFinite(w) || w === 1) return tag;
    if (w <= 0) return "";
    // ComfyUI 通常支持 (tag:weight) 的加权写法
    return "(" + tag + ":" + w + ")";
}

function updatePromptWidget(node, promptValue) {
    if (!node?.widgets) return;
    const w = node.widgets.find((wi) => wi && wi.name === PROMPT_WIDGET_NAME);
    if (!w) return;
    w.value = String(promptValue || "");
    if (typeof w.callback === "function") w.callback(w.value);
    if (app.graph) app.graph.change();
}

function renderHeader(node) {
    const state = node.__fmiydArtistState;
    if (!state || !state.headerEl) return;

    const selected = state.selected || [];
    const root = state.headerEl;
    root.innerHTML = "";

    const title = document.createElement("div");
    title.style.color = "#b8d4ff";
    title.style.fontSize = "12px";
    title.style.marginBottom = "6px";
    title.textContent = "已选画师（可调权重）：" + selected.length;
    root.appendChild(title);

    if (!selected.length) {
        const empty = document.createElement("div");
        empty.style.color = "#777";
        empty.style.fontSize = "12px";
        empty.textContent = "未选择画师（在主页点卡片或详情页点击图片）";
        root.appendChild(empty);
        updatePromptWidget(node, "");
        return;
    }

    // 用“小标签/Chip”展示，允许同一行显示多个，并节省垂直空间
    const chips = document.createElement("div");
    chips.style.display = "flex";
    chips.style.flexWrap = "wrap";
    chips.style.gap = "6px 8px";
    chips.style.alignItems = "flex-start";

    // 重建加权输出
    const parts = [];

    selected.forEach((item) => {
        const chip = document.createElement("div");
        chip.style.display = "flex";
        chip.style.alignItems = "center";
        chip.style.gap = "6px";
        chip.style.padding = "6px 8px";
        chip.style.border = "1px solid #333";
        chip.style.borderRadius = "999px";
        chip.style.background = "rgba(0,0,0,0.15)";
        chip.style.maxWidth = "100%";

        const tagText = document.createElement("div");
        tagText.style.color = "#9aa";
        tagText.style.fontSize = "11px";
        tagText.style.maxWidth = "240px";
        tagText.style.overflow = "hidden";
        tagText.style.textOverflow = "ellipsis";
        tagText.style.whiteSpace = "nowrap";
        tagText.textContent = item.tag ? item.tag : ("画师#" + (item.idx + 1));
        chip.title = (item.name ? item.name + "\\n" : "") + (item.tag || "");
        chip.appendChild(tagText);

        const input = document.createElement("input");
        input.type = "number";
        input.step = "0.05";
        input.min = "0";
        input.value = String(item.weight);
        input.style.width = "72px";
        input.style.padding = "4px 6px";
        input.style.borderRadius = "6px";
        input.style.background = "#252525";
        input.style.border = "1px solid #444";
        input.style.color = "#eee";
        input.style.fontSize = "11px";

        input.onchange = function () {
            const newW = Number(input.value);
            const idx = state.selected.findIndex((x) => x.idx === item.idx);
            if (idx >= 0 && isFinite(newW)) {
                state.selected[idx].weight = newW;
            }
            renderHeader(node);
        };

        chip.appendChild(input);

        const btnRemove = document.createElement("button");
        btnRemove.type = "button";
        btnRemove.setAttribute("aria-label", "取消选中该画师");
        btnRemove.title = "取消选中";
        btnRemove.textContent = "×";
        btnRemove.style.cssText =
            "flex:0 0 auto;margin:0;padding:0 2px;min-width:20px;height:20px;line-height:18px;border:none;border-radius:4px;background:transparent;color:#e55;cursor:pointer;font-size:16px;font-weight:700;";
        btnRemove.onmouseenter = () => {
            btnRemove.style.background = "rgba(255,80,80,0.2)";
            btnRemove.style.color = "#f88";
        };
        btnRemove.onmouseleave = () => {
            btnRemove.style.background = "transparent";
            btnRemove.style.color = "#e55";
        };
        btnRemove.onclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            /** 不在此改 state：由 iframe 删 selected 后 postSelection，父页 applySelectionToNode 再刷新，避免与画廊 Set 不同步 */
            pushRemoveSelectionIdxToIframe(node, item.idx);
        };

        chip.appendChild(btnRemove);
        chips.appendChild(chip);

        const weighted = formatWeightedTag(item.tag, item.weight);
        if (weighted) parts.push(weighted);
    });

    root.appendChild(chips);

    const recipeRow = document.createElement("div");
    recipeRow.style.cssText = "margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;";
    const recipeBtn = document.createElement("button");
    recipeBtn.type = "button";
    recipeBtn.textContent = "收藏当前画师串为配方";
    recipeBtn.title = "把当前头部展示的画师串（含权重）保存到画廊「我的收藏 → 配方」";
    recipeBtn.style.cssText =
        "padding:4px 10px;font-size:11px;border-radius:6px;border:1px solid #555;background:#2a2a2a;color:#cce;cursor:pointer;";
    recipeBtn.onclick = () => {
        const w = findWidget(node, PROMPT_WIDGET_NAME);
        const v = w ? String(w.value || "").trim() : "";
        pushRecipeFavoriteToIframe(node, v);
    };
    recipeRow.appendChild(recipeBtn);
    root.appendChild(recipeRow);

    const promptValue = parts.join(", ");
    updatePromptWidget(node, promptValue);
}

/** 画师串写入 iframe 本地历史（仅队列执行时节点实际输出） */
function pushRecipeHistoryToIframe(node, text) {
    const iframe = node?.__fmiydArtistState?.iframeEl;
    if (!iframe?.contentWindow) return;
    const t = String(text || "").trim();
    if (!t) return;
    try {
        iframe.contentWindow.postMessage(
            {
                type: "fmiyd_append_recipe_history",
                text: t,
                source: "execute",
            },
            "*"
        );
    } catch (e) {}
}

function pushRecipeFavoriteToIframe(node, text) {
    const iframe = node?.__fmiydArtistState?.iframeEl;
    if (!iframe?.contentWindow) return;
    const t = String(text || "").trim();
    if (!t) {
        if (
            !fmiydShowAppToast({
                severity: "warn",
                summary: "无法收藏",
                detail: "当前画师串为空，请先在画廊中选择画师。",
                life: 4200,
            })
        ) {
            alert("当前画师串为空，无法收藏为配方");
        }
        return;
    }
    try {
        iframe.contentWindow.postMessage(
            {
                type: "fmiyd_add_recipe_favorite",
                text: t,
            },
            "*"
        );
    } catch (e) {}
}

function applySelectionToNode(node, selectedArr) {
    if (!node) return;
    if (!node.__fmiydArtistState) node.__fmiydArtistState = { selected: [], headerEl: null };

    const state = node.__fmiydArtistState;

    const prevMap = {};
    (state.selected || []).forEach((x) => {
        prevMap[Number(x.idx)] = x.weight;
    });

    const selected = (selectedArr || []).map((x) => {
        const idx = Number(x.idx);
        const incomingW = Number(x.weight);
        const hasIncoming = x.weight !== undefined && x.weight !== null && Number.isFinite(incomingW);
        return {
            idx,
            name: x.name || "",
            tag: x.tag || "",
            weight: hasIncoming ? incomingW : Object.prototype.hasOwnProperty.call(prevMap, idx) ? prevMap[idx] : 1
        };
    });

    state.selected = selected;
    renderHeader(node);
}

function isArtistGalleryNode(node) {
    return !!(node && (node.type === NODE_TYPE_ARTIST || node.comfyClass === NODE_TYPE_ARTIST));
}

/**
 * 仅从「画师图鉴画廊」节点在队列中执行完成时的 output 取画师串写入历史。
 * 必须校验节点类型：executed 会对图中每个节点触发，不能把别的节点的 STRING 输出误记进历史。
 */
function pushExecuteRecipeHistoryIfArtistNode(nodeId, output) {
    const graph = app?.graph;
    const node = findNodeById(graph, nodeId);
    if (!isArtistGalleryNode(node)) return;
    if (!output || typeof output !== "object") return;

    let raw = output.prompt;
    if (raw === undefined) raw = output.PROMPT;
    let str = Array.isArray(raw) ? raw[0] : raw;
    let text = String(str ?? "").trim();

    if (!text) {
        for (const v of Object.values(output)) {
            if (Array.isArray(v) && v.length && typeof v[0] === "string") {
                const t = String(v[0]).trim();
                if (t) {
                    text = t;
                    break;
                }
            }
        }
    }

    const t = String(text || "").trim();
    if (!t) return;
    pushRecipeHistoryToIframe(node, t);
}

window.addEventListener("message", (ev) => {
    if (!ev.data) return;
    if (ev.data.type === "fmiyd_toast") {
        const ok = fmiydShowAppToast({
            severity: ev.data.severity,
            summary: ev.data.summary,
            detail: ev.data.detail,
            life: ev.data.life,
        });
        if (!ok && ev.data.detail) {
            try {
                console.info("[FMIYD]", ev.data.summary || "", ev.data.detail);
            } catch (e) {}
        }
        return;
    }
    if (ev.data.type !== "fmiyd_artist_selection") return;

    const graph = app?.graph;
    let node = findNodeById(graph, ev.data.node_id);
    if (!node) {
        // 兜底：当 node_id 不稳定（例如 -1）时，优先用当前选中的节点
        const canvas = app?.canvas;
        if (canvas && canvas.selected_nodes) {
            const list = Array.isArray(canvas.selected_nodes)
                ? canvas.selected_nodes
                : Object.values(canvas.selected_nodes);
            node = list.find((n) => n && n.widgets && (n.type === NODE_TYPE_ARTIST || n.comfyClass === NODE_TYPE_ARTIST));
        }
        if (!node && graph?._nodes) {
            node = graph._nodes.find((n) => n && n.widgets && (n.type === NODE_TYPE_ARTIST || n.comfyClass === NODE_TYPE_ARTIST));
        }
    }
    if (!node) return;
    applySelectionToNode(node, ev.data.selected);
});

app.registerExtension({
    name: "FMIYD.ArtistGalleryEmbed",
    setup() {
        const api = app.api;
        if (!api || typeof api.addEventListener !== "function") return;
        api.addEventListener("executed", (e) => {
            try {
                const d = e.detail;
                if (!d) return;
                const nodeId = d.node ?? d.display_node ?? d.node_id;
                pushExecuteRecipeHistoryIfArtistNode(nodeId, d.output);
            } catch (err) {}
        });
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE_ARTIST) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const node = this;
            node.__fmiydArtistState = node.__fmiydArtistState || { selected: [] };

            // 隐藏 prompt；隐藏已在「画师串 / 权值随机设置」里提供的数值项，避免与弹窗重复展示
            if (Array.isArray(node.widgets)) {
                const promptWidget = node.widgets.find((w) => w && w.name === PROMPT_WIDGET_NAME);
                if (promptWidget) {
                    promptWidget.computeSize = () => [0, -4];
                    promptWidget.draw = () => {};
                    promptWidget.type = "hidden";
                    try {
                        Object.defineProperty(promptWidget, "hidden", { value: true, writable: false });
                    } catch (e) {}
                }
            }
            hideGallerySettingsWidgets(node);
            setTimeout(() => hideGallerySettingsWidgets(node), 0);
            setTimeout(() => hideGallerySettingsWidgets(node), 80);

            // 让节点高度自适应：用 flex 布局让 iframe 填满剩余空间
            if (typeof node.setSize === "function") node.setSize([820, 980]);
            if (Array.isArray(node.size)) node.size = node.size || [820, 980];

            const root = $el("div.fmiyd-artist-gallery-root", {
                style: {
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                    borderRadius: "6px",
                },
            });

            const toolRow = $el("div", {
                style: {
                    flex: "0 0 auto",
                    display: "flex",
                    gap: "8px",
                    alignItems: "center",
                    marginBottom: "4px",
                },
            });
            const setBtn = document.createElement("button");
            setBtn.textContent = "画师串 / 权值随机设置";
            setBtn.title =
                "配置随机画师串长度、权值区间/步长/阈值与高权 tag 个数（保存到当前节点与工作流）";
            setBtn.style.cssText =
                "padding:6px 12px;font-size:12px;border-radius:6px;border:1px solid #555;background:#2a2a2a;color:#cce;cursor:pointer;";
            setBtn.onclick = () => openGallerySettingsModal(node);
            toolRow.appendChild(setBtn);

            const dBtn = document.createElement("button");
            dBtn.textContent = "D站账号";
            dBtn.title = "可选：遇 403/限流时再填。优先匿名请求；仅保存在当前节点参数中";
            dBtn.style.cssText =
                "padding:6px 12px;font-size:12px;border-radius:6px;border:1px solid #555;background:#2a2a2a;color:#cce;cursor:pointer;";
            dBtn.onclick = () => openDanbooruAccountModal(node);
            toolRow.appendChild(dBtn);

            root.appendChild(toolRow);

            const header = $el("div.fmiyd-artist-gallery-header", {
                style: {
                    flex: "0 0 auto",
                    padding: "8px",
                    border: "1px solid #333",
                    background: "rgba(0,0,0,0.12)",
                    marginTop: "4px",
                    marginBottom: "8px",
                    overflow: "auto",
                    maxHeight: "240px",
                },
            });

            const iframeWrap = $el("div.fmiyd-artist-gallery-body", {
                style: {
                    flex: "1 1 auto",
                    minHeight: "200px",
                    border: "1px solid #555",
                    borderRadius: "6px",
                    overflow: "hidden",
                    backgroundColor: "#111",
                },
            });

            const iframe = document.createElement("iframe");
            iframe.src = GALLERY_PATH + "?node_id=" + encodeURIComponent(String(node.id));
            iframe.style.width = "100%";
            iframe.style.height = "100%";
            iframe.style.border = "0";
            iframe.loading = "lazy";
            iframe.onload = () => pushDanbooruCredsToIframe(node);
            iframeWrap.appendChild(iframe);

            root.appendChild(header);
            root.appendChild(iframeWrap);

            node.__fmiydArtistState.headerEl = header;
            node.__fmiydArtistState.iframeEl = iframe;
            renderHeader(node);

            node.addDOMWidget("fmiyd_artist_gallery_widget", "div", root, { onDraw: () => {} });

            setTimeout(() => {
                if (typeof node.onResize === "function") node.onResize(node.size);
            }, 10);

        };
    },
});

