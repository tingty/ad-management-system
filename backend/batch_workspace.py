"""V4.40 / F11：推广图片批次的临时文件工作区。

旧实现 `_cleanup_ai_bgs()` 用 `glob("_mabg_*.png")` / `glob("_mlogo_*.png")`
删除 uploads 目录下**所有**匹配的临时底图和 Logo。两批并发出图时，先结束的一批会把
另一批还在使用的背景 / Logo 一起删掉；被删的那张图随后可能读到空路径并静默回退模板。

本模块把「批次」变成一等公民：

- 每批拥有独立目录 `<UPLOAD_DIR>/_mabatch_<batch_id>/`，所有临时底图 / 下载 Logo 都写在这里；
- 批次自己维护文件清单，`cleanup()` **只删自己目录里的文件**，绝不扫描或删除其它批次；
- `cleanup_stale()` 只处理超过 TTL 的 `_mabatch_*` 遗留目录（进程崩溃 / 超时遗留），
  TTL 默认 1 小时，远大于单任务超时，运行中的批次不会被误清；
- 正式产物 PNG 仍直接写 UPLOAD_DIR，不随批次清理，避免影响「素材历史」的下载。

注意：这里只处理本项目 uploads 下带固定前缀的临时目录，不会递归删除用户目录。
"""
from __future__ import annotations

import os
import time
import uuid

BATCH_PREFIX = "_mabatch_"
STALE_TTL_SECONDS = int(os.getenv("AD_BATCH_STALE_TTL", "3600"))


def _inside(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(parent)]) == os.path.abspath(parent)
    except (ValueError, OSError):
        return False


class BatchWorkspace:
    """一个批次一个目录 + 一份自有文件清单。"""

    def __init__(self, root: str, batch_id: str = "", ttl: int = STALE_TTL_SECONDS):
        self.root = os.path.abspath(root)
        self.batch_id = (batch_id or uuid.uuid4().hex[:16]).replace("/", "_")
        self.name = f"{BATCH_PREFIX}{self.batch_id}"
        self.dir = os.path.join(self.root, self.name)
        os.makedirs(self.dir, exist_ok=True)
        self.ttl = max(60, int(ttl))
        self._files: set[str] = set()

    def temp_name(self, kind: str, suffix: str = ".png") -> str:
        """返回一个相对 root 的临时文件路径，并登记为本批次自有文件。

        供应商 `ImageProvider.generate(..., filename)` 内部会做
        `os.path.join(UPLOAD_DIR, filename)`，因此这里返回带批次目录的相对路径即可，
        无需改动各供应商实现。
        """
        safe_kind = "".join(ch for ch in str(kind) if ch.isalnum() or ch in "-_")[:24] or "tmp"
        suffix = "." + str(suffix).lstrip(".").lower()
        fn = f"_{safe_kind}_{uuid.uuid4().hex[:16]}{suffix}"
        full = os.path.join(self.dir, fn)
        self._files.add(full)
        return os.path.join(self.name, fn)

    def register(self, path: str) -> None:
        """登记外部（例如远程 Logo 下载）写入本批次目录的文件。"""
        if path and _inside(path, self.dir):
            self._files.add(os.path.abspath(path))

    def own_files(self) -> list[str]:
        return sorted(self._files)

    def cleanup(self) -> dict:
        """只清理本批次目录；返回可写入日志的统计，失败不向外抛。"""
        removed = 0
        failed: list[str] = []
        for p in list(self._files):
            try:
                os.remove(p)
                removed += 1
            except FileNotFoundError:
                pass
            except OSError:
                failed.append(os.path.basename(p))
        self._files.clear()
        try:
            with os.scandir(self.dir) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            os.remove(entry.path)
                            removed += 1
                        except OSError:
                            failed.append(entry.name)
            os.rmdir(self.dir)
        except OSError:
            pass
        return {"batch_id": self.batch_id, "removed": removed, "failed": failed}

    @classmethod
    def cleanup_stale(cls, root: str, ttl: int = STALE_TTL_SECONDS) -> dict:
        """清理超时遗留的批次目录（只认固定前缀的目录，不动其它文件）。

        超时或进程被杀时 `cleanup()` 没有机会执行；下一次出图前调用一次即可回收。
        目录 mtime 会随文件写入更新，因此运行中的批次不会被判定为遗留。
        """
        root = os.path.abspath(root)
        cutoff = time.time() - max(60, int(ttl))
        removed_dirs: list[str] = []
        removed_files = 0
        try:
            entries = list(os.scandir(root))
        except OSError:
            return {"dirs": [], "files": 0}
        for entry in entries:
            if not entry.name.startswith(BATCH_PREFIX) or not entry.is_dir(follow_symlinks=False):
                continue
            try:
                if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                    continue
            except OSError:
                continue
            try:
                with os.scandir(entry.path) as inner:
                    for f in inner:
                        if f.is_file(follow_symlinks=False):
                            try:
                                os.remove(f.path)
                                removed_files += 1
                            except OSError:
                                pass
                os.rmdir(entry.path)
                removed_dirs.append(entry.name)
            except OSError:
                pass
        return {"dirs": removed_dirs, "files": removed_files}
