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
        lines += ["", "【图片使用的文案组合（按版位轮换）】"]
        for i, v in enumerate(vs[:40], 1):
            if isinstance(v, dict):
                lines.append(f"- {v.get('label') or f'组合 {i}'}："
                             f"{v.get('headline') or '（无标题）'} | "
                             f"{v.get('sub') or '（无副标）'} | "
                             f"{v.get('cta') or '（无 CTA）'}")
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
        z.writestr(f"{label}/清单.json", _json_bytes({
            "label": label, "count": len(packed), "missing": missing, "images": packed,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }))
    buf.seek(0)
    return buf


def build_history_zip(rows: list, multi: bool = False) -> io.BytesIO:
    """打包一条或多条历史：图片 + 广告文案 + 落地页分析 + 生成信息。"""
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
            if row.copy_json:
                z.writestr(f"{base}广告文案.txt", copy_as_text(row))
                z.writestr(f"{base}广告文案.json", _json_bytes(row.copy_json))
            if row.analysis_json:
                z.writestr(f"{base}落地页分析.txt", analysis_as_text(row))
                z.writestr(f"{base}落地页分析.json", _json_bytes(row.analysis_json))
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
