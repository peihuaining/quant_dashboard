"""云端回测管理 — 列表 / 详情 / 删除（仅测试项目 30796820）"""
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

AGENT_DIR       = Path("/home/administrator/workspace/quantconnect_agent")
SECRETS         = Path.home() / ".openclaw" / "secrets.env"
TEST_PROJECT_ID = 30796820

CACHE_LIST_TTL   = 30    # seconds
CACHE_DETAIL_TTL = 300   # seconds

_list_cache: dict = {"ts": 0, "data": None}
_detail_cache: dict = {}   # bt_id → {"ts": float, "data": dict}


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_env() -> None:
    if not SECRETS.exists():
        return
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _get_mgr():
    _load_env()
    sys.path.insert(0, str(AGENT_DIR))
    from qc_cloud_manager import CloudStrategyManager  # type: ignore
    return CloudStrategyManager()


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_series(charts: dict, chart_name: str, *series_names: str) -> list:
    """Extract [{x, y}] from QC charts dict, trying series names in order."""
    chart = charts.get(chart_name, {})
    series_map = chart.get("series", {})
    s = None
    for name in series_names:
        if name in series_map:
            s = series_map[name]
            break
    if s is None and series_map:
        s = next(iter(series_map.values()))
    if not s:
        return []
    out = []
    for v in s.get("values", []):
        if isinstance(v, dict):
            x = v.get("x") or v.get("t")
            y = v.get("y") or v.get("v")
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            x, y = v[0], v[1]
        else:
            continue
        if x is not None and y is not None:
            out.append({"x": int(x), "y": float(y)})
    return out


def _parse_rolling(rw: dict) -> list:
    """Rolling window → [{month:'2022-01', sharpe, cagr, winRate, equity}], last 24."""
    if not rw:
        return []
    months = []
    for key, val in rw.items():
        if not isinstance(val, dict):
            continue
        # key format: M12_20220131 — extract YYYYMMDD
        date_part = key.split("_")[-1] if "_" in key else key
        label = f"{date_part[:4]}-{date_part[4:6]}" if len(date_part) >= 6 else key
        ps = val.get("portfolioStatistics", {}) or {}
        months.append({
            "month":  label,
            "sharpe": _f(ps.get("sharpeRatio")),
            "cagr":   _f(ps.get("compoundingAnnualReturn")),
            "winRate":_f(ps.get("winRate")),
            "equity": _f(ps.get("endEquity")),
        })
    months.sort(key=lambda m: m["month"])
    return months[-24:]


def _build_equity_from_rolling(rw: dict) -> list:
    """Build monthly equity curve [{month, equity}] from all rolling window entries.

    Each entry represents a rolling-window period ending on that month's date.
    The endEquity field gives the portfolio value at that date, producing a
    continuous monthly equity time series when sorted chronologically.
    """
    if not rw:
        return []
    points = []
    for key, val in rw.items():
        if not isinstance(val, dict):
            continue
        date_part = key.split("_")[-1] if "_" in key else key
        label = f"{date_part[:4]}-{date_part[4:6]}" if len(date_part) >= 6 else key
        ps = val.get("portfolioStatistics", {}) or {}
        eq = _f(ps.get("endEquity"))
        if eq is not None:
            points.append({"month": label, "equity": eq})
    points.sort(key=lambda p: p["month"])
    # Deduplicate months (keep last occurrence for same label)
    seen: dict = {}
    for p in points:
        seen[p["month"]] = p["equity"]
    return [{"month": k, "equity": v} for k, v in sorted(seen.items())]


def _norm_status(s: str) -> str:
    """Normalize QC status strings ('Completed.' → 'Completed')."""
    return (s or "").rstrip(". ")


def _str(v) -> str:
    """Safely convert any value to a date string (handles bool False from QC API)."""
    if not v or not isinstance(v, str):
        return ""
    return v


def _summary_item(bt: dict) -> dict:
    return {
        "id":        bt.get("backtestId"),
        "name":      bt.get("name", ""),
        "status":    _norm_status(bt.get("status", "")),
        "created":   _str(bt.get("created"))[:16],
        "completed": _str(bt.get("completed"))[:16],
        "progress":       _f(bt.get("progress")) or 0.0,
        "tradeableDates": bt.get("tradeableDates"),   # proxy for backtest length
        "error":          bt.get("error"),
    }


