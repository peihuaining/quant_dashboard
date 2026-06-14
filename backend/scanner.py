import json
import glob
import os
import re
from typing import Any

DATA_DIR = "/home/administrator/quant_stock"


def _parse_group(name: str) -> str:
    if name.startswith("BT_"):
        return "early"
    if re.match(r"bt_phase1_|bt_p1_", name):
        return "phase1"
    if re.match(r"bt_p23_", name):
        return "phase23"
    if re.match(r"wft_ConfigE_", name):
        return "wft_configE"
    if re.match(r"wft_ConfigF_", name):
        return "wft_configF"
    if re.match(r"wft_capm3m_", name):
        return "wft_capm3m"
    if re.match(r"wft_dynamic_", name):
        return "wft_dynamic"
    return "other"


def _safe_float(val: Any) -> float | None:
    try:
        return float(str(val).replace("%", "").replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def scan_backtests() -> list[dict]:
    results = []
    for d in sorted(glob.glob(f"{DATA_DIR}/backtest_*")):
        fr_path = os.path.join(d, "full_result.json")
        ps_path = os.path.join(d, "portfolio_statistics.json")
        if not os.path.exists(fr_path):
            continue
        try:
            with open(fr_path) as f:
                fr = json.load(f)
        except Exception:
            continue

        ps = {}
        if os.path.exists(ps_path):
            try:
                with open(ps_path) as f:
                    ps = json.load(f)
            except Exception:
                pass

        # statistics can come from full_result or portfolio_statistics
        stats_raw = fr.get("statistics") or {}
        # prefer portfolio_statistics fields when present
        sharpe = _safe_float(ps.get("sharpeRatio") or stats_raw.get("Sharpe Ratio"))
        annual = _safe_float(ps.get("compoundingAnnualReturn") or stats_raw.get("Compounding Annual Return"))
        drawdown = _safe_float(ps.get("drawdown") or stats_raw.get("Drawdown"))
        win_rate_raw = ps.get("winRate") or stats_raw.get("Win Rate")
        win_rate = _safe_float(win_rate_raw)
        if win_rate and win_rate <= 1.0:
            win_rate = win_rate * 100

        name = fr.get("name") or os.path.basename(d)
        backtest_id = fr.get("backtestId") or os.path.basename(d).replace("backtest_", "")

        results.append({
            "backtestId": backtest_id,
            "name": name,
            "group": _parse_group(name),
            "projectId": fr.get("projectId"),
            "created": (fr.get("created") or "")[:10],
            "backtestStart": (fr.get("backtestStart") or "")[:10],
            "backtestEnd": (fr.get("backtestEnd") or "")[:10],
            "status": fr.get("status"),
            "sharpe": sharpe,
            "annualReturn": annual,
            "drawdown": drawdown,
            "winRate": win_rate,
            "dirPath": d,
        })

    results.sort(key=lambda x: x["created"], reverse=True)
    return results


def get_backtest_detail(backtest_id: str) -> dict | None:
    # find by backtestId or directory name suffix
    for d in glob.glob(f"{DATA_DIR}/backtest_*"):
        fr_path = os.path.join(d, "full_result.json")
        if not os.path.exists(fr_path):
            continue
        try:
            with open(fr_path) as f:
                fr = json.load(f)
        except Exception:
            continue
        bid = fr.get("backtestId") or os.path.basename(d).replace("backtest_", "")
        if bid == backtest_id:
            ps = {}
            ps_path = os.path.join(d, "portfolio_statistics.json")
            if os.path.exists(ps_path):
                try:
                    with open(ps_path) as f:
                        ps = json.load(f)
                except Exception:
                    pass
            return {"full_result": fr, "portfolio_statistics": ps, "dirPath": d}
    return None


def get_trades(backtest_id: str) -> list[dict] | None:
    detail = get_backtest_detail(backtest_id)
    if not detail:
        return None
    ct_path = os.path.join(detail["dirPath"], "closed_trades.json")
    if not os.path.exists(ct_path):
        return []
    try:
        with open(ct_path) as f:
            return json.load(f)
    except Exception:
        return []


def get_charts(backtest_id: str) -> dict | None:
    detail = get_backtest_detail(backtest_id)
    if not detail:
        return None
    d = detail["dirPath"]

    # Build monthly equity curve from rolling_window endEquity
    equity: list[dict] = []
    rw_path = os.path.join(d, "rolling_window.json")
    if os.path.exists(rw_path):
        try:
            with open(rw_path) as f:
                rw = json.load(f)
            # keys like "M1_20230131" — sort by date suffix
            months = sorted(rw.items(), key=lambda kv: kv[0].split("_", 1)[-1])
            for key, val in months:
                date_str = key.split("_", 1)[-1]  # "20230131"
                end_eq = _safe_float((val.get("portfolioStatistics") or {}).get("endEquity"))
                if end_eq is not None:
                    equity.append({"x": date_str, "y": end_eq})
        except Exception:
            pass

    # Build cumulative P&L curve from closed_trades (trade-level, sorted by exitTime)
    trade_curve: list[dict] = []
    ct_path = os.path.join(d, "closed_trades.json")
    start_equity = 100_000.0
    if os.path.exists(ct_path):
        try:
            with open(ct_path) as f:
                trades = json.load(f)
            trades_sorted = sorted(trades, key=lambda t: t.get("exitTime", ""))
            cumulative = start_equity
            for t in trades_sorted:
                pl = _safe_float(t.get("profitLoss")) or 0.0
                fees = _safe_float(t.get("totalFees")) or 0.0
                cumulative += pl - fees
                date = (t.get("exitTime") or "")[:10]
                if date:
                    trade_curve.append({"x": date, "y": round(cumulative, 2)})
        except Exception:
            pass

    # normalise equity to start at 1.0
    def normalise(pts: list[dict]) -> list[dict]:
        if not pts:
            return pts
        base = float(pts[0]["y"])
        if base == 0:
            return pts
        return [{"x": p["x"], "y": round(float(p["y"]) / base, 6)} for p in pts]

    return {
        "equity": normalise(equity),          # monthly from rolling_window
        "trade_curve": normalise(trade_curve), # per-trade from closed_trades
        "benchmark": [],
    }


def _wft_experiment(name: str, commit: str | None, windows: list[dict]) -> dict:
    sharpes = [_safe_float(w.get("sharpe")) for w in windows]
    sharpes_valid = [s for s in sharpes if s is not None]
    avg_sharpe = round(sum(sharpes_valid) / len(sharpes_valid), 3) if sharpes_valid else None
    positive = sum(1 for s in sharpes_valid if s > 0)
    return {
        "name": name,
        "commit": commit or "N/A",
        "windows": windows,
        "avg_sharpe": avg_sharpe,
        "positive_windows": positive,
        "total_windows": len(windows),
        "multi_config": any("config" in w for w in windows),
    }


def scan_wft() -> list[dict]:
    experiments = []
    for fp in sorted(glob.glob(f"{DATA_DIR}/wft_*.json")):
        try:
            with open(fp) as f:
                data = json.load(f)
        except Exception:
            continue
        name = os.path.basename(fp).replace(".json", "")
        m = re.match(r"wft_([a-zA-Z0-9]+)_\d{8}", name)
        exp_name = m.group(1) if m else name
        commit = data.get("commit")
        windows = data.get("results", [])

        # if results carry a "config" field, split into sub-experiments
        configs_present = {w.get("config") for w in windows if w.get("config")}
        if len(configs_present) > 1:
            for cfg in sorted(configs_present):
                sub_wins = [w for w in windows if w.get("config") == cfg]
                sub_commit = sub_wins[0].get("commit") if sub_wins else commit
                experiments.append(_wft_experiment(
                    f"{exp_name}/{cfg}", sub_commit or commit, sub_wins
                ))
        else:
            experiments.append(_wft_experiment(exp_name, commit, windows))

    return experiments


def scan_phase23() -> list[dict]:
    results = []
    for fp in sorted(glob.glob(f"{DATA_DIR}/phase23_audit_*.json")):
        try:
            with open(fp) as f:
                data = json.load(f)
        except Exception:
            continue
        for item in data.get("results", []):
            stats = item.get("stats", {})
            audit = item.get("audit", {})
            results.append({
                "name": item.get("name"),
                "commit": item.get("commit"),
                "tp": item.get("tp"),
                "sl": item.get("sl"),
                "adx": item.get("adx"),
                "backtestId": item.get("backtest_id"),
                "sharpe": _safe_float(stats.get("Sharpe Ratio")),
                "annualReturn": _safe_float(stats.get("Compounding Annual Return")),
                "drawdown": _safe_float(stats.get("Drawdown")),
                "winRate": _safe_float(stats.get("Win Rate")),
                "totalOrders": _safe_float(stats.get("Total Orders")),
                "auditPassed": audit.get("passed"),
                "auditSummary": audit.get("summary"),
                "auditFlags": audit.get("flags", []),
            })
    return results
