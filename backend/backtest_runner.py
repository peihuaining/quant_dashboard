"""一键回测触发 — 仅针对测试项目 30796820，严禁触碰实盘 29000050"""
import asyncio
import time
from typing import Optional

QC_AGENT_DIR = "/home/administrator/workspace/quantconnect_agent"
MAX_DAYS = 730
MIN_DAYS = 30

_job: Optional["BtJob"] = None


class BtJob:
    def __init__(self, days: int):
        self.days = days
        self.started_at = time.time()
        self.status = "running"   # running | done | error
        self.lines: list = []
        self.returncode: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "days": self.days,
            "elapsed": int(time.time() - self.started_at),
            "lines": self.lines[-200:],
            "returncode": self.returncode,
        }


async def _run(job: BtJob) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "qc_live_ops.py", "backtest", str(job.days),
            cwd=QC_AGENT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            job.lines.append(line)
        await proc.wait()
        job.returncode = proc.returncode
        job.status = "done" if proc.returncode == 0 else "error"
    except Exception as exc:
        job.lines.append(f"[runner error] {exc}")
        job.status = "error"


async def trigger(days: int) -> dict:
    global _job
    if _job and _job.status == "running":
        return {"error": "already_running", **_job.as_dict()}
    _job = BtJob(days)
    asyncio.create_task(_run(_job))
    return {"started": True, "days": days, "status": "running"}


def get_status() -> dict:
    if _job is None:
        return {"status": "idle", "lines": [], "elapsed": 0, "days": None, "returncode": None}
    return _job.as_dict()
