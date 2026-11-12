"""「素材历史」与「推广图片查阅 / 下载」的服务层。

V4.36：把原本完全不落库的「素材创作」流程（落地页分析 → 广告文案 → 推广图片）
按会话落库，提供再查阅、再下载与批量清理能力。

职责：
- 历史记录的序列化（含 UTC 时区显式化，避免前端显示差 8 小时）
- 从落地页 URL / 分析结论推断展示标题
- 安全解析 uploads 下的图片文件名（防目录穿越）
- 打包 ZIP：图片 + 广告文案 TXT/JSON + 落地页分析 JSON + 生成信息
- 批量删除时清理磁盘孤儿文件（仍被其它历史引用的文件不删）
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import csv
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}


# ----------------------------- 时间 / 序列化 -----------------------------

def _iso(dt) -> str | None:
    """SQLite 取回的 DateTime 通常是 naive UTC；统一输出带时区的 ISO。"""
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def history_to_dict(row) -> dict:
    """列表 / 详情统一输出结构。"""
    images = row.images_json or []
    if not isinstance(images, list):
        images = []
    return {
        "id": row.id,
        "title": row.title or "未命名素材会话",
        "url": row.url or "",
        "site_name": row.site_name or "",
        "platform": row.platform or "",
        "lang": row.lang or "",
        "analysis": row.analysis_json or None,
        "copy": row.copy_json or None,
        "images": images,
        "style_opts": row.style_opts_json or {},
        "image_model": row.image_model_json or None,
        "note": row.note or "",
        "image_count": int(row.image_count or len(images)),
        "has_copy": bool(row.has_copy),
        "owner_name": row.owner_name or "",
        "source_id": row.source_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        # V4.42 / F12：明确告知前端「images 只是展示缓存」，完整记录走分页接口
        "display_cache_limit": 80,
        "retention_policy": ("完整素材保存在不可变 creative_assets 记录中，不自动截断；"
                             "按 history_id 分页查询 /api/creative-assets 可读取早期素材"),
        "asset_list_url": f"/api/creative-assets?history_id={row.id}",
    }


# ----------------------------- 标题推断 -----------------------------

def site_name_of(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower().split(":")[0]
        host = re.sub(r"^www\.", "", host)
        return host
    except Exception:
        return ""


def derive_title(analysis: dict | None, url: str, platform: str = "") -> str:
    a = analysis or {}
    site = site_name_of(url or a.get("url", ""))
    industry = (a.get("industry") or "").strip()
    brand = (a.get("type") or "").strip()
    base = site or industry or brand or "正文分析"
    if not site and industry:
        base = f"{industry}"
        if brand and brand != industry:
            base += f" · {brand}"
    return f"{base} · {platform}" if platform else base


# ----------------------------- 文件路径安全 -----------------------------

def safe_image_path(name: str) -> str | None:
    """只接受 uploads 目录下的**纯文件名**，杜绝 ../ 与绝对路径穿越。"""
    raw = (name or "").strip()
    if not raw or "/" in raw or "\\" in raw or "\x00" in raw:
        return None
    base = os.path.basename(raw)
    if base != raw or base in (".", "..") or not base:
        return None
    if os.path.splitext(base)[1].lower() not in _ALLOWED_EXT:
        return None
    path = os.path.realpath(os.path.join(UPLOAD_DIR, base))
    root = os.path.realpath(UPLOAD_DIR)
    if os.path.commonpath([path, root]) != root:
        return None
    return path if os.path.isfile(path) else None


def image_files_of(row) -> list[str]:
    out = []
    for im in (row.images_json or []):
        if not isinstance(im, dict):
            continue
        f = im.get("file") or ""
        if not f and im.get("url"):
            f = os.path.basename(str(im["url"]))
        if f:
            out.append(os.path.basename(str(f)))
    return out


def media_type_of(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


# ----------------------------- 文案文本 -----------------------------

def copy_as_text(row) -> str:
    c = row.copy_json or {}
    fields = c.get("fields") or {}
    schema = c.get("schema") or []
    labels = {s.get("key"): s.get("label", s.get("key")) for s in schema if isinstance(s, dict)}
    lines = [
        f"广告推广文案 · {row.platform or '-'} · {row.lang or '-'}",
        f"落地页：{row.url or '-'}",
        f"生成时间：{_iso(row.updated_at) or '-'}",
        "-" * 50,
    ]
    if c.get("brand"):
        lines.append(f"品牌名：{c['brand']}")
        lines.append("-" * 50)
    for k, v in fields.items():
        label = labels.get(k, k)
        if isinstance(v, list):
            for i, item in enumerate(v, 1):
                lines.append(f"{label} {i}：{item}")
        else:
            lines.append(f"{label}：{v}")
    if c.get("validation") and not c["validation"].get("valid", True):
        lines += ["", "【校验提示】"]
        for p in (c["validation"].get("issues") or []):
            if isinstance(p, dict):
                lines.append(f"- {p.get('message', '')}")
    # V4.38：记录用户勾选了哪些创意文案、每张图片按什么组合出图，便于回溯与复用。
    sel = c.get("selected_copy") or {}
    if isinstance(sel, dict) and sel:
        lines += ["", "【本次选用的创意文案】"]
        for k, flags in sel.items():
            if not isinstance(flags, list):
                continue
            vals = fields.get(k)
            vals = vals if isinstance(vals, list) else [vals]
            picked = [str(vals[i]) for i, on in enumerate(flags)
                      if on and i < len(vals) and vals[i]]
            if picked:
                lines.append(f"- {labels.get(k, k)}：{' / '.join(picked)}")
    vs = c.get("copy_variants") or []
    if isinstance(vs, list) and vs:
        lines += ["", "【图片使用的文案组合（按任务矩阵指定概念）】"]
        for i, v in enumerate(vs[:40], 1):
            if isinstance(v, dict):
                lines.append(f"- {v.get('label') or f'组合 {i}'}："
                             f"{v.get('headline') or '（无标题）'} | "
                             f"{v.get('sub') or '（无副标）'} | "
                             f"{v.get('cta') or '（无 CTA）'}")
    # V4.40 / F08：每份导出标记适用广告产品与规则版本，避免把内部尺寸当永久官方标准。
    imgs = row.images_json if isinstance(row.images_json, list) else []
    tagged = [x for x in imgs if isinstance(x, dict) and
              (x.get("ad_product") or x.get("spec_version"))]
    if tagged:
        lines += ["", "【适用广告产品与规则版本】"]
        for key, label in (("ad_product", "广告产品"), ("spec_version", "规则版本")):
            vals = list(dict.fromkeys(str(x.get(key) or "").strip() for x in tagged
                                     if str(x.get(key) or "").strip()))
            if vals:
                lines.append(f"{label}：{' / '.join(vals)}")
        lines.append("说明：规则版本为系统内部整理，正式投放前须按平台官方文档复核。")
    # V4.41 / F04：展示「当时」实际生效的预设解析结果，不能被后续预设修改覆盖。
    cfg = (row.style_opts_json or {}).get("creative_config") if isinstance(row.style_opts_json, dict) else None
    if not isinstance(cfg, dict) or not cfg:
        for x in imgs:
            if isinstance(x, dict) and isinstance(x.get("creative_config"), dict):
                cfg = x["creative_config"]
                break
    if isinstance(cfg, dict) and cfg:
        lines += ["", "【本次生成实际生效的创意配置（历史快照）】"]
        lines.append(f"配置 ID：{cfg.get('config_id', '')} ｜ 版本：{cfg.get('version', '')} ｜ "
                     f"哈希：{str(cfg.get('hash', ''))[:16]}")
        ids = cfg.get("preset_ids") if isinstance(cfg.get("preset_ids"), dict) else {}
        if ids:
            lines.append("预设：方向 " + str(ids.get("direction") or "—")
                         + " / 风格 " + str(ids.get("style") or "—")
                         + " / 配色 " + str(ids.get("color") or "—"))
        if cfg.get("custom_fields"):
            lines.append("管理员编辑过的预设：" + "、".join(str(x) for x in cfg["custom_fields"]))
        lines.append("说明：策略字段参与文案与画面语义，纯视觉字段只作用于画面；此快照不被后续配置覆盖。")
    layouts = list(dict.fromkeys(str(x.get("layout") or "").strip() for x in imgs
                                 if isinstance(x, dict) and x.get("layout")))
    if layouts:
        lines.append("本次使用版式：" + " / ".join(layouts))
    # V4.42 / F06：逐图记录请求 / 返回尺寸与主体保护构图；F12：服务端任务与归档
    modes = list(dict.fromkeys(
        str((x.get("composition") or {}).get("mode") or "").strip()
        for x in imgs if isinstance(x, dict) and (x.get("composition") or {}).get("mode")))
    if modes:
        lines += ["", "【构图与尺寸能力（F06）】"]
        lines.append("构图模式：" + " / ".join(modes))
        for x in imgs:
            if not isinstance(x, dict) or not x.get("composition"):
                continue
            comp = x["composition"]
            req = "×".join(str(v) for v in (x.get("request_size") or [])) or "—"
            ret = "×".join(str(v) for v in (x.get("returned_size") or [])) or "—"
            lines.append(f"- {x.get('size') or '—'}：请求 {req} / 实际返回 {ret} / "
                         f"{comp.get('mode') or '—'} / 裁切 {comp.get('crop') or '未裁切'}")
        lines.append("说明：尺寸能力以官方文档与受控测试为准；未核验比例由渲染端扩图或主体保护处理。")
    job_ids = list(dict.fromkeys(str(x.get("job_id") or "").strip() for x in imgs
                                 if isinstance(x, dict) and x.get("job_id")))
    if job_ids:
        lines += ["", "【服务端生成任务（F12）】", "任务 ID：" + " / ".join(job_ids),
                  "生成与归档由服务端完成，浏览器断开不影响结果；完整资产按 history_id 分页查询。"]
    lines.append("历史保留策略：完整素材保存在不可变记录中，不自动截断；列表仅缓存最近 80 张。")
    return "\n".join(lines) + "\n"


def analysis_as_text(row) -> str:
    a = row.analysis_json or {}
    if not a:
        return "（本次会话未保存落地页分析结论）\n"
    lines = [
        f"网站地址：{a.get('url') or row.url or '-'}",
        f"语言：{a.get('language') or '-'}",
        f"行业：{a.get('industry') or '-'}",
        f"类型：{a.get('type') or '-'}",
        f"对象：{a.get('audience') or '-'}",
        f"竞品：{'、'.join(a.get('competitors') or []) or '-'}",
        "优势：",
    ]
    lines += [f"  - {x}" for x in (a.get("advantages") or [])] or ["  -"]
    lines.append("推广途径：")
    for ch in (a.get("channels") or []):
        if isinstance(ch, dict):
            lines.append(f"  - {ch.get('platform', '-')}：{ch.get('reason', '')}")
    mi = a.get("model_info") or {}
    if mi:
        lines.append(f"分析模型：{mi.get('provider', '-')} / {mi.get('model', '-')}"
                     + ("（兜底）" if mi.get("fallback") else ""))
    # V4.42 / F09：事实 / 假设 / 缺口与证据编号可追溯
    if a.get("evidence_coverage") or a.get("facts") or a.get("gaps") or a.get("legacy_unverified"):
        lines += ["", "【事实证据链】",
                  f"证据门：{a.get('evidence_gate') or '—'} ｜ 原文 {a.get('evidence_source_chars') or 0} 字 ｜ "
                  f"送入 {len(a.get('evidence_coverage') or [])} 段 ｜ 未覆盖 {a.get('evidence_dropped_chars') or 0} 字"]
        for key, label in (("facts", "已验证事实"), ("assumptions", "营销假设"),
                           ("gaps", "资料缺口")):
            vals = a.get(key) or []
            if vals:
                lines.append(f"{label}：" + "；".join(str(x) for x in vals))
        if a.get("evidence_ids"):
            lines.append("可引用证据编号：" + "、".join(str(x) for x in a["evidence_ids"]))
        for c in (a.get("evidence_chain") or [])[:12]:
            if isinstance(c, dict):
                lines.append(f"  - {c.get('claim') or ''} [{c.get('kind') or 'fact'}] "
                             f"引用 {', '.join(c.get('evidence_ids') or []) or '未引用'}")
        if a.get("evidence_expired_offers"):
            lines.append("过期优惠（不得沿用）："
                         + "；".join(str(x.get("expires_on")) for x in a["evidence_expired_offers"]))
        if a.get("legacy_unverified"):
            lines.append("注意：旧数据无证据 ID，标记为 legacy_unverified，不自动补成已验证。")
    return "\n".join(lines) + "\n"


def _json_bytes(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _slug(name: str, fallback: str = "material") -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", (name or "").strip())[:48].strip("_")
    return s or fallback


def _zip_image(z: zipfile.ZipFile, base: str, filename: str, idx: int, meta: dict | None = None):
    path = safe_image_path(filename)
    if not path:
        return False
    meta = meta or {}
    size = _slug(str(meta.get("size") or ""), "")
    placement = _slug(str(meta.get("placement") or ""), "")
    stem = "_".join(x for x in [f"{idx:02d}", size, placement] if x) or f"{idx:02d}"
    ext = os.path.splitext(filename)[1].lower() or ".png"
    arc = f"{base}图片/{stem}{ext}"
    z.write(path, arc)
    return True


def infer_meta(filename: str) -> dict:
    """没传元数据时，从 media_<platform>_<size>_<uuid>_<hash>.png 里推断尺寸。"""
    m = re.search(r"_(\d{2,5}x\d{2,5})_", str(filename or ""))
    return {"size": m.group(1) if m else "", "placement": ""}


def build_files_zip(files: list[str], metas: list[dict] | None = None,
                    label: str = "推广图片") -> io.BytesIO:
    """打包任意一组图片文件名（供「素材创作」一键打包全部 / 打包所选）。"""
    metas = metas or []
    buf = io.BytesIO()
    used: set[str] = set()
    packed, missing = [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, f in enumerate(files, 1):
            m = metas[i - 1] if i - 1 < len(metas) else None
            if not isinstance(m, dict) or not m:
                m = infer_meta(f)
            path = safe_image_path(f)
            if not path:
                missing.append(f)
                continue
            size = _slug(str(m.get("size") or ""), "")
            placement = _slug(str(m.get("placement") or ""), "")
            stem = "_".join(x for x in [f"{i:02d}", size, placement] if x) or f"{i:02d}"
            ext = os.path.splitext(f)[1].lower() or ".png"
            arc = f"{label}/{stem}{ext}"
            while arc in used:
                arc = f"{label}/{stem}_{len(used)}{ext}"
            used.add(arc)
            z.write(path, arc)
            packed.append({"file": f, "size": m.get("size", ""),
                           "placement": m.get("placement", ""), "path_in_zip": arc})
        from media_platforms import SPEC_VERSION, SPEC_SOURCE, SPEC_DISCLAIMER
        z.writestr(f"{label}/清单.json", _json_bytes({
            "label": label, "count": len(packed), "missing": missing, "images": packed,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "spec_version": SPEC_VERSION,
            "spec_source": SPEC_SOURCE,
            "spec_note": (SPEC_DISCLAIMER +
                          " 适用广告产品与资产角色见「素材历史 → 导出」的生成信息.json。"),
            "composition_note": ("V4.42 / F06：逐图构图模式、请求 / 返回尺寸与裁切参数见"
                                 "「素材创作」图片元数据与历史生成信息.json"),
            "retention_policy": ("V4.42 / F12：完整素材为不可变记录，按 history_id 分页查询"
                                 " /api/creative-assets；本 ZIP 仅含当前展示缓存中的图片"),
        }))
    buf.seek(0)
    return buf


# ----------------------------- B5：交付增强（ad_copy.csv + delivery_notes.md） -----------------------------

def _flat(v) -> str:
    """把字段值规整为单行字符串（列表用 / 连接）。"""
    if v is None:
        return ""
    if isinstance(v, list):
        return " / ".join(str(x) for x in v if x not in (None, ""))
    return str(v)


def _copy_rows(copy_json: dict, default_platform: str = "-") -> list:
    """从 copy_json 提取多平台文案行：平台 / 版位 / 标题 / 副标题 / 行动号召 / 品牌。

    优先取 platform_copies（B3 多平台主文案），再补充 copy_variants（出图组合），
    最后回退顶层 fields（单平台）。
    """
    c = copy_json or {}
    rows = []
    pc = c.get("platform_copies")
    if isinstance(pc, dict):
        for plat, cv in pc.items():
            cv = cv if isinstance(cv, dict) else {}
            f = cv.get("fields") or {}
            rows.append({
                "platform": plat,
                "label": "",
                "headline": _flat(f.get("headline")),
                "sub": _flat(f.get("sub")),
                "cta": _flat(f.get("cta")),
                "brand": _flat(cv.get("brand") or f.get("brand")),
            })
    vs = c.get("copy_variants") or []
    if isinstance(vs, list):
        for v in vs:
            if not isinstance(v, dict):
                continue
            rows.append({
                "platform": "组合",
                "label": _flat(v.get("label")),
                "headline": _flat(v.get("headline")),
                "sub": _flat(v.get("sub")),
                "cta": _flat(v.get("cta")),
                "brand": _flat(v.get("brand")),
            })
    if not rows and isinstance(c.get("fields"), dict):
        f = c["fields"]
        rows.append({
            "platform": default_platform,
            "label": "",
            "headline": _flat(f.get("headline")),
            "sub": _flat(f.get("sub")),
            "cta": _flat(f.get("cta")),
            "brand": _flat(c.get("brand") or f.get("brand")),
        })
    return rows


def _write_copy_csv(z: zipfile.ZipFile, base: str, rows: list) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["平台", "版位", "标题", "副标题", "行动号召", "品牌"])
    for r in rows:
        w.writerow([r["platform"], r["label"], r["headline"], r["sub"], r["cta"], r["brand"]])
    # 加 BOM 以便 Excel 正确识别 UTF-8
    z.writestr(f"{base}ad_copy.csv", "\ufeff" + buf.getvalue())


def _delivery_notes(row) -> str:
    """面向广告主 / 渠道的结构化交付说明：来源、模型、各平台文案、素材清单、引用追溯。"""
    a = row.analysis_json or {}
    snap = a.get("snapshot") or {}
    mi = a.get("model_info") or {}
    rows = _copy_rows(row.copy_json or {}, row.platform or "-")
    src = snap.get("source") or "—"
    if snap.get("fetched_at"):
        src += f"（{snap.get('fetched_at')} 抓取）"
    if snap.get("fetch_quality"):
        src += f"，质量 {snap.get('fetch_quality')}"
    lines = [
        "# 创意素材交付说明",
        "",
        f"- 来源落地页：{row.url or '—'}",
        f"- 产品/品牌：{snap.get('title') or row.title or '—'}",
        f"- 数据来源：{src}",
        f"- 分析模型：{mi.get('provider') or '—'}/{mi.get('model') or '—'}",
        f"- 生成语言：{row.lang or '—'}，平台：{row.platform or '—'}",
    ]
    lines += ["", "## 各平台文案"]
    if rows:
        for r in rows:
            tag = f"**{r['platform']}**"
            if r["label"]:
                tag += f" / {r['label']}"
            lines.append(f"- {tag}：{r['headline']}｜{r['sub']}｜CTA {r['cta']}｜品牌 {r['brand']}")
    else:
        lines.append("（无文案记录）")
    imgs = row.images_json if isinstance(row.images_json, list) else []
    lines += ["", "## 素材清单"]
    if imgs:
        for i, im in enumerate(imgs, 1):
            meta = im if isinstance(im, dict) else {}
            f = meta.get("file") or os.path.basename(str(meta.get("url") or ""))
            sz = meta.get("size") or ""
            lines.append(f"{i}. {f}（{meta.get('placement') or '推广素材'}{('，' + sz) if sz else ''}）")
    else:
        lines.append("（无素材记录）")
    brands = sorted({r["brand"] for r in rows if r["brand"]})
    lines += ["", "## 引用与复用"]
    lines.append("- 本次使用的参考图与产品已沉淀至「素材库」，可在创意工作台「从素材库引用 / 复用产品」一键复用（B4）。")
    if brands:
        lines.append(f"- 涉及品牌：{'、'.join(brands)}")
    lines += ["", "> 注：内部整理规则与尺寸为系统参考，正式投放前须按平台官方文档复核。"]
    return "\n".join(lines) + "\n"


def build_history_zip(rows: list, multi: bool = False) -> io.BytesIO:
    """打包一条或多条历史：图片 + 广告文案 + 落地页分析 + 生成信息 + B5 交付物。"""
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, row in enumerate(rows, 1):
            base = f"{n:02d}_{_slug(row.title, 'material')}/" if multi else ""
            images = row.images_json if isinstance(row.images_json, list) else []
            packed, missing = 0, []
            for i, im in enumerate(images, 1):
                meta = im if isinstance(im, dict) else {}
                f = meta.get("file") or os.path.basename(str(meta.get("url") or ""))
                if _zip_image(z, base, f, i, meta):
                    packed += 1
                elif f:
                    missing.append(f)
            # B5：交付说明（无论是否含文案都生成，便于只出图的历史也能交付）
            z.writestr(f"{base}delivery_notes.md", _delivery_notes(row))
            if row.copy_json:
                z.writestr(f"{base}广告文案.txt", copy_as_text(row))
                z.writestr(f"{base}广告文案.json", _json_bytes(row.copy_json))
                # B5：结构化交付物（ad_copy.csv + delivery_notes.md 已在上方写入）
                _write_copy_csv(z, base, _copy_rows(row.copy_json, row.platform or "-"))
            if row.analysis_json:
                z.writestr(f"{base}落地页分析.txt", analysis_as_text(row))
                z.writestr(f"{base}落地页分析.json", _json_bytes(row.analysis_json))
            # V4.40 / F08：导出标记适用广告产品 / 资产角色 / 规则版本 / 批次 id
            tag = lambda k: list(dict.fromkeys(
                str(im.get(k) or "").strip() for im in images
                if isinstance(im, dict) and str(im.get(k) or "").strip()))
            z.writestr(f"{base}生成信息.json", _json_bytes({
                "id": row.id, "title": row.title, "url": row.url,
                "platform": row.platform, "lang": row.lang,
                "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
                "image_count": row.image_count, "packed_images": packed,
                "missing_files": missing,
                "style_opts": row.style_opts_json or {},
                "image_model": row.image_model_json or {},
                "note": row.note or "",
                "owner": row.owner_name or "",
                "ad_products": tag("ad_product"),
                "asset_roles": tag("asset_role"),
                "spec_versions": tag("spec_version"),
                "batch_ids": tag("batch_id"),
                # V4.41：概念 / 版式 / 配置快照与逐图提示词哈希一并归档
                "concept_ids": tag("concept_id"),
                "layouts": tag("layout"),
                "creative_config_ids": tag("creative_config_id"),
                "prompt_hashes": tag("prompt_hash"),
                "creative_config": ((row.style_opts_json or {}).get("creative_config")
                                    if isinstance(row.style_opts_json, dict) else None),
                "creative_note": "配置快照记录当时实际生效的预设，后续修改不覆盖历史",
                # V4.42 / F06：构图 / 尺寸能力；F12：服务端任务、不可变归档与保留策略
                "composition_modes": list(dict.fromkeys(
                    str((im.get("composition") or {}).get("mode") or "").strip()
                    for im in images if isinstance(im, dict)
                    and (im.get("composition") or {}).get("mode"))),
                "request_sizes": [im.get("request_size") for im in images
                                  if isinstance(im, dict) and im.get("request_size")][:24],
                "returned_sizes": [im.get("returned_size") for im in images
                                   if isinstance(im, dict) and im.get("returned_size")][:24],
                "composition_note": ("尺寸能力以官方文档与受控测试为准；未核验比例由渲染端"
                                     "扩图或主体保护处理，逐图裁切参数见图片元数据"),
                "job_ids": tag("job_id"),
                "display_cache_limit": 80,
                "retention_policy": ("完整素材保存在不可变 creative_assets 记录中，不自动截断；"
                                     "按 history_id 分页查询 /api/creative-assets 可读取早期素材"),
                "evidence": {
                    "gate": (row.analysis_json or {}).get("evidence_gate") or "—",
                    "coverage_count": len((row.analysis_json or {}).get("evidence_coverage") or []),
                    "source_chars": (row.analysis_json or {}).get("evidence_source_chars") or 0,
                    "dropped_chars": (row.analysis_json or {}).get("evidence_dropped_chars") or 0,
                    "facts": (row.analysis_json or {}).get("facts") or [],
                    "gaps": (row.analysis_json or {}).get("gaps") or [],
                    "legacy_unverified": bool((row.analysis_json or {}).get("legacy_unverified")),
                },
                "spec_note": "内部整理规则，正式投放前须按平台官方文档复核",
            }))
            manifest.append({"id": row.id, "title": row.title, "folder": base or ".",
                             "images": packed})
        if multi:
            z.writestr("历史清单.json", _json_bytes({
                "count": len(rows), "items": manifest,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }))
    buf.seek(0)
    return buf


def cleanup_orphan_files(db, targets: set[str]) -> int:
    """清理已删除历史引用的磁盘图片。

    **调用时机**：必须在 DB 记录删除并 commit **之后**调用。此时库里剩下的都是
    仍需保留的记录，凡是被它们引用的文件一律跳过，避免误删共享图片。
    传入 targets（待删记录引用过的纯文件名集合），避免 ORM 对象 commit 后过期。
    """
    from models import CreationHistory

    referenced: set[str] = set()
    for r in db.query(CreationHistory).all():
        referenced.update(image_files_of(r))
    deleted = 0
    for f in targets - referenced:
        p = safe_image_path(f)
        if p:
            try:
                os.remove(p)
                deleted += 1
            except OSError:
                pass
    return deleted
