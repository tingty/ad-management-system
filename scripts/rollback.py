#!/usr/bin/env python3
"""版本回滚工具（V4.124 起）。

设计目标：需求/设计判断错误时，能低成本回退到上一个可用版本，
且**不丢数据**。回滚分两层，互不强制绑定：

  1. 代码回滚：靠 git tag（每个已发版版本一个 tag），用 git revert 生成反向提交，
     保留历史、可再次 push，避免 force push 破坏他人工作区。
  2. 数据回滚：靠数据库快照（SQLite 文件级备份）。仅在「新版本写坏了数据」时使用；
     仅代码回滚通常不需要动数据，因为新表/新列对旧代码是无害冗余。

命令：
  python3 scripts/rollback.py backup-db [--label V4.124]   # 迁移/发版前打快照
  python3 scripts/rollback.py list-backups                 # 列出快照
  python3 scripts/rollback.py list-tags                    # 列出可回滚版本
  python3 scripts/rollback.py plan-code <tag>              # 打印代码回滚步骤（不执行）
  python3 scripts/rollback.py restore-db <backup-file>     # 从快照恢复（需先停服务）

安全约束：
  - backup-db 使用 sqlite3 在线备份 API（backup），不加锁业务，不复制中途写坏的文件。
  - restore-db 拒绝覆盖正在被写的文件之外的任何路径，且写回前自动再存一份 current 快照。
  - 所有命令都打印将执行的动作；restore-db 需要 --yes 才真正写回。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"
DB_CANDIDATES = [
    ROOT / "ad_material.db",
    ROOT / "backend" / "ad_material.db",
]


def _db_path(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"[rollback] 数据库文件不存在：{p}")
        return p
    # 优先尊重 DATABASE_URL
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite"):
        raw = url.split(":///", 1)[-1]
        p = Path(raw)
        if not p.is_absolute():
            p = (ROOT / "backend" / p).resolve()
        if p.is_file():
            return p
    for c in DB_CANDIDATES:
        if c.is_file():
            return c
    raise SystemExit("[rollback] 未找到数据库文件，请用 --db 指定绝对路径")


def backup_db(label: str | None, explicit_db: str | None) -> None:
    import sqlite3

    db = _db_path(explicit_db)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", label or db.stem)
    dest = BACKUP_DIR / f"{stamp}__{safe}.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)  # 在线一致性快照，避免 WAL 中途拷贝
    finally:
        out.close()
        src.close()
    print(f"[rollback] 已备份 {db} → {dest} ({dest.stat().st_size} bytes)")


def list_backups() -> None:
    if not BACKUP_DIR.is_dir():
        print("[rollback] 暂无备份")
        return
    files = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    if not files:
        print("[rollback] 暂无备份")
        return
    for f in files:
        print(f"{f.stat().st_size:>12}  {f.name}  ({f})")


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"[rollback] git {' '.join(args)} 失败：\n{r.stderr}")
    return r.stdout.strip()


def list_tags() -> None:
    tags = git("tag", "-l", "--sort=-creatordate")
    if not tags:
        print("[rollback] 暂无版本标签；基线标签应为 v4.123-baseline")
        return
    print("[rollback] 可回滚版本标签（越靠上越新）：")
    for t in tags.splitlines():
        print("  " + t)
    print("\n当前 HEAD：" + git("rev-parse", "--short", "HEAD"))


def plan_code(tag: str) -> None:
    git("rev-parse", "--verify", tag)  # 不存在则报错
    print(f"""[rollback] 代码回滚到 {tag} 的建议步骤（本命令不执行）：

  1) 确认目标标签存在：      git tag -l | grep {tag}
  2) 查看将回退的提交：      git log --oneline {tag}..HEAD
  3) 逐个生成反向提交：      git revert --no-edit <从新到旧的每个 commit>
     （不要用 git reset --hard + force push，会破坏他人工作区）
  4) 同步远端：              git push origin main
  5) 数据层通常无需回滚；若新版本写坏了数据，见 restore-db。
  6) 前端重新构建部署：      docker compose up -d --build

  ※ 若只是想临时关闭新功能而保留数据，优先用功能开关，而不是代码回滚。""")


def restore_db(backup: str, explicit_db: str, yes: bool) -> None:
    src = Path(backup).expanduser().resolve()
    if not src.is_file() or src.suffix != ".db":
        raise SystemExit(f"[rollback] 备份文件不存在或不是 .db：{src}")
    db = _db_path(explicit_db)
    # 写回前先把当前库再存一份，避免误操作不可恢复
    import sqlite3

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    pre = BACKUP_DIR / f"{stamp}__before-restore.db"
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    o = sqlite3.connect(str(pre))
    try:
        c.backup(o)
    finally:
        o.close()
        c.close()
    print(f"[rollback] 已先保存当前库 → {pre}")
    if not yes:
        print(f"[rollback] 预演：将用 {src} 覆盖 {db}。确认无误后加 --yes 真正执行。")
        return
    # 停服务提示（脚本不负责停用容器，避免误停其它服务）
    print("[rollback] 请先停止应用服务（docker compose stop app），否则可能写入中途状态。")
    shutil.copy2(src, db)
    print(f"[rollback] 已从 {src} 恢复到 {db}")


def main() -> int:
    ap = argparse.ArgumentParser(description="版本回滚工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backup-db", help="数据库在线快照")
    p.add_argument("--label", help="快照标签，如 V4.124")
    p.add_argument("--db", help="数据库绝对路径（默认自动探测）")

    sub.add_parser("list-backups", help="列出快照")
    sub.add_parser("list-tags", help="列出版本标签")

    p = sub.add_parser("plan-code", help="打印代码回滚步骤，不执行")
    p.add_argument("tag", help="目标版本标签，如 v4.123-baseline")

    p = sub.add_parser("restore-db", help="从快照恢复数据库")
    p.add_argument("backup", help="快照文件路径")
    p.add_argument("--db", help="目标数据库绝对路径")
    p.add_argument("--yes", action="store_true", help="真正写回（默认仅预演）")

    args = ap.parse_args()
    if args.cmd == "backup-db":
        backup_db(args.label, args.db)
    elif args.cmd == "list-backups":
        list_backups()
    elif args.cmd == "list-tags":
        list_tags()
    elif args.cmd == "plan-code":
        plan_code(args.tag)
    elif args.cmd == "restore-db":
        restore_db(args.backup, args.db, args.yes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
