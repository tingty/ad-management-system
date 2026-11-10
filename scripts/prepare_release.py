#!/usr/bin/env python3
"""发版前整理 / 发布版本通知（V4.37）。

单一数据源仍是根目录的 CHANGELOG.md；本脚本负责把「本次优化和更改过的功能与模块」
归纳成一条结构化版本通知，并在同步 git 之前校验它是否完整。

用法：
  # 1) 先看本次改动涉及哪些模块，生成版本通知骨架（打印，不写文件）
  python3 scripts/prepare_release.py --draft

  # 2) 把骨架追加到 CHANGELOG.md（随后手工补全摘要 / 改动 / 影响 / 验证）
  python3 scripts/prepare_release.py --write --version V4.38 --title "版本主题"

  # 3) 同步 git 前校验（pre-push 钩子自动调用）
  python3 scripts/prepare_release.py --check
  python3 scripts/prepare_release.py --check --range origin/main..HEAD --strict

环境变量：
  RELEASE_DIFF_RANGE  同 --range，指定要分析的 git 区间
  SKIP_RELEASE_CHECK  由 pre-push 钩子处理；本脚本自身不读取
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
sys.path.insert(0, str(ROOT / "backend"))
import release_notes  # noqa: E402  （仅依赖 os / re，不会拉起 FastAPI）

# ---------------------------------------------------------------------------
# 改动文件 → 涉及模块：发版时自动归纳，避免漏写模块总结
# ---------------------------------------------------------------------------
MODULE_RULES: list[tuple[str, str]] = [
    ("frontend/src/App.tsx", "前端与菜单"),
    ("frontend/src/api.ts", "前端与菜单"),
    ("frontend/src/styles.css", "前端与菜单"),
    ("frontend/src/pages/MaterialCreation.tsx", "素材创作平台"),
    ("frontend/src/pages/MediaAdStudio.tsx", "素材创作平台"),
    ("frontend/src/pages/MaterialHistory.tsx", "素材创作平台"),
    ("frontend/src/pages/MaterialPromptLibrary.tsx", "素材提示词"),
    ("frontend/src/pages/LLMSettings.tsx", "大模型配置"),
    ("frontend/src/pages/Accounts.tsx", "系统设置"),
    ("frontend/src/pages/Logs.tsx", "系统设置"),
    ("frontend/src/pages/ReleaseNotes.tsx", "新版通知"),
    ("frontend/src/pages/*", "前端与菜单"),
    ("frontend/src/*", "前端与菜单"),
    ("backend/release_notes.py", "新版通知"),
    ("backend/roadmap.py", "新版通知"),
    ("backend/industry_profiles.py", "行业适配"),
    ("backend/text_utils.py", "素材创作平台"),
    ("backend/llm_catalog.py", "大模型配置"),
    ("backend/model_health.py", "大模型配置"),
    ("backend/providers.py", "大模型配置"),
    ("backend/prompt_catalog.py", "素材提示词"),
    ("backend/presets.py", "素材提示词"),
    ("backend/media_ad.py", "素材创作平台"),
    ("backend/media_platforms.py", "素材创作平台"),
    ("backend/imaging.py", "素材创作平台"),
    ("backend/creation_history.py", "素材创作平台"),
    ("backend/routers.py", "后端接口"),
    ("backend/services.py", "后端接口"),
    ("backend/models.py", "数据模型"),
    ("backend/schemas.py", "数据模型"),
    ("backend/migrations.py", "数据模型"),
    ("backend/main.py", "系统设置"),
    ("backend/auth.py", "系统设置"),
    ("backend/requirements.txt", "部署依赖"),
    ("backend/*", "后端接口"),
    ("scripts/*", "发版流程"),
]
# 覆盖校验用的宽松关键词：版本通知里出现这些词即视为已总结该模块
COVERAGE_KEYWORDS: dict[str, str] = {
    "前端与菜单": "前端", "后端接口": "后端", "数据模型": "数据",
    "素材提示词": "提示词", "部署依赖": "部署", "发版流程": "发版",
    "系统设置": "系统设置", "大模型配置": "大模型", "新版通知": "新版通知",
    "素材创作平台": "素材创作", "行业适配": "行业", "改造追踪": "改造",
}
CODE_PREFIXES = ("frontend/src/", "backend/", "scripts/", "docs/")
MODULE_RULES.insert(0, ("docs/REMEDIATION_TRACKER.md", "改造追踪"))


def git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT)] + args,
                              capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return ""


def changed_files(diff_range: str = "") -> dict[str, str]:
    """返回 {路径: 状态}，状态取 A/M/D/R。合并工作区、暂存区与指定区间。"""
    cmds = []
    if diff_range:
        cmds.append(["diff", "--name-status", diff_range])
    else:
        cmds = [["diff", "--name-status", "HEAD"],
                ["diff", "--name-status", "--cached"],
                ["diff", "--name-status", "HEAD~1..HEAD"]]
    out: dict[str, str] = {}
    for cmd in cmds:
        for line in git(cmd).splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0][:1], parts[-1].strip()
            if not path:
                continue
            # 删除的文件不会出现在原地；保留第一次出现的新增状态优先
            if path not in out or status == "D":
                out[path] = status
    # 新文件在 commit 之前是 untracked，diff 看不到；补进来才能正确归纳模块。
    # 但指定了 git 区间（如 pre-push 钩子）时只看区间内已提交的文件，避免误判。
    if not diff_range:
        for line in git(["ls-files", "--others", "--exclude-standard"]).splitlines():
            path = line.strip()
            if path:
                out.setdefault(path, "A")
    return out


def module_of(path: str) -> str:
    for pattern, label in MODULE_RULES:
        if fnmatch.fnmatch(path, pattern):
            return label
    if path.startswith("frontend/src/"):
        return "前端"
    if path.startswith("backend/"):
        return "后端"
    return "工程 / 文档"


def modules_of(files: dict[str, str]) -> list[str]:
    mods: list[str] = []
    for path in files:
        if not path.startswith(CODE_PREFIXES):
            continue
        m = module_of(path)
        if m not in mods:
            mods.append(m)
    return mods


def code_files(files: dict[str, str]) -> list[str]:
    return [p for p in files if p.startswith(CODE_PREFIXES)]


def next_version(latest: str | None) -> str:
    if not latest:
        return "V4.38"
    m = re.match(r"V(\d+)\.(\d+)(?:\.(\d+))?", latest)
    if not m:
        return "V4.38"
    major, minor = int(m.group(1)), int(m.group(2))
    return f"V{major}.{minor + 1}"


# ---------------------------------------------------------------------------
# 生成版本通知骨架
# ---------------------------------------------------------------------------
def build_entry(version: str, title: str, modules: list[str], kinds: list[str],
                summary: str = "") -> str:
    today = date.today().isoformat()
    mod_text = "、".join(modules) if modules else "请补充涉及模块"
    kind_text = " / ".join(kinds) if kinds else "优化"
    head = [
        f"## {version} {title}",
        "",
        f"**发布日期**：{today}",
        f"**变更类型**：{kind_text}",
        f"**涉及模块**：{mod_text}",
        f"**变更摘要**：{summary or '请一句话说明本版做了什么（勿保留本占位文字）'}",
        "",
        "**本次优化与更改的功能 / 模块**",
    ]
    for m in modules or ["请补充涉及模块"]:
        head.append(f"- 【优化】{m} / 功能名：具体改动说明（勿保留本占位文字）")
    head += [
        "",
        "**影响范围**",
        "- 前端 / 后端 / 数据 / 兼容性 / 权限：请逐项说明（勿保留本占位文字）",
        "",
        "**验证**",
        "- 请填写本次实际执行的验证项与结果（勿保留本占位文字）",
        "",
        "**说明 / 默认约定**",
        "- 如有部署注意事项、默认行为或后续计划，在此补充。",
        "",
    ]
    return "\n".join(head)


def guess_kinds(files: dict[str, str]) -> list[str]:
    statuses = set(files.values())
    kinds = []
    if "A" in statuses or "R" in statuses:
        kinds.append("新增")
    if "D" in statuses:
        kinds.append("删除")
    if "M" in statuses:
        kinds.append("优化")
    return kinds or ["优化"]


# ---------------------------------------------------------------------------
# 发版前校验
# ---------------------------------------------------------------------------
TODO_MARKERS = tuple(release_notes.TODO_MARKERS)


def check(diff_range: str = "", strict: bool = False) -> int:
    errors: list[str] = []
    warns: list[str] = []
    files = changed_files(diff_range)
    notes = release_notes.get_release_notes()
    latest = notes["latest"]
    note = release_notes.latest_note()
    code = code_files(files)

    print("=" * 68)
    print("发版前版本通知校验（V4.39 · 含改造期次校验）")
    print("=" * 68)
    print(f"变更文件 {len(files)} 个，其中代码文件 {len(code)} 个")
    print(f"CHANGELOG 最新版本：{latest or '（无）'}，共 {notes['total']} 个版本")
    if code:
        print("本次改动涉及模块：" + "、".join(modules_of(files)))

    if not note:
        errors.append("CHANGELOG.md 中没有解析到任何版本段落")
    else:
        # 1) 代码改动必须同步 CHANGELOG
        if code and "CHANGELOG.md" not in files:
            errors.append("本次改动涉及代码，但 CHANGELOG.md 未同步更新；请先用 --draft/--write 整理版本通知")

        # 2) 结构化字段完整性
        body = note["body"]
        required = {
            "发布日期": bool(note["date"]),
            "变更摘要": bool(note["summary"]),
            "涉及模块": bool(note["modules"]),
            "变更类型": bool(note["change_types"]),
            "本次优化与更改的功能 / 模块": note["has_structured"],
            "影响范围": bool(note["impact"]),
            "验证": bool(note["verification"]),
        }
        for name, ok in required.items():
            if not ok:
                errors.append(f"最新版本 {note['version']} 缺少「{name}」内容")
        markers = [m for m in TODO_MARKERS if m in body]
        if markers:
            errors.append(f"最新版本仍含占位文字 {markers}，请补全后再发布")

        # 3) 改动模块是否被版本通知覆盖
        if code:
            declared = " ".join(note["modules"] + [note["summary"], note["body"]])
            missing = []
            for m in modules_of(files):
                key = COVERAGE_KEYWORDS.get(m, m.split(" / ")[0])
                if key not in declared:
                    missing.append(m)
            if missing:
                warns.append("版本通知未显式提到这些改动模块：" + "、".join(missing))

        # 4) 变更类型是否覆盖删除 / 新增
        if "删除" in guess_kinds(files) and "删除" not in note["change_types"]:
            warns.append("本次有文件删除，但「变更类型」未标注「删除」")
        if "新增" in guess_kinds(files) and not ({"新增", "发布"} & set(note["change_types"])):
            warns.append("本次有新增文件，但「变更类型」未标注「新增 / 发布」")

        # 5) V4.39 起：AI 改造「每期 3 个问题、独立发版、版本通知统一发布」
        #    校验改造期次字段与 roadmap 一致，避免做完改造却没写版本文案。
        if note.get("phase_text") or note.get("issue_ids"):
            from roadmap import PHASES, planned_issue_ids
            ids = note.get("issue_ids") or []
            if len(ids) != 3:
                errors.append(f"改造期次应包含 3 个问题，当前 {len(ids)} 个：{ids}")
            unknown = [i for i in ids if i not in planned_issue_ids()]
            if unknown:
                errors.append(f"改造期次含路线图外的问题编号：{unknown}")
            phase = next((p for p in PHASES
                          if set(ids) == {i["id"] for i in p["issues"]}), None)
            if not phase and ids:
                errors.append(f"本期问题 {ids} 不属于路线图中的同一期")
            elif phase and phase["version"] != note["version"]:
                errors.append(f"本期改造应发布为 {phase['version']}，当前版本为 {note['version']}")

    for w in warns:
        print("  [WARN] " + w)
    for e in errors:
        print("  [FAIL] " + e)

    if errors:
        print("\n校验未通过：请先整理并发布本次版本通知，再同步 git。")
        print("  python3 scripts/prepare_release.py --draft")
        return 1
    if warns and strict:
        print("\n严格模式：存在警告，拒绝发布。请补齐模块总结或用不带 --strict 的方式发布。")
        return 1
    print(f"\n校验通过：{latest} 已按结构化格式发布，可同步 git。")
    if warns:
        print(f"（{len(warns)} 条提示，不阻断发布）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="发版前整理 / 发布 / 校验版本通知")
    ap.add_argument("--check", action="store_true", help="校验最新版本通知是否完整并已随代码同步")
    ap.add_argument("--draft", action="store_true", help="打印版本通知骨架（不写文件）")
    ap.add_argument("--write", action="store_true", help="把骨架追加到 CHANGELOG.md")
    ap.add_argument("--range", default=os.getenv("RELEASE_DIFF_RANGE", ""),
                    help="分析指定 git 区间，如 origin/main..HEAD")
    ap.add_argument("--strict", action="store_true", help="校验时把警告也视为失败")
    ap.add_argument("--version", default="", help="版本号，默认在最新版本上 +1")
    ap.add_argument("--title", default="版本优化与变更", help="版本标题")
    ap.add_argument("--summary", default="", help="变更摘要（可选）")
    args = ap.parse_args()

    if args.check or (not args.draft and not args.write):
        return check(args.range, args.strict)

    files = changed_files(args.range)
    latest = release_notes.get_release_notes()["latest"]
    version = args.version or next_version(latest)
    entry = build_entry(version, args.title, modules_of(files), guess_kinds(files), args.summary)
    if args.draft:
        print(entry)
        return 0
    current = CHANGELOG.read_text(encoding="utf-8")
    sep = "\n" if current.endswith("\n") else "\n\n"
    with CHANGELOG.open("a", encoding="utf-8") as f:
        f.write(sep + entry)
    print(f"已追加版本骨架 {version} 到 {CHANGELOG}")
    print("请补全摘要、改动明细、影响范围与验证后，再执行 --check 并同步 git。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
