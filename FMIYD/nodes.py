# FMIYD — 更衣人偶画廊节点
# 数据来源：https://hayde0096.github.io/kisegae/（hayde0096/Kisegaeningyou）

from __future__ import annotations
from typing import Tuple, Any, Optional, Union
import random
import time
import io
import requests
import base64
import json
import os
import re


# -----------------------------------------------------------------------------
# 更衣人偶画廊
# -----------------------------------------------------------------------------
class FMIYDKisegaeGallery:
    """
    打开「更衣人偶」画廊选择服装，选中后输出该服装的提示词 tag（可接正向提示词编码）。
    数据来源：https://hayde0096.github.io/kisegae/（hayde0096/Kisegaeningyou）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "点节点上「打开更衣人偶画廊」选图后自动填入，无需复制粘贴；也可手动编辑。",
                }),
                "use_random": ("BOOLEAN", {
                    "default": False,
                    "label_on": "随机开启",
                    "label_off": "随机关闭",
                }),
                "gallery_folder": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "当前画廊路径（由前端画廊自动填写，用于随机模式）。",
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "get_prompt"
    CATEGORY = "FMIYD"

    API_TREE = "https://api.github.com/repos/hayde0096/Kisegaeningyou/git/trees/main?recursive=1"
    API_CONTENTS = "https://api.github.com/repos/hayde0096/Kisegaeningyou/contents/"

    def _fetch_json(self, url: str):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _get_random_folder(self) -> str | None:
        data = self._fetch_json(self.API_TREE)
        if not isinstance(data, dict):
            return None
        tree = data.get("tree") or []
        folders = [item["path"] for item in tree if item.get("type") == "tree"]
        if not folders:
            return None
        return random.choice(folders)

    def _get_random_tag_from_folder(self, folder: str) -> str | None:
        contents = self._fetch_json(f"{self.API_CONTENTS}{folder}")
        if not isinstance(contents, list):
            return None
        desc_files = [f for f in contents if isinstance(f, dict) and f.get("name", "").endswith(".desc.txt")]
        if not desc_files:
            return None
        f = random.choice(desc_files)

        # 优先使用 API 返回的 base64 content
        content = f.get("content")
        if content:
            try:
                padded = content + "=" * ((4 - len(content) % 4) % 4)
                raw = base64.b64decode(padded)
                return raw.decode("utf-8", errors="ignore").strip()
            except Exception:
                pass

        # 退回使用 download_url
        download_url = f.get("download_url")
        if not download_url:
            return None
        try:
            resp = requests.get(download_url, timeout=15)
            resp.raise_for_status()
            return resp.text.strip()
        except Exception:
            return None

    def _get_random_tag(self, gallery_folder: str | None) -> str:
        folder = (gallery_folder or "").strip()
        if not folder:
            folder = self._get_random_folder() or ""
        if not folder:
            return ""
        tag = self._get_random_tag_from_folder(folder)
        return tag or ""

    @classmethod
    def IS_CHANGED(cls, prompt: str = "", use_random: bool = False, gallery_folder: str = "", **kwargs):
        """
        在开启随机模式时，让节点在每次执行时都视为“已改变”，从而重新计算随机结果。
        """
        if use_random:
            # 使用当前时间戳作为变化依据，保证每次执行都不相同
            return time.time()
        # 非随机模式下，正常根据输入内容决定是否需要重新计算
        return (prompt, use_random, gallery_folder)

    def get_prompt(self, prompt: str, use_random: bool, gallery_folder: str) -> Tuple[Any]:
        if use_random:
            tag = self._get_random_tag(gallery_folder)
            return (tag or "",)
        return (prompt.strip() or "",)


NODE_CLASS_MAPPINGS = {
    "FMIYDKisegaeGallery": FMIYDKisegaeGallery,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FMIYDKisegaeGallery": "更衣人偶画廊",
}


# -----------------------------------------------------------------------------
# 画师图鉴画廊
# -----------------------------------------------------------------------------


def _fmiyd_artist_tag_dedupe_key(tag: str) -> str:
    """与 __init__._artist_tag_dedupe_key / dedupe_artist_tags 一致。"""
    if not isinstance(tag, str):
        return ""
    t = tag.strip().lower()
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"_+", "_", t)
    return t.strip("_")


class FMIYDArtistGallery:
    """
    以画廊方式展示「画师名」对应的作品缩略图（Danbooru 在线），点击图片后输出该画师的画师tag。
    数值类参数在 Comfy 中为「初始值」；用户修改并保存工作流后，以已保存值为准，不会自动恢复。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 前端隐藏显示；运行时由画廊点击填入
                "prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "由画师图鉴画廊点击图片自动填入：画师tag",
                    },
                ),
                "use_random_artist_prompt": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "随机画师串开启",
                        "label_off": "随机画师串关闭",
                    },
                ),
                "random_tag_count": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 50,
                        "step": 1,
                        "display": "number",
                        "tooltip": "随机画师串长度（= 画师tag数量，随机画师串开启时生效）。新节点首次放置时的初始值；修改后随工作流保存。",
                    },
                ),
                "use_random_weight": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "随机权值开启",
                        "label_off": "随机权值关闭",
                    },
                ),
                # 以下由前端弹窗编辑并隐藏；必须放在 required，否则部分 ComfyUI 版本执行时 optional 不传参，设置不生效
                "weight_min": (
                    "FLOAT",
                    {
                        "default": 0.05,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": "权值随机下限（仅「随机权值开启」时生效）。可大于 1（如强调 tag）。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "weight_max": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": "权值随机上限（仅「随机权值开启」时生效）。可大于 1。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "weight_step": (
                    "FLOAT",
                    {
                        "default": 0.05,
                        "min": 0.01,
                        "max": 0.5,
                        "step": 0.01,
                        "tooltip": "离散权值步长（仅「随机权值开启」时生效）。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "weight_threshold": (
                    "FLOAT",
                    {
                        "default": 0.8,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": "高权阈值：权值高于此算「高权」池（仅「随机权值开启」时生效）。可大于 1。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "min_tags_above_threshold": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": 50,
                        "step": 1,
                        "display": "number",
                        "tooltip": "高权 tag 至少几个（仅「随机权值开启」时生效）。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "max_tags_above_threshold": (
                    "INT",
                    {
                        "default": 3,
                        "min": 0,
                        "max": 50,
                        "step": 1,
                        "display": "number",
                        "tooltip": "高权 tag 至多几个（仅「随机权值开启」时生效）。新节点初始值；修改后随工作流保存。",
                    },
                ),
                "danbooru_login": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "可选。画廊优先匿名请求 D 站；遇 403/限流时再与 API Key 成对填写，由服务端自动重试。勿分享工作流",
                    },
                ),
                "danbooru_api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "可选。与登录名成对使用；仅在匿名被拒时由服务端用于重试。勿分享工作流",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "get_prompt"
    CATEGORY = "FMIYD"

    _artist_tags_cache = None
    _artist_tags_source_dir: Optional[str] = None

    @staticmethod
    def _build_weight_slots(weight_min: float, weight_max: float, weight_step: float) -> list[float]:
        """在 [min,max] 内按步长生成离散权值点。"""
        wmin = float(weight_min)
        wmax = float(weight_max)
        wstep = float(weight_step)
        if wmax < wmin:
            wmin, wmax = wmax, wmin
        if wstep <= 0:
            return [round((wmin + wmax) / 2, 4)]
        slots: list[float] = []
        x = wmin
        i = 0
        while x <= wmax + 1e-9 and i < 10000:
            slots.append(round(x, 4))
            x += wstep
            i += 1
        if not slots:
            slots = [round(wmin, 4)]
        return slots

    @classmethod
    def _load_artist_tags(cls):
        if cls._artist_tags_cache is not None:
            return cls._artist_tags_cache

        cls._artist_tags_source_dir = None
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "artist_export_catalog", "artists_with_images.json"),
            os.path.join(base_dir, "artist_export_2000", "artists_with_images.json"),
            os.path.join(base_dir, "artist_export_1000", "artists_with_images.json"),
        ]

        tags = []
        for p in candidates:
            if not os.path.isfile(p):
                continue
            if cls._artist_tags_source_dir is None:
                cls._artist_tags_source_dir = os.path.dirname(os.path.abspath(p))
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    continue
                for rec in data:
                    if not isinstance(rec, dict):
                        continue
                    tag_val = ""
                    for k, v in rec.items():
                        if isinstance(k, str) and isinstance(v, str) and "tag" in k.lower():
                            tag_val = v.strip()
                    if tag_val:
                        tags.append(tag_val)
                if tags:
                    break
            except Exception:
                continue

        # 去重并保持顺序
        seen = set()
        uniq = []
        for t in tags:
            if t in seen:
                continue
            seen.add(t)
            uniq.append(t)
        cls._artist_tags_cache = uniq
        return uniq

    @staticmethod
    def _parse_prompt_tags(prompt: str):
        """
        从已有画师串中提取 tag 列表。
        支持：
          - tag1, tag2
          - (tag1:0.75), (tag2:1.0)
        """
        s = (prompt or "").strip()
        if not s:
            return []
        parts = [p.strip() for p in s.split(",") if p.strip()]
        out = []
        for p in parts:
            # (tag:0.8) -> tag
            m = re.match(r"^\((.*):\s*([0-9]*\.?[0-9]+)\)$", p)
            if m:
                tag = m.group(1).strip()
                if tag:
                    out.append(tag)
            else:
                out.append(p)
        return out

    @classmethod
    def _assign_random_weights(
        cls,
        tags: list,
        weight_min: float,
        weight_max: float,
        weight_step: float,
        weight_threshold: float,
        min_tags_above_threshold: int,
        max_tags_above_threshold: int,
    ) -> list[tuple[str, float]]:
        """
        在 [weight_min, weight_max] 内按 weight_step 取离散点；
        高于 weight_threshold 的为「高权」池，否则为「低权」池；
        高权 tag 个数在 [min_tags_above_threshold, max_tags_above_threshold] 内随机（并受 tag 总数约束）。
        """
        n = len(tags)
        if n <= 0:
            return []

        slots = cls._build_weight_slots(weight_min, weight_max, weight_step)
        if len(slots) == 1:
            w0 = slots[0]
            return [(str(t), w0) for t in tags]

        thr = float(weight_threshold)
        low_pool = [x for x in slots if x <= thr]
        high_pool = [x for x in slots if x > thr]

        if not high_pool:
            high_pool = [max(slots)]
        if not low_pool:
            low_pool = [x for x in slots if x < max(high_pool)] or [min(slots)]

        # 若阈值导致高低池实际重叠（仅一个离散点落在两侧），退化为全池随机
        if max(low_pool) >= min(high_pool) and len(slots) > 1:
            low_pool = [x for x in slots if x < max(slots)]
            high_pool = [x for x in slots if x >= min(slots)]
            if not low_pool:
                low_pool = [min(slots)]
            if not high_pool:
                high_pool = [max(slots)]

        ma = max(0, int(min_tags_above_threshold))
        xa = max(0, int(max_tags_above_threshold))
        if xa < ma:
            xa = ma
        xa = min(xa, n)
        ma = min(ma, xa)

        high_count = random.randint(ma, xa) if ma <= xa else 0

        high_idx = set(random.sample(range(n), high_count)) if high_count > 0 else set()

        weighted: list[tuple[str, float]] = []
        for i, tag in enumerate(tags):
            pool = high_pool if i in high_idx else low_pool
            if not pool:
                pool = slots
            w = random.choice(pool)
            weighted.append((str(tag), float(w)))
        return weighted

    @staticmethod
    def _format_weighted_tags(weighted):
        parts = []
        for tag, w in weighted:
            if not tag:
                continue
            # 两位小数，去掉末尾无效 0
            ws = f"{w:.2f}".rstrip("0").rstrip(".")
            parts.append(f"({tag}:{ws})")
        return ", ".join(parts)

    @classmethod
    def IS_CHANGED(
        cls,
        prompt: str = "",
        use_random_artist_prompt: bool = False,
        random_tag_count: int = 4,
        use_random_weight: bool = False,
        weight_min: Optional[float] = None,
        weight_max: Optional[float] = None,
        weight_step: Optional[float] = None,
        weight_threshold: Optional[float] = None,
        min_tags_above_threshold: Optional[int] = None,
        max_tags_above_threshold: Optional[int] = None,
        danbooru_login: str = "",
        danbooru_api_key: str = "",
        **kwargs,
    ):
        # 任意随机功能开启时，每次执行都强制重算
        if use_random_artist_prompt or use_random_weight:
            return time.time()
        return (
            prompt,
            use_random_artist_prompt,
            random_tag_count,
            use_random_weight,
            weight_min,
            weight_max,
            weight_step,
            weight_threshold,
            min_tags_above_threshold,
            max_tags_above_threshold,
            danbooru_login,
            danbooru_api_key,
        )

    @staticmethod
    def _prompt_output_for_ui(final: str) -> dict[str, Any]:
        """
        Comfy 仅在节点返回 dict 且含「ui」时才会向前端发 executed 消息（见官方 comms_messages）。
        画廊历史依赖 extension 监听 executed + output.prompt；纯 tuple 返回值不会触发 executed。
        """
        s = final if isinstance(final, str) else str(final)
        return {"ui": {"prompt": [s]}, "result": (s,)}

    def get_prompt(
        self,
        prompt: str,
        use_random_artist_prompt: bool,
        random_tag_count: int,
        use_random_weight: bool,
        weight_min: Optional[float] = None,
        weight_max: Optional[float] = None,
        weight_step: Optional[float] = None,
        weight_threshold: Optional[float] = None,
        min_tags_above_threshold: Optional[int] = None,
        max_tags_above_threshold: Optional[int] = None,
        danbooru_login: str = "",
        danbooru_api_key: str = "",
    ) -> Union[Tuple[Any, ...], dict[str, Any]]:
        use_rand_art = bool(use_random_artist_prompt)
        use_rand_w = bool(use_random_weight)
        prompt_s = (prompt or "").strip()

        # 画廊多选写入的 (tag:0.9) 等形式：两随机皆关时必须原样输出，不能用 _parse_prompt_tags 拆成无权重串
        if not use_rand_art and not use_rand_w:
            return self._prompt_output_for_ui(prompt_s)

        tags: list[str] = []
        if use_rand_art:
            all_tags = self._load_artist_tags()
            bl = _fmiyd_load_blacklisted_dedupe_keys()
            if bl:
                all_tags = [t for t in all_tags if _fmiyd_artist_tag_dedupe_key(t) not in bl]
            if all_tags:
                k = max(1, min(int(random_tag_count or 1), len(all_tags)))
                tags = random.sample(all_tags, k)
        else:
            tags = self._parse_prompt_tags(prompt)

        if not tags:
            return self._prompt_output_for_ui("")

        if use_rand_w:
            wmin = 0.05 if weight_min is None else float(weight_min)
            wmax = 1.0 if weight_max is None else float(weight_max)
            wstep = 0.05 if weight_step is None else float(weight_step)
            wthr = 0.8 if weight_threshold is None else float(weight_threshold)
            min_hi = 1 if min_tags_above_threshold is None else int(min_tags_above_threshold)
            max_hi = 3 if max_tags_above_threshold is None else int(max_tags_above_threshold)
            weighted = self._assign_random_weights(
                tags,
                wmin,
                wmax,
                wstep,
                wthr,
                min_hi,
                max_hi,
            )
            return self._prompt_output_for_ui(self._format_weighted_tags(weighted))

        return self._prompt_output_for_ui(", ".join(tags))


