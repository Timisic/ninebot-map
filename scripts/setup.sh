#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  printf '未找到 uv。请先按 https://docs.astral.sh/uv/getting-started/installation/ 安装，再运行本脚本。\n' >&2
  exit 1
fi
uv sync --frozen
./run doctor
