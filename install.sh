#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$ROOT/elab-futu-research"

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  echo "错误：找不到 $SOURCE/SKILL.md" >&2
  exit 1
fi

install_skill() {
  local base="$1"
  local target="$base/elab-futu-research"
  mkdir -p "$base"
  rm -rf "$target.tmp"
  cp -R "$SOURCE" "$target.tmp"
  if [[ -d "$target" ]]; then
    mv "$target" "$target.backup.$(date +%Y%m%d%H%M%S)"
  fi
  mv "$target.tmp" "$target"
  echo "已安装：$target"
}

case "${1:-all}" in
  all)
    install_skill "${CODEX_HOME:-$HOME/.codex}/skills"
    install_skill "${CLAUDE_HOME:-$HOME/.claude}/skills"
    ;;
  codex)
    install_skill "${CODEX_HOME:-$HOME/.codex}/skills"
    ;;
  claude)
    install_skill "${CLAUDE_HOME:-$HOME/.claude}/skills"
    ;;
  *)
    echo "用法：bash install.sh [all|codex|claude]" >&2
    exit 2
    ;;
esac

echo "完成。重新打开 Codex/Claude Code 后即可调用 elab-futu-research。"
echo "更多工具：github.com/edgelab101"