# ── public API (sync, wrapped in asyncio.to_thread by callers) ────────────────

def _list_backtests_sync(force: bool) -> list:
    now = time.time()
    if not force and _list_cache["ts"] and now - _list_cache["ts"] < CACHE_LIST_TTL:
        return _list_cache["data"]
    mgr = _get_mgr()
    r = mgr.qc.api_call("backtests/read", {"projectId": TEST_PROJECT_ID})
    bts = r.json().get("backtests", [])
    items = [_summary_item(b) for b in bts]
    items.sort(key=lambda x: x["created"], reverse=True)
    _list_cache.update({"ts": now, "data": items})
    return items


def _get_detail_sync(bt_id: str, force: bool) -> dict:
    now = time.time()
    if not force and bt_id in _detail_cache:
        cached = _detail_cache[bt_id]
        if now - cached["ts"] < CACHE_DETAIL_TTL:
            return cached["data"]
    mgr = _get_mgr()
    r = mgr.qc.api_call("backtests/read", {"projectId": TEST_PROJECT_ID, "backtestId": bt_id})
    bt = r.json().get("backtest", {})

    stats   = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})
    tp      = bt.get("totalPerformance", {}) or {}
    ps      = tp.get("portfolioStatistics") or {}
    ts      = tp.get("tradeStatistics")     or {}
    charts  = bt.get("charts", {})

    rw = bt.get("rollingWindow", {}) or {}
    equity_curve = _build_equity_from_rolling(rw)

    result = {
        "id":           bt_id,
        "name":         bt.get("name", ""),
        "status":       _norm_status(bt.get("status", "")),
        "created":      _str(bt.get("created"))[:16],
        "backtestStart":bt.get("backtestStart", ""),
        "backtestEnd":  bt.get("backtestEnd", ""),
        "kpis": {
            # statistics has plain-English keys
            "cagr":           _f(stats.get("Compounding Annual Return")),
            "drawdown":       _f(stats.get("Drawdown")),
            "totalOrders":    ts.get("totalNumberOfTrades"),
            # portfolioStatistics has camelCase keys
            "sharpe":         _f(ps.get("sharpeRatio")),
            "sortino":        _f(ps.get("sortinoRatio")),
            "winRate":        _f(ps.get("winRate")),
            "psr":            _f(ps.get("probabilisticSharpeRatio")),
            "profitLossRatio":_f(ps.get("profitLossRatio")),
            "alpha":          _f(ps.get("alpha")),
            "beta":           _f(ps.get("beta")),
            "var99":          _f(ps.get("valueAtRisk99")),
            "startEquity":    _f(ps.get("startEquity")),
            "endEquity":      _f(ps.get("endEquity")),
            # tradeStatistics keys
            "profitFactor":   _f(ts.get("profitFactor")),
            "avgDuration":    str(ts.get("averageTradeDuration", "")),
            "maxConsecWins":  ts.get("maxConsecutiveWinningTrades"),
            "maxConsecLoss":  ts.get("maxConsecutiveLosingTrades"),
        },
        "statistics":  stats,
        "runtime":     runtime,
        "charts": {
            # Charts series are empty via this API — equity built from rolling window
            "equity": equity_curve,
        },
        "monthly": _parse_rolling(rw),
    }
    _detail_cache[bt_id] = {"ts": now, "data": result}
    return result


def _delete_sync(bt_id: str) -> dict:
    mgr = _get_mgr()
    r = mgr.qc.api_call("backtests/delete", {"projectId": TEST_PROJECT_ID, "backtestId": bt_id})
    success = r.json().get("success", False)
    _detail_cache.pop(bt_id, None)
    _list_cache["ts"] = 0   # invalidate list cache
    return {"success": success}


# ── async wrappers ────────────────────────────────────────────────────────────

async def list_backtests(force: bool = False) -> list:
    return await asyncio.to_thread(_list_backtests_sync, force)


async def get_detail(bt_id: str, force: bool = False) -> dict:
    return await asyncio.to_thread(_get_detail_sync, bt_id, force)


async def delete_backtest(bt_id: str) -> dict:
    return await asyncio.to_thread(_delete_sync, bt_id)
