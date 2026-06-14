#!/bin/bash
# Quant Dashboard — 本地 CI 脚本
# 用法:
#   bash tests/run_ci.sh           # 全量测试
#   bash tests/run_ci.sh unit      # 仅单元测试（无需 API 服务）
#   bash tests/run_ci.sh integ     # 仅集成测试
#   bash tests/run_ci.sh fast      # 仅单元测试（同 unit，快速验证）

set -euo pipefail

DASHBOARD_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="/home/administrator/quant_stock"
LOG_FILE="${LOG_DIR}/dashboard_ci.log"
API_URL="http://127.0.0.1:9001/api/health"
BOT_TOKEN="6346087166:AAGDWwQuBAf_RJPnZAN8GxSgsQv9MsNHOQM"
CHAT_ID="900695327"
MODE="${1:-all}"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo -e "$(ts)  $*" | tee -a "$LOG_FILE"; }
info()    { log "${CYAN}[INFO]${RESET}  $*"; }
ok()      { log "${GREEN}[PASS]${RESET}  $*"; }
warn()    { log "${YELLOW}[WARN]${RESET}  $*"; }
fail()    { log "${RED}[FAIL]${RESET}  $*"; }
section() { log "${BOLD}──── $* ────${RESET}"; }

send_telegram() {
    local msg="$1"
    curl -s --max-time 10 -X POST \
        "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${CHAT_ID}\",\"text\":$(echo "$msg" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}" \
        > /dev/null 2>&1 || true
}

# ── 检查 API 服务是否运行 ─────────────────────────────────────────────────────
check_api() {
    if curl -sf --max-time 5 "$API_URL" > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

# ── 确保 API 服务运行（集成测试需要） ────────────────────────────────────────
ensure_api_running() {
    if check_api; then
        info "API 服务已运行 (${API_URL})"
        return 0
    fi

    info "API 服务未运行，正在启动..."
    cd "${DASHBOARD_DIR}/backend"
    nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 9001 \
        --log-level warning >> "${LOG_DIR}/dashboard.log" 2>&1 &
    local pid=$!

    local waited=0
    while [ $waited -lt 15 ]; do
        sleep 1
        waited=$((waited + 1))
        if check_api; then
            info "API 服务启动成功 (PID $pid，等待 ${waited}s)"
            return 0
        fi
    done

    fail "API 服务启动超时（15s）"
    return 1
}

# ── 运行 pytest，捕获结果 ─────────────────────────────────────────────────────
run_pytest() {
    local label="$1"; shift
    local args=("$@")
    local tmp
    tmp=$(mktemp)

    section "$label"
    if python3 -m pytest "${args[@]}" 2>&1 | tee -a "$LOG_FILE" | tee "$tmp"; then
        local passed
        passed=$(grep -E "^[0-9]+ passed" "$tmp" | grep -oE "^[0-9]+" || echo "?")
        ok "${label}: ${passed} 个用例全部通过"
        rm -f "$tmp"
        return 0
    else
        local summary
        summary=$(grep -E "passed|failed|error" "$tmp" | tail -1 || echo "见日志")
        fail "${label} 失败 — ${summary}"
        rm -f "$tmp"
        return 1
    fi
}

# ── 主流程 ────────────────────────────────────────────────────────────────────
START_TS=$(date +%s)
FAILED=0

echo "" >> "$LOG_FILE"
section "Quant Dashboard CI  [mode=${MODE}]  $(ts)"

cd "$DASHBOARD_DIR"

case "$MODE" in
    unit|fast)
        run_pytest "单元测试" \
            tests/test_unit_scanner.py \
            tests/test_unit_live_bridge.py \
            tests/test_unit_infra.py \
            || FAILED=1
        ;;
    integ|integration)
        ensure_api_running || { FAILED=1; }
        if [ "$FAILED" -eq 0 ]; then
            run_pytest "集成测试" tests/test_integration_api.py || FAILED=1
        fi
        ;;
    all|*)
        # 先跑单元测试（快）
        run_pytest "单元测试" \
            tests/test_unit_scanner.py \
            tests/test_unit_live_bridge.py \
            tests/test_unit_infra.py \
            || FAILED=1

        # 集成测试需要 API
        ensure_api_running || FAILED=1

        if [ "$FAILED" -eq 0 ]; then
            run_pytest "集成测试" tests/test_integration_api.py || FAILED=1
        fi
        ;;
esac

ELAPSED=$(( $(date +%s) - START_TS ))

# ── 汇总 ─────────────────────────────────────────────────────────────────────
section "CI 结束  耗时 ${ELAPSED}s"

if [ "$FAILED" -eq 0 ]; then
    ok "✅ 所有测试通过  (${ELAPSED}s)"
    # 仅在 cron 环境中发送成功消息（有 DASHBOARD_CI_NOTIFY_OK=1 时）
    if [ "${DASHBOARD_CI_NOTIFY_OK:-0}" = "1" ]; then
        send_telegram "✅ Quant Dashboard CI 通过
模式: ${MODE} | 耗时: ${ELAPSED}s
$(ts)"
    fi
    exit 0
else
    fail "❌ 测试失败，见日志: ${LOG_FILE}"
    # 失败时总是通知
    send_telegram "❌ Quant Dashboard CI 失败
模式: ${MODE} | 耗时: ${ELAPSED}s
日志: ${LOG_FILE}
$(ts)"
    exit 1
fi
