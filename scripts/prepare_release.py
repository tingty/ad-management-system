#!/usr/bin/env python3
"""发版前整理 / 发布 / 同步版本通知（V4.43）。

完整归档仍是根目录的 CHANGELOG.md；本脚本负责把本次改动归纳成「总结式」版本通知，
并在同步 git 前校验「系统运行版本 == CHANGELOG 最新版本」，保证每次系统更新都同步版本内容。

用法：
  # 1) 按当前系统版本自动生成一条可直接发布的总结式通知（推荐）
  python3 scripts/prepare_release.py --sync --title "版本主题" \
      --summary "一句话总结" --points "要点一|要点二|要点三"

  # 2) 先预览骨架 / 手工追加下一个版本
  python3 scripts/prepare_release.py --draft
  python3 scripts/prepare_release.py --write --version V4.44 --title "版本主题"

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
import version as _version  # noqa: E402  （系统版本单一来源，动态读取避免值拷贝）

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
    ("backend/version.py", "系统版本"),
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
    "系统版本": "系统版本",
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
                summary: str = "", points: list[str] | None = None) -> str:
    """生成可直接发布的总结式版本通知（无占位文字，供 --sync / --draft 使用）。

    V4.43：通知页只展示「版本号 + 更新要点」，因此 `**更新要点**` 是必备章节；
    「本次优化与更改 / 影响范围 / 验证」保留为完整归档，不进入页面展示。
    """
    today = date.today().isoformat()
    mods = modules or ["系统版本"]
    mod_text = "、".join(mods)
    kind_text = " / ".join(kinds) if kinds else "优化"
    sum_text = summary or (f"系统更新至 {version}，本次改动涉及 {mod_text} 等 "
                           f"{len(mods)} 个模块。")
    pts = [p.strip() for p in (points or []) if p and p.strip()]
    if not pts:
        pts = [f"{m}：相关代码与配置已更新。" for m in mods[:6]]
    head = [
        f"## {version} {title}",
        "",
        f"**发布日期**：{today}",
        f"**变更类型**：{kind_text}",
        f"**涉及模块**：{mod_text}",
        f"**变更摘要**：{sum_text}",
        "",
        "**更新要点**",
    ]
    head += [f"- {p}" for p in pts[:6]]
    head += ["", "**本次优化与更改的功能 / 模块**"]
    for m in mods:
        head.append(f"- 【优化】{m} / 版本更新：相关代码与配置已同步更新。")
    head += [
        "",
        "**影响范围**",
        f"- 前端 / 后端 / 数据 / 兼容性：本次改动涉及 {mod_text}；旧数据与旧接口保持兼容。",
        "",
        "**验证**",
        "- 系统版本与 CHANGELOG 版本一致性由发版校验强制检查；该条目由本次改动文件自动归纳。",
        "",
    ]
    return "\n".join(head)


# 生成发布数据时，剔除历史 CHANGELOG 里残留的凭据字样（如早期默认口令），
# 既避免安全扫描误报，也防止旧口令出现在对外版本通知中。
_CRED_REDACT = (
    "Tingty@123.com", "Admin@123.com", "Manager@123.com",
    "Tingty@123", "Admin@123", "Manager@123", "Editor@123",
    "Viewer@123", "admin123",
)


def _redact(text: str) -> str:
    if not text:
        return text
    for tok in sorted(_CRED_REDACT, key=len, reverse=True):
        if tok in text:
            text = text.replace(tok, "（已移除凭据）")
    return text


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
# 生成部署环境权威发布数据：backend/release_notes_data.py
# ---------------------------------------------------------------------------
def write_data_file() -> int:
    """把 CHANGELOG 全部版本整理为 `backend/release_notes_data.py`。

    该文件随代码发布，是「新版通知」接口的权威来源；即使部署环境没有
    CHANGELOG.md 或 git，也能直接展示最新版本内容。每次 --sync 都会重建，
    保证「代码更新 → 运行 --sync → 通知数据随代码入库」形成闭环。
    """
    parsed = release_notes.parse_changelog()
    if not parsed:
        print("[WARN] CHANGELOG.md 为空，跳过生成 release_notes_data.py")
        return 0
    notes = [release_notes.public_note(n) for n in parsed]
    out = ROOT / "backend" / "release_notes_data.py"
    lines = [
        "# AUTO-GENERATED by scripts/prepare_release.py --sync. 请勿手工编辑。",
        "# 版本通知接口直接读取本文件，保证部署环境（无 CHANGELOG.md / git）也能展示最新版本内容。",
        "# 如需修改通知文案，请编辑 CHANGELOG.md 后运行 python3 scripts/prepare_release.py --sync。",
        "NOTES = [",
    ]
    for n in notes:
        item = {
            "version": n.get("version"),
            "title": _redact(n.get("title") or ""),
            "date": n.get("date"),
            "summary": _redact(n.get("summary") or ""),
            "points": [_redact(p) for p in (n.get("points") or [])],
            "change_types": n.get("change_types") or [],
            "modules": n.get("modules") or [],
            "auto_generated": bool(n.get("auto_generated")),
        }
        # 用 repr 生成合法 Python 字面量（False/True/None 与中文均可正常 import）
        lines.append("    " + repr(item) + ",")
    lines.append("]")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成发布数据 {out}（{len(notes)} 个版本）")
    return 0


# ---------------------------------------------------------------------------
# 发版前校验
# ---------------------------------------------------------------------------
TODO_MARKERS = tuple(release_notes.TODO_MARKERS)


def check(diff_range: str = "", strict: bool = False) -> int:
    errors: list[str] = []
    warns: list[str] = []
    files = changed_files(diff_range)
    # 用「纯解析」结果校验，避免 get_release_notes() 的自动兜底条目掩盖漏写。
    parsed = release_notes.parse_changelog()
    note = parsed[0] if parsed else None
    latest = note["version"] if note else None
    code = code_files(files)
    expected = _version.release_tag()

    print("=" * 68)
    print("发版前版本通知校验（系统版本一致性 / 总结要点 / 结构化字段 / 模块覆盖 / 改造期次）")
    print("=" * 68)
    print(f"变更文件 {len(files)} 个，其中代码文件 {len(code)} 个")
    print(f"系统运行版本：{expected}（{_version.APP_VERSION}）")
    print(f"CHANGELOG 最新版本：{latest or '（无）'}，共 {len(parsed)} 个版本")
    try:
        import release_notes_data
        dlatest = release_notes_data.NOTES[0]["version"] if release_notes_data.NOTES else "（无）"
    except Exception:
        dlatest = "（缺失）"
    print(f"发布数据最新版本：{dlatest}")
    if code:
        print("本次改动涉及模块：" + "、".join(modules_of(files)))

    # 0) V4.43 核心：系统升版后，版本通知必须同步到同一版本号。
    #    这是「每次版本更新都同步版本内容」的强制闸门，漏写 CHANGELOG 直接拦截。
    version_changed = "backend/version.py" in files or "backend/main.py" in files
    if (code or version_changed) and latest != expected:
        errors.append(
            f"系统版本为 {expected}（{_version.APP_VERSION}），但 CHANGELOG 最新版本为 {latest or '（无）'}；"
            f"请执行 python3 scripts/prepare_release.py --sync 自动整理本次版本通知"
        )

    if not note:
        errors.append("CHANGELOG.md 中没有解析到任何版本段落")
    else:
        # 1) 部署发布数据必须与系统版本同步（新版通知接口权威来源）
        try:
            import release_notes_data
            data_notes = release_notes_data.NOTES
            data_latest = data_notes[0]["version"] if data_notes else None
        except Exception:
            data_latest = None
            data_notes = []
            warns.append("release_notes_data.py 缺失；部署环境将无法展示版本通知，请运行 --sync 生成")

        if data_latest is None:
            errors.append("发布数据 release_notes_data.py 不存在；请运行 python3 scripts/prepare_release.py --sync 生成")
        elif data_latest != expected:
            errors.append(
                f"发布数据 release_notes_data.py 最新版本为 {data_latest}，但系统版本为 {expected}；"
                f"请运行 python3 scripts/prepare_release.py --sync 同步版本通知数据"
            )
        elif expected not in {n.get("version") for n in data_notes}:
            errors.append(f"发布数据 release_notes_data.py 未包含当前版本 {expected}；请运行 --sync 重新生成")
        # 2) 代码改动必须同步 CHANGELOG
        if code and "CHANGELOG.md" not in files:
            errors.append("本次改动涉及代码，但 CHANGELOG.md 未同步更新；请先用 --sync/--write 整理版本通知")

        # 3) 结构化字段完整性（V4.43 起「更新要点」为通知页的必备内容）
        body = note["body"]
        required = {
            "发布日期": bool(note["date"]),
            "变更摘要": bool(note["summary"]),
            "涉及模块": bool(note["modules"]),
            "变更类型": bool(note["change_types"]),
            "更新要点": bool(note.get("key_points")),
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

        # 4) 改动模块是否被版本通知覆盖
        if code:
            declared = " ".join(note["modules"] + [note["summary"], note["body"]])
            missing = []
            for m in modules_of(files):
                key = COVERAGE_KEYWORDS.get(m, m.split(" / ")[0])
                if key not in declared:
                    missing.append(m)
            if missing:
                warns.append("版本通知未显式提到这些改动模块：" + "、".join(missing))

        # 5) 变更类型是否覆盖删除 / 新增
        if "删除" in guess_kinds(files) and "删除" not in note["change_types"]:
            warns.append("本次有文件删除，但「变更类型」未标注「删除」")
        if "新增" in guess_kinds(files) and not ({"新增", "发布"} & set(note["change_types"])):
            warns.append("本次有新增文件，但「变更类型」未标注「新增 / 发布」")

        # 6) V4.39 起：AI 改造「每期 3 个问题、独立发版、版本通知统一发布」
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
    ap.add_argument("--sync", action="store_true",
                    help="按当前系统运行版本自动生成总结式版本通知并追加到 CHANGELOG.md")
    ap.add_argument("--range", default=os.getenv("RELEASE_DIFF_RANGE", ""),
                    help="分析指定 git 区间，如 origin/main..HEAD")
    ap.add_argument("--strict", action="store_true", help="校验时把警告也视为失败")
    ap.add_argument("--version", default="", help="版本号；--sync 默认取当前系统版本，其余默认在最新版本上 +1")
    ap.add_argument("--title", default="版本优化与变更", help="版本标题")
    ap.add_argument("--summary", default="", help="变更摘要（可选）")
    ap.add_argument("--points", default="", help="更新要点，用 | 分隔；不填则按本次改动模块自动归纳")
    args = ap.parse_args()

    if args.check or (not args.draft and not args.write and not args.sync):
        return check(args.range, args.strict)

    files = changed_files(args.range)
    parsed = release_notes.parse_changelog()
    latest = parsed[0]["version"] if parsed else None
    version = args.version or (_version.release_tag() if args.sync else next_version(latest))
    points = [p.strip() for p in args.points.split("|") if p.strip()]

    if args.sync and any(n["version"] == version for n in parsed):
        print(f"{version} 的版本通知已存在，跳过 CHANGELOG 自动生成；如需补充内容请直接编辑 CHANGELOG.md。")
    else:
        entry = build_entry(version, args.title, modules_of(files), guess_kinds(files),
                            args.summary, points)
        if args.draft:
            print(entry)
            return 0
        current = CHANGELOG.read_text(encoding="utf-8")
        sep = "\n" if current.endswith("\n") else "\n\n"
        with CHANGELOG.open("a", encoding="utf-8") as f:
            f.write(sep + entry)
        if args.sync:
            print(f"已按系统版本 {version}（{_version.APP_VERSION}）自动生成总结式版本通知 → {CHANGELOG}")
            print("版本通知接口会立即同步该版本；如需更精确的「更新要点」可直接编辑本条段落。")

    # --sync 始终重建部署发布数据，保证「代码更新 → 运行 --sync → 通知随代码入库」闭环
    if args.sync:
        write_data_file()
        print("发布前执行：python3 scripts/prepare_release.py --check")
        return check(args.range, args.strict)
    print(f"已追加版本骨架 {version} 到 {CHANGELOG}")
    print("发布前执行：python3 scripts/prepare_release.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
