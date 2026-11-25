# -*- coding: utf-8 -*-
"""V4.137：全系统时间口径统一。

约定：
  1. **存储**：数据库一律 UTC（models.utcnow / datetime.utcnow），SQLite 取回为 naive UTC；
  2. **展示**：面向用户的时间一律显式东八区（Asia/Shanghai, UTC+8），
     不依赖运行机器的本地时区，避免部署到 UTC 服务器后整体偏移 8 小时；
  3. **调度钟点**：用户配置的「每天几点执行」按北京时间解释，
     但仍返回 naive datetime，以便与 SystemState 水位字符串直接比较（aware/naive 混用会抛异常）。

前端统一工具在 frontend/src/datetime.ts：无时区后缀按 UTC 解析，展示强制 Asia/Shanghai。
"""
from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def beijing_now() -> datetime:
    """带 +08:00 时区的当前北京时间，用于下发到前端的时间戳。"""
    return datetime.now(BEIJING_TZ)


def beijing_naive_now() -> datetime:
    """钟点为北京时间、但不带 tzinfo 的 datetime。

    仅用于与用户配置的小时比较、以及 SystemState 里 ISO 字符串水位 / 锁的比较，
    避免 aware 与 naive 直接相减报错。绝不用于写入数据库的时间列（那些仍写 UTC）。
    """
    return beijing_now().replace(tzinfo=None)


def beijing_display() -> str:
    """版本通知等直接展示给用户的时间文本：YYYY-MM-DD HH:MM（北京时间）。"""
    return beijing_now().strftime("%Y-%m-%d %H:%M")


def beijing_iso() -> str:
    """带 +08:00 的 ISO 时间戳，供前端按统一工具解析。"""
    return beijing_now().isoformat(timespec="seconds")
