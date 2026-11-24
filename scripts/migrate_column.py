#!/usr/bin/env python3
"""保障三 · 版本化列迁移 CLI（V4.127 起）。

用途：语义确需变更时才改物理列名。只改「叫法」请改 api_field_label 展示名，不动列。

命令：
  python3 scripts/migrate_column.py audit <old>                 # 只看代码里还有哪些旧名引用
  python3 scripts/migrate_column.py rename <old> <new>          # 预演：备份 + 检查，不写库
  python3 scripts/migrate_column.py rename <old> <new> --yes    # 真正执行（先自动备份）

rename 一次同步四处：物理列 → api_field_map.target_field → api_field_label
→ v_api_order_final 视图 → 代码引用审计（有残留则拒绝，除非 --force）。
迁移前自动调 scripts/rollback.py backup-db 做在线快照，可回滚。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))


def _backup(label: str) -> None:
    import rollback
    try:
        rollback.backup_db(label, None)
    except SystemExit as e:
        print(f"[migrate] 备份失败，终止迁移：{e}", file=sys.stderr)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="版本化列迁移工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit", help="扫描旧列名的代码引用")
    p.add_argument("old")

    p = sub.add_parser("rename", help="改列名并同步四处")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--table", default="api_unified_fact")
    p.add_argument("--yes", action="store_true", help="真正写库（默认仅预演）")
    p.add_argument("--force", action="store_true", help="代码仍有旧名引用时仍执行（需人工确认）")

    args = ap.parse_args()

    import migrations

    if args.cmd == "audit":
        hits = migrations.audit_column_references(args.old)
        print(f"[migrate] {args.old} 的代码引用 {len(hits)} 处：")
        for h in hits:
            print("  " + h)
        return 0

    print(f"[migrate] 预演改列：{args.table}.{args.old} → {args.new}")
    hits = migrations.audit_column_references(args.old)
    if hits:
        print(f"[migrate] 代码引用 {len(hits)} 处（需同步或确认）：")
        for h in hits[:20]:
            print("  " + h)
    if not args.yes:
        print("[migrate] 预演结束，未写库。确认后加 --yes 执行（将先自动备份数据库）。")
        return 0

    _backup(f"before-rename-{args.old}-to-{args.new}")
    result = migrations.rename_column(args.old, args.new, table=args.table, force=args.force)
    print(f"[migrate] 已完成：{result['table']}.{result['old']} → {result['new']}")
    print("[migrate] 映射表 / 展示名 / 视图已同步；迁移版本已记入 schema_migrations。")
    print("[migrate] 如写坏数据：python3 scripts/rollback.py list-backups 后用 restore-db 恢复。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
