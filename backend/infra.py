"""基础设施健康检查模块 — 网络/Git/定时任务"""
import asyncio
import os
import re
from datetime import datetime

LOG_DIR = "/home/administrator/quant_stock"
STRATEGY_DIR = "/opt/lean-trading/lean-workspace/MyStrategy"
ROUTER_HOST = "192.168.100.1"
ROUTER_PASS = "P314ADsl"


def _read_log_tail(path: str, lines: int = 30) -> list[str]:
    try:
        with open(path, errors="replace") as f:
            content = f.readlines()
        return [l.rstrip() for l in content[-lines:] if l.strip()]
    except FileNotFoundError:
        return []
    except Exception as e:
        return [f"[error: {e}]"]


def _last_modified(path: str) -> str | None:
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _file_size_kb(path: str) -> float:
    try:
        return round(os.path.getsize(path) / 1024, 1)
    except Exception:
        return 0.0


async def get_git_info() -> dict:
    try:
        p1 = await asyncio.create_subprocess_exec(
            "git", "-C", STRATEGY_DIR, "rev-parse", "--abbrev-ref", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        o1, _ = await asyncio.wait_for(p1.communicate(), timeout=5)
        current = o1.decode().strip()

        p2 = await asyncio.create_subprocess_exec(
            "git", "-C", STRATEGY_DIR, "branch", "-v",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        o2, _ = await asyncio.wait_for(p2.communicate(), timeout=5)
        branches = []
        for line in o2.decode().splitlines():
            is_cur = line.startswith("*")
            rest = line[2:].strip()
            parts = rest.split(None, 2)
            if len(parts) >= 2:
                branches.append({
                    "name": parts[0],
                    "commit": parts[1],
                    "message": parts[2] if len(parts) > 2 else "",
                    "current": is_cur,
                    "is_live": parts[0] == "feature/live-ema50-correction",
                })

        p3 = await asyncio.create_subprocess_exec(
            "git", "-C", STRATEGY_DIR, "log", "--oneline", "-5",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        o3, _ = await asyncio.wait_for(p3.communicate(), timeout=5)
        recent_commits = [l.strip() for l in o3.decode().splitlines() if l.strip()]

        return {"current": current, "branches": branches, "recent_commits": recent_commits}
    except Exception as e:
        return {"current": None, "branches": [], "recent_commits": [], "error": str(e)}


async def get_network_status() -> dict:
    node_log = _read_log_tail(f"{LOG_DIR}/node_monitor.log", 30)
    network_log = _read_log_tail(f"{LOG_DIR}/network_check.log", 20)

    current_node = None
    router_reachable = False
    try:
        proc = await asyncio.create_subprocess_exec(
            "sshpass", "-p", ROUTER_PASS, "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            f"root@{ROUTER_HOST}",
            (
                'GLOBAL=$(uci show passwall | grep "=global$" | head -1 | cut -d. -f2 | cut -d= -f1);'
                'NID=$(uci get passwall.${GLOBAL}.tcp_node 2>/dev/null);'
                'REMARKS=$(uci get passwall.${NID}.remarks 2>/dev/null);'
                'echo "NID:${NID}";echo "REMARKS:${REMARKS}";'
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        out = stdout.decode()
        nid_m = re.search(r"NID:(\S+)", out)
        rem_m = re.search(r"REMARKS:(.+)", out)
        if nid_m:
            router_reachable = True
            current_node = {
                "id": nid_m.group(1),
                "remarks": rem_m.group(1).strip() if rem_m else "",
            }
    except Exception:
        pass

    return {
        "router_reachable": router_reachable,
        "current_node": current_node,
        "node_monitor": {
            "last_modified": _last_modified(f"{LOG_DIR}/node_monitor.log"),
            "size_kb": _file_size_kb(f"{LOG_DIR}/node_monitor.log"),
            "recent_lines": node_log,
        },
        "network_check": {
            "last_modified": _last_modified(f"{LOG_DIR}/network_check.log"),
            "size_kb": _file_size_kb(f"{LOG_DIR}/network_check.log"),
            "recent_lines": network_log,
        },
    }


def get_cron_status() -> dict:
    files = {
        "node_monitor":     f"{LOG_DIR}/node_monitor.log",
        "network_check":    f"{LOG_DIR}/network_check.log",
        "daily_check":      f"{LOG_DIR}/daily_check.log",
        "chatdev_backend":  f"{LOG_DIR}/chatdev_backend.log",
        "chatdev_frontend": f"{LOG_DIR}/chatdev_frontend.log",
        "qc_assistant":     f"{LOG_DIR}/qc_assistant.log",
    }
    result = {}
    for key, path in files.items():
        result[key] = {
            "last_modified": _last_modified(path),
            "size_kb": _file_size_kb(path),
            "exists": os.path.exists(path),
        }
    return result
