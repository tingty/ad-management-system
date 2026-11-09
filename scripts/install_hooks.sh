#!/bin/sh
# 安装「发版前版本通知校验」pre-push 钩子到本机 .git/hooks/。
# 钩子文件本身不随 git 同步，因此每台开发 / 部署机执行一次即可。
set -e
ROOT=$(git rev-parse --show-toplevel)
HOOK="$ROOT/.git/hooks/pre-push"
mkdir -p "$(dirname "$HOOK")"

if [ -f "$HOOK" ] && ! grep -q "prepare_release.py" "$HOOK"; then
  BACKUP="$HOOK.bak.$(date +%Y%m%d%H%M%S)"
  cp "$HOOK" "$BACKUP"
  echo "已备份原有 pre-push 钩子：$BACKUP"
fi

cp "$ROOT/scripts/hooks/pre-push" "$HOOK"
chmod +x "$HOOK"
echo "已安装 pre-push 发版校验钩子：$HOOK"
echo "此后每次 git push 都会校验 CHANGELOG.md 的最新版本通知；"
echo "紧急跳过：SKIP_RELEASE_CHECK=1 git push（事后请补齐版本通知）。"
