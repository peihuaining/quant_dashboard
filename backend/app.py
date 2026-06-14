import ipaddress
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import scanner
import live_bridge
import infra
import code_mgr
import signal_monitor
import backtest_runner
import equity_tracker

# ── IP 白名单 ─────────────────────────────────────────────────────────────────
ALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),        # localhost
    ipaddress.ip_network("192.168.100.0/24"),   # 局域网段
]

def _is_allowed(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in ALLOWED_NETWORKS)
    except ValueError:
        return False

app = FastAPI(title="Quant Dashboard API", docs_url="/api/docs")

@app.middleware("http")
async def ip_whitelist(request: Request, call_next):
    client_ip = request.client.host
    if not _is_allowed(client_ip):
        return JSONResponse(status_code=403, content={"detail": f"forbidden: {client_ip}"})
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:9001",
        "http://localhost:9001",
        "http://192.168.100.168:9001",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    bt = scanner.scan_backtests()
    wft = scanner.scan_wft()
    p23 = scanner.scan_phase23()
    return {
        "status": "ok",
        "backtest_count": len(bt),
        "wft_experiment_count": len(wft),
        "phase23_config_count": len(p23),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── backtests ─────────────────────────────────────────────────────────────────

@app.get("/api/backtests")
def list_backtests(group: Optional[str] = None, name: Optional[str] = None):
    items = scanner.scan_backtests()
    if group and group != "all":
        items = [x for x in items if x["group"] == group]
    if name:
        items = [x for x in items if name.lower() in x["name"].lower()]
    return {"items": items, "total": len(items)}


@app.get("/api/backtests/{backtest_id}")
def get_backtest(backtest_id: str):
    detail = scanner.get_backtest_detail(backtest_id)
    if not detail:
        raise HTTPException(status_code=404, detail="backtest not found")
    fr = detail["full_result"]
    ps = detail["portfolio_statistics"]
    # merge statistics from both sources for a unified view
    stats = {**(fr.get("statistics") or {}), **{k: v for k, v in ps.items()}}
    return {
        "backtestId": fr.get("backtestId"),
        "name": fr.get("name"),
        "projectId": fr.get("projectId"),
        "created": fr.get("created"),
        "backtestStart": fr.get("backtestStart"),
        "backtestEnd": fr.get("backtestEnd"),
        "status": fr.get("status"),
        "statistics": stats,
        "parameterSet": fr.get("parameterSet"),
    }


@app.get("/api/backtests/{backtest_id}/trades")
def get_trades(
    backtest_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    trades = scanner.get_trades(backtest_id)
    if trades is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    page = trades[skip: skip + limit]
    # normalise symbol field
    for t in page:
        syms = t.get("symbols", [])
        t["symbol"] = syms[0]["value"] if syms else "?"
    return {"trades": page, "total": len(trades), "skip": skip, "limit": limit}


@app.get("/api/backtests/{backtest_id}/charts")
def get_charts(backtest_id: str):
    result = scanner.get_charts(backtest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    return result


# ── compare ───────────────────────────────────────────────────────────────────

@app.get("/api/compare")
def compare(ids: str = Query(..., description="comma-separated backtest IDs")):
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:3]
    items = []
    for bid in id_list:
        detail = scanner.get_backtest_detail(bid)
        if not detail:
            continue
        fr = detail["full_result"]
        ps = detail["portfolio_statistics"]
        stats = {**(fr.get("statistics") or {}), **ps}
        items.append({
            "backtestId": fr.get("backtestId"),
            "name": fr.get("name"),
            "statistics": stats,
            "backtestStart": fr.get("backtestStart"),
            "backtestEnd": fr.get("backtestEnd"),
        })
    return {"items": items}


# ── wft ───────────────────────────────────────────────────────────────────────

@app.get("/api/wft")
def list_wft():
    return {"experiments": scanner.scan_wft()}


# ── phase23 ───────────────────────────────────────────────────────────────────

@app.get("/api/phase23")
def list_phase23():
    return {"configs": scanner.scan_phase23()}


# ── live (read-only, whitelisted) ─────────────────────────────────────────────

@app.get("/api/live/status")
async def live_status():
    return await live_bridge.run_live_cmd("status")


@app.get("/api/live/logs")
async def live_logs(hours: int = Query(1, ge=1, le=24)):
    return await live_bridge.run_live_cmd("logs", str(hours))


@app.get("/api/live/orders")
async def live_orders(n: int = Query(10, ge=1, le=100)):
    return await live_bridge.run_live_cmd("orders", str(n))


@app.get("/api/live/objectstore")
async def live_objectstore():
    return await live_bridge.run_live_cmd("objectstore")


@app.get("/api/live/structured")
async def live_structured():
    result = await live_bridge.run_live_structured()
    equity_tracker.append(result.get("runtime_stats", {}).get("Equity", ""))
    return result


@app.get("/api/live/equity_history")
def live_equity_history():
    points = equity_tracker.load()
    return {"points": points, "count": len(points)}


# ── infrastructure ────────────────────────────────────────────────────────────

@app.get("/api/infra/network")
async def infra_network():
    return await infra.get_network_status()


@app.get("/api/infra/git")
async def infra_git():
    return await infra.get_git_info()


@app.get("/api/infra/cron")
async def infra_cron():
    return infra.get_cron_status()


# ── code manager ─────────────────────────────────────────────────────────────

@app.get("/api/code/diff")
async def code_diff(
    from_branch: str = Query("master"),
    to_branch: str = Query("feature/live-ema50-correction"),
    file: Optional[str] = Query(None),
):
    return await code_mgr.get_diff(from_branch, to_branch, file)


@app.get("/api/code/commits")
async def code_commits(
    branch: str = Query("feature/live-ema50-correction"),
    n: int = Query(15, ge=1, le=50),
    base: Optional[str] = Query(None),
):
    return await code_mgr.get_commits(branch, n, base)


@app.get("/api/code/branches")
async def code_branches():
    return await code_mgr.get_branches_with_stats()


# ── signal monitor ────────────────────────────────────────────────────────────

@app.get("/api/signal/config")
def signal_config():
    return signal_monitor.get_strategy_config_extended()


@app.get("/api/signal/logs")
def signal_logs():
    lines = signal_monitor.get_recent_signals()
    return {"lines": lines, "total": len(lines)}


# ── backtest trigger (test project 30796820 only) ─────────────────────────────

@app.post("/api/backtest/run")
async def run_backtest(days: int = Query(365, ge=backtest_runner.MIN_DAYS, le=backtest_runner.MAX_DAYS)):
    return await backtest_runner.trigger(days)


@app.get("/api/backtest/job")
def backtest_job():
    return backtest_runner.get_status()


# ── static frontend ───────────────────────────────────────────────────────────

if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