_blacklist_cache_mtime: Optional[float] = None
_blacklist_cache_keys: Optional[frozenset[str]] = None


def _fmiyd_blacklist_json_path() -> str:
    d = getattr(FMIYDArtistGallery, "_artist_tags_source_dir", None)
    if not d:
        FMIYDArtistGallery._load_artist_tags()
        d = getattr(FMIYDArtistGallery, "_artist_tags_source_dir", None) or ""
    if not d:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artist_export_catalog")
    return os.path.join(d, "artist_blacklist.json")


class FMIYDPixivGallery:
    """
    简化版 Pixiv：内嵌画廊默认展示排行榜，支持作品搜索与指定用户作品；
    选中插画后运行节点输出对应图片张量（多选则 batch 维拼接，尺寸统一到首张）。
    需配置 OAuth refresh_token（与官方 App 相同鉴权方式，勿分享工作流）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selected_urls": (
                    "STRING",
                    {
                        "default": "[]",
                        "multiline": True,
                        "tooltip": "由画廊自动写入：选中插画的下载 URL（JSON 数组）。",
                    },
                ),
                "selected_url": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "由画廊自动写入：当前单选图片 URL（单选主通道）。",
                    },
                ),
                "selection_nonce": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "画廊内部使用：每次选择变化会更新，确保执行读取到最新选择。",
                    },
                ),
                "pixiv_refresh_token": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Pixiv OAuth refresh_token，用于登录并拉取排行榜/收藏/关注等；勿分享工作流。",
                    },
                ),
                "pixiv_cookie": (
                    "STRING",
                    {
                        "default": "PHPSESSID=...",
                        "multiline": True,
                        "tooltip": "Pixiv Cookie（可仅填 PHPSESSID，或完整 Cookie 字符串）；用于收藏/关注等网页登录态请求。",
                    },
                ),
                "pixiv_user_id": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Cookie 模式建议填写自己的 Pixiv 用户 ID（数字）。",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load_images"
    CATEGORY = "FMIYD"

    @classmethod
    def IS_CHANGED(
        cls,
        selected_urls: str = "",
        selected_url: str = "",
        selection_nonce: str = "",
        pixiv_refresh_token: str = "",
        pixiv_cookie: str = "",
        pixiv_user_id: str = "",
        **kwargs,
    ):
        return (
            selected_urls or "",
            selected_url or "",
            selection_nonce or "",
            pixiv_refresh_token or "",
            pixiv_cookie or "",
            pixiv_user_id or "",
        )

    def load_images(
        self,
        selected_urls: str,
        selected_url: str = "",
        selection_nonce: str = "",
        pixiv_refresh_token: str = "",
        pixiv_cookie: str = "",
        pixiv_user_id: str = "",
    ):
        import numpy as np
        import torch
        from PIL import Image

        direct = (selected_url or "").strip()
        if isinstance(direct, str) and direct.startswith("https://"):
            urls = [direct]
        else:
            raw = (selected_urls or "").strip()
            urls = []
            if raw.startswith("["):
                try:
                    arr = json.loads(raw)
                    if isinstance(arr, list):
                        urls = [str(u).strip() for u in arr if isinstance(u, str) and u.strip()]
                except Exception:
                    urls = []
            elif raw:
                urls = [raw]

        if not urls:
            return (torch.zeros(1, 64, 64, 3, dtype=torch.float32),)

        # Pixiv 画廊当前为单选语义：后端执行时只认“最后一次选择”的 URL，
        # 避免历史残留值排在前面导致输出旧图。
        urls = [urls[-1]]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.pixiv.net/",
        }
        tensors: list[torch.Tensor] = []
        for url in urls:
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            try:
                r = requests.get(url, headers=headers, timeout=120)
                r.raise_for_status()
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                arr = np.array(im).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(arr))
            except Exception:
                continue

        if not tensors:
            return (torch.zeros(1, 64, 64, 3, dtype=torch.float32),)

        h0, w0 = tensors[0].shape[0], tensors[0].shape[1]
        aligned: list[torch.Tensor] = []
        for t in tensors:
            if t.shape[0] == h0 and t.shape[1] == w0:
                aligned.append(t)
                continue
            arr = (t.numpy() * 255.0).clip(0, 255).astype("uint8")
            im = Image.fromarray(arr)
            im = im.resize((w0, h0), Image.Resampling.LANCZOS)
            arr2 = np.array(im).astype(np.float32) / 255.0
            aligned.append(torch.from_numpy(arr2))

        batched = torch.stack(aligned, dim=0)
        return (batched,)


class FMIYDDanbooruGallery:
    """
    全新 D 站画廊节点：内嵌画廊浏览 Danbooru 图片，单选后输出 IMAGE。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selected_urls": (
                    "STRING",
                    {
                        "default": "[]",
                        "multiline": True,
                        "tooltip": "由画廊自动写入：选中图片 URL（JSON 数组）。",
                    },
                ),
                "selected_url": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "由画廊自动写入：当前单选图片 URL（单选主通道）。",
                    },
                ),
                "selection_nonce": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "画廊内部使用：每次选择变化会更新，确保执行读取到最新选择。",
                    },
                ),
                "selected_tags": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "由画廊自动写入：当前选中图片的 tag 串。",
                    },
                ),
                "danbooru_login": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Danbooru 账号 login（可选，仅在匿名受限时使用）。",
                    },
                ),
                "danbooru_api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Danbooru API Key（可选，勿分享工作流）。",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "tags")
    FUNCTION = "load_images"
    CATEGORY = "FMIYD"

    @classmethod
    def IS_CHANGED(
        cls,
        selected_urls: str = "",
        selected_url: str = "",
        selection_nonce: str = "",
        selected_tags: str = "",
        danbooru_login: str = "",
        danbooru_api_key: str = "",
        **kwargs,
    ):
        return (
            selected_urls or "",
            selected_url or "",
            selection_nonce or "",
            selected_tags or "",
            danbooru_login or "",
            danbooru_api_key or "",
        )

    def load_images(
        self,
        selected_urls: str,
        selected_url: str = "",
        selection_nonce: str = "",
        selected_tags: str = "",
        danbooru_login: str = "",
        danbooru_api_key: str = "",
    ):
        import numpy as np
        import torch
        from PIL import Image

        direct = (selected_url or "").strip()
        if isinstance(direct, str) and direct.startswith("https://"):
            urls = [direct]
        else:
            raw = (selected_urls or "").strip()
            urls = []
            if raw.startswith("["):
                try:
                    arr = json.loads(raw)
                    if isinstance(arr, list):
                        urls = [str(u).strip() for u in arr if isinstance(u, str) and u.strip()]
                except Exception:
                    urls = []
            elif raw:
                urls = [raw]

        if not urls:
            return (torch.zeros(1, 64, 64, 3, dtype=torch.float32), (selected_tags or "").strip())

        urls = [urls[-1]]
        headers = {
            "User-Agent": "FMIYD-DanbooruGallery/1.0",
            "Referer": "https://danbooru.donmai.us/",
        }
        tensors: list[torch.Tensor] = []
        for url in urls:
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            try:
                r = requests.get(url, headers=headers, timeout=120)
                r.raise_for_status()
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                arr = np.array(im).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(arr))
            except Exception:
                continue

        if not tensors:
            return (torch.zeros(1, 64, 64, 3, dtype=torch.float32), (selected_tags or "").strip())

        h0, w0 = tensors[0].shape[0], tensors[0].shape[1]
        aligned: list[torch.Tensor] = []
        for t in tensors:
            if t.shape[0] == h0 and t.shape[1] == w0:
                aligned.append(t)
                continue
            arr = (t.numpy() * 255.0).clip(0, 255).astype("uint8")
            im = Image.fromarray(arr)
            im = im.resize((w0, h0), Image.Resampling.LANCZOS)
            arr2 = np.array(im).astype(np.float32) / 255.0
            aligned.append(torch.from_numpy(arr2))
        return (torch.stack(aligned, dim=0), (selected_tags or "").strip())


