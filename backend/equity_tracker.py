"""本地净值时序追踪 — 每次 /api/live/structured 调用时追加一条记录"""
import json
from datetime import datetime, timezone
from pathlib import Path

STORE_PATH = Path("/home/administrator/quant_stock/equity_history.json")
MAX_POINTS = 2880   # 120 天 × 24h，约 240KB


def _parse(s: str) -> float | None:
    try:
        return float(str(s or "").replace("$", "").replace(",", "").strip()) or None
    except (ValueError, TypeError):
        return None


def append(equity_str: str) -> None:
    """记录当前净值（相同分钟内只更新，不重复追加）"""
    equity = _parse(equity_str)
    if not equity:
        return
    points = load()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    if points and points[-1]["t"][:16] == now:
        points[-1]["v"] = equity           # 同分钟内更新最后一条
    else:
        points.append({"t": now, "v": equity})
    if len(points) > MAX_POINTS:
        points = points[-MAX_POINTS:]
    STORE_PATH.write_text(json.dumps(points, separators=(",", ":")))


def load() -> list:
    try:
        return json.loads(STORE_PATH.read_text()) if STORE_PATH.exists() else []
    except Exception:
        return []
