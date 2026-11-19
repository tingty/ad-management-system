"""V4.104 / 方案E：系统级布尔配置（持久化到 SystemState KV）。

复用现有 ``models.SystemState``（key/value 文本），不新建表、不加列。
读取端在行不存在时返回默认值——因此「质检开关」无需 seed 即天然默认打开。
"""
from __future__ import annotations

IMAGE_QUALITY_AUDIT_ENABLED = "image_quality_audit_enabled"


def get_bool(db, key: str, default: bool = True) -> bool:
    """读布尔配置；缺行 / 空值 → default（默认打开）。"""
    try:
        from models import SystemState
        row = db.query(SystemState).filter_by(key=key).first()
        if not row or not (row.value or "").strip():
            return default
        return str(row.value).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return default


def set_bool(db, key: str, value: bool) -> None:
    """写布尔配置（upsert）；由调用方负责 commit。"""
    from models import SystemState
    row = db.query(SystemState).filter_by(key=key).first()
    if not row:
        row = SystemState(key=key, value="")
        db.add(row)
    row.value = "1" if value else "0"
