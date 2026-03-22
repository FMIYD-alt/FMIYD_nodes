/**
 * FMIYD 画廊节点 — ComfyUI 内懒人自动化
 * 参考 D 站画廊实现，将「更衣人偶画廊」直接以内嵌 DOM widget 方式挂在节点上，
 * 不再使用额外按钮弹窗。
 */
import { app } from "/scripts/app.js";
import { $el } from "/scripts/ui.js";

const NODE_TYPE_KISEGAE = "FMIYDKisegaeGallery";
const PROMPT_WIDGET_NAME = "prompt";
const FOLDER_WIDGET_NAME = "gallery_folder";
const GALLERY_PATH = "/fmiyd/kisegae";

function applyTagToNode(tag, nodeId) {
    if (tag == null) return;
    try {
        const graph = app?.graph;
        if (!graph) return;

        let node = null;

        // 1. 如果传入了 nodeId，优先按 ID 查找
        if (nodeId != null) {
            if (typeof graph.getNodeById === "function") {
                try {
                    node = graph.getNodeById(Number(nodeId)) || graph.getNodeById(nodeId);
                } catch (e) {}
            }
            if (!node && graph._nodes) {
                node = graph._nodes.find(
                    (n) => n && (String(n.id) === String(nodeId) || n.id === Number(nodeId))
                );
            }
        }

        // 2. 如果没找到，退回到「当前选中的 FMIYDKisegaeGallery 节点」
        if (!node) {
            const canvas = app?.canvas;
            if (canvas && canvas.selected_nodes) {
                const list = Array.isArray(canvas.selected_nodes)
                    ? canvas.selected_nodes
                    : Object.values(canvas.selected_nodes);
                node = list.find(
                    (n) =>
                        n &&
                        n.widgets &&
                        (n.type === NODE_TYPE_KISEGAE || n.comfyClass === NODE_TYPE_KISEGAE)
                );
            }
        }

        // 3. 如果还没找到，作为兜底：使用图里第一个更衣人偶节点
        if (!node && graph._nodes) {
            node = graph._nodes.find(
                (n) =>
                    n &&
                    n.widgets &&
                    (n.type === NODE_TYPE_KISEGAE || n.comfyClass === NODE_TYPE_KISEGAE)
            );
        }

        if (!node?.widgets) return;
        const w = node.widgets.find((wi) => wi.name === PROMPT_WIDGET_NAME);
        if (w) {
            w.value = typeof tag === "string" ? tag : String(tag);
            if (typeof w.callback === "function") w.callback(w.value);
        }
        if (app.graph) app.graph.change();
    } catch (e) {}
}

window.addEventListener("message", (ev) => {
    if (!ev.data) return;
    const type = ev.data.type;
    if (type === "fmiyd_kisegae_tag") {
        const tag = ev.data.tag;
        const nodeId = ev.data.node_id;
        applyTagToNode(tag, nodeId);
        return;
    }

    if (type === "fmiyd_kisegae_folder") {
        const folder = ev.data.folder;
        const nodeId = ev.data.node_id;
        if (!folder) return;
        try {
            const graph = app?.graph;
            if (!graph) return;
            let node = null;
            if (typeof graph.getNodeById === "function" && nodeId != null) {
                try {
                    node = graph.getNodeById(Number(nodeId)) || graph.getNodeById(nodeId);
                } catch (e) {}
            }
            if (!node && graph._nodes) {
                node = graph._nodes.find(
                    (n) =>
                        n &&
                        n.widgets &&
                        (n.type === NODE_TYPE_KISEGAE || n.comfyClass === NODE_TYPE_KISEGAE)
                );
            }
            if (!node?.widgets) return;
            const w = node.widgets.find((wi) => wi.name === FOLDER_WIDGET_NAME);
            if (w) {
                w.value = String(folder);
                if (typeof w.callback === "function") w.callback(w.value);
                if (app.graph) app.graph.change();
            }
        } catch (e) {}
    }
});

app.registerExtension({
    name: "FMIYD.KisegaeGalleryEmbed",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE_KISEGAE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const node = this;

            // 隐藏原本的 prompt / gallery_folder 文本框，只保留内部存储功能
            if (Array.isArray(node.widgets)) {
                const hideWidget = (w) => {
                    if (!w) return;
                    w.computeSize = () => [0, -4];
                    w.draw = () => {};
                    w.type = "hidden";
                    try {
                        Object.defineProperty(w, "hidden", {
                            value: true,
                            writable: false,
                        });
                    } catch (e) {}
                };

                const promptWidget = node.widgets.find((w) => w && w.name === PROMPT_WIDGET_NAME);
                hideWidget(promptWidget);

                const folderWidget = node.widgets.find((w) => w && w.name === FOLDER_WIDGET_NAME);
                hideWidget(folderWidget);
            }

            // 参考 D 站画廊，扩展节点高度以容纳内嵌画廊
            if (Array.isArray(node.size)) {
                const w = Math.max(node.size[0] || 360, 700);
                const h = Math.max(node.size[1] || 200, 820);
                node.size = [w, h];
            } else if (typeof node.setSize === "function") {
                node.setSize([700, 820]);
            }

            // 创建容器，参考 D 站画廊的 addDOMWidget 用法
            const container = $el("div.fmiyd-kisegae-gallery", {
                style: {
                    width: "100%",
                    height: "100%",
                    border: "1px solid #555",
                    borderRadius: "6px",
                    overflow: "hidden",
                    backgroundColor: "#111",
                    marginTop: "4px",
                },
            });

            const iframe = document.createElement("iframe");
            iframe.src = GALLERY_PATH + "?node_id=" + encodeURIComponent(String(node.id));
            iframe.style.width = "100%";
            iframe.style.height = "100%";
            iframe.style.border = "0";
            iframe.loading = "lazy";
            container.appendChild(iframe);

            node.addDOMWidget("fmiyd_kisegae_gallery", "div", container, {
                onDraw: () => {},
            });

            // 调整节点尺寸，避免被裁切
            setTimeout(() => {
                if (typeof node.onResize === "function") {
                    node.onResize(node.size);
                }
            }, 10);
        };
    },
});