def _fmiyd_load_blacklisted_dedupe_keys() -> set[str]:
    global _blacklist_cache_mtime, _blacklist_cache_keys
    path = _fmiyd_blacklist_json_path()
    try:
        mt = os.path.getmtime(path) if os.path.isfile(path) else -1.0
    except OSError:
        mt = -1.0
    if _blacklist_cache_keys is not None and _blacklist_cache_mtime == mt:
        return set(_blacklist_cache_keys)
    keys: set[str] = set()
    if mt >= 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for x in data:
                    if isinstance(x, str) and x.strip():
                        keys.add(_fmiyd_artist_tag_dedupe_key(x))
        except Exception:
            pass
    _blacklist_cache_mtime = mt
    _blacklist_cache_keys = frozenset(keys)
    return set(keys)


# 节点注册
NODE_CLASS_MAPPINGS.update(
    {
        "FMIYDArtistGallery": FMIYDArtistGallery,
        "FMIYDPixivGallery": FMIYDPixivGallery,
        "FMIYDDanbooruGallery": FMIYDDanbooruGallery,
    }
)

NODE_DISPLAY_NAME_MAPPINGS.update(
    {
        "FMIYDArtistGallery": "画师图鉴画廊",
        "FMIYDPixivGallery": "Pixiv 画廊",
        "FMIYDDanbooruGallery": "D站画廊（全新）",
    }
)
