#!/usr/bin/env bash
# 构建 LocalShareFile 安装包（wheel）。
# 用法： ./build.sh          构建到 dist/
#       ./build.sh install   构建后安装到当前 Python 环境
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 清理旧构建产物"
rm -rf dist build localsharefile.egg-info

echo "==> 构建 wheel 安装包"
if python3 -m build --wheel >/dev/null 2>&1; then
    :
else
    echo "   （未安装 build 模块，改用 pip wheel）"
    python3 -m pip wheel --no-deps -w dist .
fi

echo "==> 构建产物"
ls -lh dist/

if [[ "${1:-}" == "install" ]]; then
    echo "==> 安装到当前 Python 环境"
    python3 -m pip install --force-reinstall dist/localsharefile-*.whl
    echo "安装完成，试试：localsharefile --help"
fi
