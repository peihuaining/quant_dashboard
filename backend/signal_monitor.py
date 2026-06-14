"""信号看板 — 策略参数解析 + 信号日志提取"""
import re
import os
from pathlib import Path

STRATEGY_DIR = "/opt/lean-trading/lean-workspace/MyStrategy"
LOG_DIR = "/home/administrator/quant_stock"

# Regex patterns for each config param in main.py
_PARAM_PATTERNS = {
    "fast_period":             r"self\.fast_period\s*=\s*(\d+)",
    "slow_period":             r"self\.slow_period\s*=\s*(\d+)",
    "leverage_factor":         r"self\.leverage_factor\s*=\s*([\d.]+)",
    "stop_loss_multiplier":    r"self\.stop_loss_multiplier\s*=\s*([\d.]+)",
    "take_profit_multiplier":  r"self\.take_profit_multiplier\s*=\s*([\d.]+)",
    "max_portfolio_count":     r"self\.max_portfolio_count\s*=\s*(\d+)",
    "lookback_period":         r"self\.lookback_period\s*=\s*(\d+)",
    "rebalance_frequency":     r"self\.rebalance_frequency\s*=\s*(\d+)",
    "stop_loss_freeze_period": r"self\.stop_loss_freeze_period\s*=\s*(\d+)",
}

_SIGNAL_KEYWORDS = [
    "EMA", "ATR", "crossover", "cross", "entry", "exit",
    "开仓", "平仓", "止损", "买入", "卖出", "Regime",
    "Bull", "Bear", "signal", "Signal", "BULL", "BEAR",
]


def get_strategy_config() -> dict:
    """Parse main.py for live strategy parameters."""
    path = os.path.join(STRATEGY_DIR, "main.py")
    try:
        src = Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e)}

    result = {}
    for key, pattern in _PARAM_PATTERNS.items():
        m = re.search(pattern, src)
        if m:
            val = m.group(1)
            try:
                result[key] = float(val) if "." in val else int(val)
            except ValueError:
                result[key] = val

    # SPY EMA periods used (all of them)
    spy_emas = [int(x) for x in re.findall(r'self\.EMA\("SPY",\s*(\d+)', src)]
    result["spy_emas"] = sorted(set(spy_emas))

    # Detect SPY EMA50 3-day filter from branch name hint or source
    result["spy_ema50_3day_filter"] = bool(
        re.search(r"spyema50|spy_ema50|3.day|three.day", src, re.IGNORECASE)
    )

    # Universe source
    result["universe"] = "ARKK ETF 成分股"

    # Tickers from tech_tickers list
    m = re.search(r'self\.tech_tickers\s*=\s*\[([^\]]+)\]', src)
    if m:
        tickers = re.findall(r'"([A-Z]+)"', m.group(1))
        result["tech_tickers"] = tickers

    result["strategy_file"] = path

    return result


def get_strategy_config_extended() -> dict:
    """Config from main.py + daily trade processor params."""
    cfg = get_strategy_config()

    # Read dailytradeprocessor.py for any extra params
    dtp_path = os.path.join(STRATEGY_DIR, "dailytradeprocessor.py")
    try:
        dtp_src = Path(dtp_path).read_text(encoding="utf-8")
        # SPY EMA200 as market regime filter
        m = re.search(r"spyema200|spy.*ema.*200|EMA.*200", dtp_src, re.IGNORECASE)
        cfg["spy200_regime_filter"] = bool(m)

        # ATR period
        m = re.search(r'ATR\([^,]+,\s*(\d+)', dtp_src)
        if m:
            cfg["atr_period"] = int(m.group(1))
    except Exception:
        pass

    return cfg


def get_recent_signals(lines_limit: int = 100) -> list:
    """Extract signal-related lines from recent logs."""
    log_files = [
        os.path.join(LOG_DIR, "daily_check.log"),
        os.path.join(LOG_DIR, "qc_assistant.log"),
    ]

    all_lines = []
    for log_path in log_files:
        try:
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
            all_lines.extend(lines[-300:])
        except Exception:
            pass

    result = []
    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in _SIGNAL_KEYWORDS):
            result.append(line)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for l in result:
        if l not in seen:
            seen.add(l)
            deduped.append(l)

    return deduped[-lines_limit:]
