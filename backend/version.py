"""系统版本单一来源（V4.43）。

只保存版本号常量，不依赖 FastAPI / 数据库，因而可以同时被 main.py、
release_notes.py 和发版脚本安全引用，不产生循环导入。

约定：
- `APP_VERSION` 是运行时权威版本（FastAPI app.version、健康检查、版本通知锚点）。
- `release_tag()` 把它映射为 CHANGELOG 的版本段落号，例如 4.43.0 → V4.43。
- 每次系统更新只需改这里；版本通知会自动以该版本为准同步，未写 CHANGELOG
  时也会生成一条明确标注「自动生成」的兜底通知，绝不停留在旧版本。
"""
from __future__ import annotations

import re

APP_VERSION = "4.56.0"

#: V4.46 / D5–D6：自动创作「策划 + 计划 + 编排」新路径的灰度开关。
#: 默认对内部工作区开启；回滚时只需改为 False，新入口即关闭，但资产 / 计划 / 任务记录保留，
#: 不删除数据库列来回滚（文档「迁移与向后兼容」）。
ENABLE_AUTO_CREATION_PLAN = True



def release_tag(version: str | None = None) -> str:
    """4.43.0 → V4.43；带修订号时保留第三位，例如 4.43.2 → V4.43.2。"""
    parts = [int(x) for x in re.findall(r"\d+", version or APP_VERSION)][:3]
    while len(parts) < 2:
        parts.append(0)
    if len(parts) > 2 and parts[2]:
        return "V%d.%d.%d" % tuple(parts)
    return "V%d.%d" % (parts[0], parts[1])
