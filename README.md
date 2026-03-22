# FMIYD — 画廊与角色 Prompt 节点

ComfyUI 自定义节点包，包含两类「选图/选角色 → 自动填 prompt」的懒人节点，均可接任意「正向提示词编码」使用。

---

## 节点一览

| 节点 | 说明 |
|------|------|
| **更衣人偶画廊** | 服装图 gallery，选图后输出该服装的 tag（[更衣人偶](https://hayde0096.github.io/kisegae/) 数据）。 |
| **二次元角色提示词查找** | 动漫/游戏角色 prompt 查询，支持 Include/Exclude、匹配方式、排序、分页等；点击卡片即自动填入节点，无需复制粘贴（[Drawing Spells](https://hbl917070.github.io/DrawingSpells/) 功能移植，NoobAI-XL 训练集数据）。 |

---

## 安装

将本目录放入 ComfyUI 的 `custom_nodes` 下，重启 ComfyUI，在节点菜单 **FMIYD** 下即可看到上述节点。

---

## 更衣人偶画廊

- 添加节点后点击 **「打开更衣人偶画廊」**，在弹窗中选画廊、点一张服装图，提示词会**自动填回**该节点。
- 将节点的 **prompt** 输出接到「正向提示词编码」即可生图。
- 数据来源：[更衣人偶](https://hayde0096.github.io/kisegae/)（[hayde0096/Kisegaeningyou](https://github.com/hayde0096/Kisegaeningyou)）。

---

## 二次元角色提示词查找

- 添加节点后点击 **「打开二次元角色提示词查找」**，在弹窗中可：
  - **包含 Include**：逗号或换行分隔，支持 `|` 表示或；
  - **排除 Exclude**：逗号或换行分隔；
  - **更多选项**：匹配方式（Substring/Exact）、排序（Default/Image Count/Random）、排除图数过少的角色、每页条数、复制时忽略的 tag 等。
- **点击任意卡片即可自动填入节点**，无需复制粘贴；卡片下方仍可单独复制「名称」「名称+作品」或「完整提示词」。
- 数据来源：[Drawing Spells](https://hbl917070.github.io/DrawingSpells/)（[GitHub](https://github.com/hbl917070/DrawingSpells)），基于 NoobAI-XL 训练用数据集；首次加载会从 GitHub 拉取数据，之后会使用本地缓存。

---

## 通用说明

- **ComfyUI-aki（秋叶整合包）**：前端已按 ComfyUI 官方扩展方式编写，若未出现按钮可先刷新页面。
- **备用**：在浏览器直接打开 `http://127.0.0.1:8188/fmiyd/kisegae` 或 `http://127.0.0.1:8188/fmiyd/drawing_spells`（端口按实际改）；从节点打开的弹窗中选图/选角色会**自动填入**，无需复制粘贴。

---

## 依赖

仅依赖 ComfyUI 本体，无第三方 Python 节点依赖。

---

## 目录结构

```
FMIYD/
├── __init__.py
├── nodes.py
├── web/
│   ├── kisegae_gallery.js           # 两个节点的按钮注入 + postMessage 填回
│   ├── kisegae_standalone.html      # 更衣人偶画廊页
│   └── drawing_spells_standalone.html # Drawing Spells 页
├── scripts/
│   ├── fetch_danbooru_artist_images.py  # 可选：本机灌库，把图写入 artist_export_catalog（非在线画廊）
│   └── audit_danbooru_tag_coverage.py  # 统计库内画师 tag 在 Danbooru 能否查到图（需可访问 D 站）
└── README.md
```

### 用 Danbooru **灌进本地库**（可选维护脚本）

这是**一次性维护脚本**：运行后会把图片写入扩展根目录 `images/xl/drawings/media/`，并更新 `artist_export_catalog/artists_with_images.json` 的 `_images` 列表。**ComfyUI「画师图鉴画廊」的缩略图已改为在线从 Danbooru 加载**，不依赖本机 `images/`；删掉或移走 `images` 文件夹不影响画廊浏览。

在仓库根目录执行（需已安装 `requests`）：

```bash
pip install requests
python scripts/fetch_danbooru_artist_images.py --db-dir artist_export_catalog
```

建议配置 [Danbooru API Key](https://danbooru.donmai.us/profile) 并设置环境变量 `DANBOORU_LOGIN`、`DANBOORU_API_KEY`，否则易出现 403/限流。默认仅抓取 `rating:general`，可用 `--rating ""` 关闭分级过滤（请自行遵守站点规则与当地法律）。

**统计 tag 在 D 站是否有图（命中率）**：

```bash
python scripts/audit_danbooru_tag_coverage.py --sample 400
python scripts/audit_danbooru_tag_coverage.py --all
```

**本地图片目录（可选）**：仅当你运行上述灌库/合并脚本时需要；路径为 `images/xl/drawings/media/`（与 JSON 分离；可由 `move_artist_media_to_root.py` 从旧目录迁移）。扩展**不会**在启动时自动创建该目录。

**删除 D 站无帖画师**（先生成失败列表再剪枝）：

```bash
python scripts/audit_danbooru_tag_coverage.py --all --failures-out danbooru_zero_miss_tags.txt
python scripts/prune_artists_no_danbooru.py --failures-file danbooru_zero_miss_tags.txt
```
