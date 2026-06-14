import asyncio
import os
import re

QC_LIVE_OPS = "/home/administrator/workspace/quantconnect_agent/qc_live_ops.py"
QC_AGENT_DIR = "/home/administrator/workspace/quantconnect_agent"

# strict whitelist — nothing outside this set can be invoked
ALLOWED_CMDS = {"status", "logs", "orders", "objectstore"}
# redundant blocklist for defence-in-depth
FORBIDDEN_CMDS = {"compile", "backtest", "deploy", "upload", "delete"}


async def run_live_cmd(cmd: str, *args: str) -> dict:
    assert cmd in ALLOWED_CMDS, f"forbidden command: {cmd!r}"
    assert cmd not in FORBIDDEN_CMDS, f"forbidden command: {cmd!r}"

    env = os.environ.copy()
    secrets_path = os.path.expanduser("~/.openclaw/secrets.env")
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()

    cmd_args = ["python3", QC_LIVE_OPS, cmd] + list(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            cwd=QC_AGENT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "output": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"output": "", "stderr": "timeout after 30s", "returncode": -1}
    except Exception as e:
        return {"output": "", "stderr": str(e), "returncode": -1}


async def run_live_structured() -> dict:
    """Run status + objectstore in parallel; return parsed structured data."""
    status_r, obj_r = await asyncio.gather(
        run_live_cmd("status"),
        run_live_cmd("objectstore"),
    )
    status_text = status_r.get("output", "")
    obj_text = obj_r.get("output", "")

    session: dict = {}
    regime: str | None = None

    for line in status_text.splitlines():
        if "项目 ID" in line:
            m = re.search(r"(\d{7,})", line)
            if m:
                session["project_id"] = m.group(1)
        elif "会话 ID" in line:
            m = re.search(r":\s*(\S+)", line)
            if m:
                session["session_id"] = m.group(1)
        elif "名称" in line and ":" in line and "🔧" not in line and "QC" not in line:
            v = line.split(":", 1)[1].strip()
            if v and len(v) > 3:
                session["name"] = v
        elif re.match(r"\s+状态\s*:", line):
            session["status"] = line.split(":", 1)[1].strip()
        elif "启动时间" in line:
            session["launched"] = line.split(":", 1)[1].strip()
        if "Regime 状态" in line:
            m = re.search(r"Regime 状态:\s*(\w+)", line)
            if m:
                regime = m.group(1)

    runtime_stats: dict = {}
    STAT_KEYS = {"Equity", "Fees", "Holdings", "Net Profit",
                 "Probabilistic Sharpe Ratio", "Regime", "Return", "Unrealized", "Volume"}
    for line in obj_text.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key in STAT_KEYS:
            runtime_stats[key] = val

    regime = regime or runtime_stats.get("Regime")
    runtime_stats.pop("Regime", None)

    return {
        "session": session,
        "regime": regime,
        "runtime_stats": runtime_stats,
        "errors": {
            "status": status_r.get("stderr", ""),
            "objectstore": obj_r.get("stderr", ""),
        },
    }
