"""V4.118 素材创意模板库 · 网页链接自动截图。

用本机 / 部署环境的 headless chromium 命令行模式对 URL 截图，落地成 PNG 文件字节。
设计要点：

- **路径探测**：优先环境变量 CHROMIUM_PATH → 常见系统路径 → Playwright 缓存的
  chrome-headless-shell；找不到即返回 unavailable，不假装成功。
- **SSRF 前置**：调用方必须先用 ssrf_guard.validate_url / fetch_remote_bytes 校验过
  目标 URL；本模块只负责"打开这个已准入的地址"，不再重复放宽校验。
- **诚实标注**：登录墙 / 验证码 / 纯动态渲染可能截到空白或不完整内容，本模块无法
  可靠判定，统一由路由层标注"网页截图 · 内容完整性未保证"，不冒充有效素材。
- **部署依赖**：真实 docker 镜像需预装 chromium（backend/Dockerfile），否则接口
  返回 unavailable + 明确原因；本机开发用 Playwright 缓存的 headless shell 即可。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional

SCREENSHOT_VERSION = "1.0"
_CHROME_TIMEOUT = 25

# 探测顺序：显式环境变量 → Linux/Docker 常见路径 → macOS 系统 Chrome → Playwright 缓存。
_CANDIDATES = [
    "$CHROMIUM_PATH",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chromium() -> str:
    """返回可用的 chromium 可执行文件路径；找不到返回空串。"""
    home = os.path.expanduser("~")
    # headless shell 优先（专为无头设计，命令行截图最稳定），系统 Chrome 兜底。
    pw_candidates: list[str] = []
    pw_dir = os.path.join(home, "Library", "Caches", "ms-playwright")
    if os.path.isdir(pw_dir):
        for name in sorted(os.listdir(pw_dir), reverse=True):
            if name.startswith("chromium_headless_shell-"):
                base = os.path.join(pw_dir, name)
                for root, _dirs, files in os.walk(base):
                    for fn in ("chrome-headless-shell", "headless_shell"):
                        if fn in files:
                            pw_candidates.append(os.path.join(root, fn))
        for name in sorted(os.listdir(pw_dir), reverse=True):
            if name.startswith("chromium-"):
                base = os.path.join(pw_dir, name)
                for root, _dirs, files in os.walk(base):
                    if "chromium" in files and "Chrome" not in root:
                        pw_candidates.append(os.path.join(root, "chromium"))
    # 显式环境变量 > playwright headless shell > 系统路径/Docker chromium。
    candidates = ([os.environ["CHROMIUM_PATH"]] if os.environ.get("CHROMIUM_PATH") else []) \
        + pw_candidates + [c for c in _CANDIDATES if c and "$CHROMIUM_PATH" not in c]
    for raw in candidates:
        path = os.path.expandvars(raw)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def screenshot(url: str, mode: str = "viewport", *, executable: Optional[str] = None) -> dict:
    """对已通过 SSRF 校验的 URL 截图，返回 PNG 字节。

    返回 {"status":"ok"|"unavailable", "png": bytes|None, "mode", "reason"}。
    mode=viewport 用 1280×900；fullpage 用 1280×3000（限制最大高度，避免超大图）。
    """
    exe = executable or find_chromium()
    if not exe:
        return {"status": "unavailable", "png": None, "mode": mode,
                "reason": "服务端未安装 chromium，无法自动截图（需在镜像中预装）"}
    size = "1280,3000" if str(mode).lower() == "fullpage" else "1280,900"
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "shot.png")
        cmd = [exe, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
               "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
               f"--window-size={size}", f"--screenshot={out}", url]
        proc = None
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=_CHROME_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"status": "unavailable", "png": None, "mode": mode,
                    "reason": "截图超时（页面加载超过 %ds）" % _CHROME_TIMEOUT}
        except Exception as e:
            return {"status": "unavailable", "png": None, "mode": mode,
                    "reason": "截图进程失败：" + type(e).__name__ + ": " + str(e)[:100]}
        if proc.returncode != 0 or not os.path.isfile(out):
            err = (proc.stderr or b"").decode("utf-8", "ignore")[-160:].strip()
            return {"status": "unavailable", "png": None, "mode": mode,
                    "reason": "截图失败：" + (err or "未生成图片文件")}
        try:
            with open(out, "rb") as f:
                png = f.read()
        except Exception as e:
            return {"status": "unavailable", "png": None, "mode": mode,
                    "reason": "读取截图失败：" + str(e)[:100]}
    if not png.startswith(b"\x89PNG"):
        return {"status": "unavailable", "png": None, "mode": mode,
                "reason": "截图输出不是有效 PNG"}
    if len(png) > 12 * 1024 * 1024:
        return {"status": "unavailable", "png": None, "mode": mode,
                "reason": "截图超过 12MB 限制"}
    return {"status": "ok", "png": png, "mode": mode, "bytes": len(png)}
