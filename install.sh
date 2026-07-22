#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$ROOT/elab-futu-research"

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  echo "错误：找不到 $SOURCE/SKILL.md" >&2
  exit 1
fi

# Backup directory lives OUTSIDE the skills directory to avoid polluting
# the skill scanner with ghost copies of elab-futu-research.
BACKUP_BASE="$HOME/.elab-futu-research-backups"

# Keep at most 3 backups per agent type; prune older ones (by sort order).
# Uses only POSIX/bash-3.2-compatible constructs; no mapfile/readarray.
prune_backups() {
  local agent_prefix="$1"
  local keep=3
  if [[ ! -d "$BACKUP_BASE" ]]; then
    return 0
  fi
  # Collect matching dirs (sorted oldest-first by timestamp suffix).
  local list
  list=$(find "$BACKUP_BASE" -maxdepth 1 -type d -name "${agent_prefix}-*" 2>/dev/null | sort || true)
  if [[ -z "$list" ]]; then
    return 0
  fi
  local count
  count=$(printf '%s\n' "$list" | grep -c '^' || true)
  if (( count <= keep )); then
    return 0
  fi
  local to_delete=$(( count - keep ))
  # Delete exact paths — no glob rm -rf on $HOME.
  printf '%s\n' "$list" | head -n "$to_delete" | while IFS= read -r dir; do
    rm -rf "$dir"
  done
}

install_skill() {
  local base="$1"          # skills directory, e.g. ~/.claude/skills
  local agent_label="$2"   # "claude" or "codex"
  local target="$base/elab-futu-research"
  mkdir -p "$base"
  rm -rf "$target.tmp"
  cp -R "$SOURCE" "$target.tmp"
  if [[ -d "$target" ]]; then
    local ts
    ts="$(date +%Y%m%d%H%M%S)"
    local backup_dir="$BACKUP_BASE/${agent_label}-${ts}"
    mkdir -p "$BACKUP_BASE"
    mv "$target" "$backup_dir"
    echo "旧版本已备份至 $backup_dir"
    prune_backups "$agent_label"
  fi
  mv "$target.tmp" "$target"
  echo "已安装：$target"
}

case "${1:-all}" in
  all)
    install_skill "${CODEX_HOME:-$HOME/.codex}/skills"   "codex"
    install_skill "${CLAUDE_HOME:-$HOME/.claude}/skills" "claude"
    ;;
  codex)
    install_skill "${CODEX_HOME:-$HOME/.codex}/skills"   "codex"
    ;;
  claude)
    install_skill "${CLAUDE_HOME:-$HOME/.claude}/skills" "claude"
    ;;
  *)
    echo "用法：bash install.sh [all|codex|claude]" >&2
    exit 2
    ;;
esac

echo "完成。重新打开 Codex/Claude Code 后即可调用 elab-futu-research。"
echo "备份目录：~/.elab-futu-research-backups/（最多保留 3 份，自动清理旧备份）"
echo "更多工具：github.com/edgelab101"
