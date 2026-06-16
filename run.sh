#!/bin/bash
# 每日金融情报官 — LangGraph Agent 一键运行脚本
# 并行采集7个资产 → LLM深度分析 → 合成日报 → 推送到微信
#
# 用法:
#   bash run.sh                  # Agent 分析 + 推送
#   bash run.sh --verbose        # 详细输出
#   bash run.sh --save-only      # 只生成日报，不推送

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 加载 .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^\s*#' "$SCRIPT_DIR/.env" | xargs)
fi

SAVE_ONLY=""
VERBOSE=""

for arg in "$@"; do
    case "$arg" in
        --verbose|-v)   VERBOSE="-v" ;;
        --save-only)    SAVE_ONLY="--save-only" ;;
    esac
done

echo "╔═══════════════════════════════════╗"
echo "║  每日金融情报官 · LangGraph Agent  ║"
echo "║  $(date '+%Y-%m-%d %H:%M')                ║"
echo "╚═══════════════════════════════════╝"
echo ""

cd "$SCRIPT_DIR"
python3 scripts/push_report.py $VERBOSE $SAVE_ONLY

# ── 第2步：生成网页看板 ──
echo ""
echo "╔═══════════════════════════════════╗"
echo "║  🕸️  生成网页看板...              ║"
echo "╚═══════════════════════════════════╝"
python3 scripts/generate_web_data.py --skip-llm $VERBOSE
echo "   ✅ 网页已更新: web/index.html"

echo ""
echo "╔═══════════════════════════════════╗"
echo "║  ✅ 完成                         ║"
echo "╚═══════════════════════════════════╝"
