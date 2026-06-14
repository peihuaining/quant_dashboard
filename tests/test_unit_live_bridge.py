"""单元测试 — live_bridge.py

覆盖：命令白名单校验 / run_live_structured 文本解析逻辑 / 超时与异常处理
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from live_bridge import (
    run_live_cmd, run_live_structured,
    ALLOWED_CMDS, FORBIDDEN_CMDS,
)

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

MOCK_STATUS_BULL = """\
🔧 QC助手初始化完成 (用户ID: 248276)
API调用成功: req_xxx - live/list - 状态码: 200 - 耗时: 1.1s

============================================================
实盘会话状态（共 1 个运行中）
============================================================
  项目 ID : 29000050  (实盘目标)
  会话 ID : L-fd306a0df5070ba71857ab2d69764532
  名称    : DualKLossControlRealTrade_v3_1_250818
  状态    : Running
  启动时间: 2026-06-07 23:10:23

Regime 状态: BULL（来自 RuntimeStatistics）
"""

MOCK_OBJ_BULL = """\
============================================================
实盘运行时统计（项目 29000050）
============================================================

  RuntimeStatistics（含策略自定义字段）:
    Equity: $117,135.06
    Fees: -$41.19
    Holdings: $123,279.19
    Net Profit: $-3,526.22
    Probabilistic Sharpe Ratio: 0%
    Regime: BULL
    Return: -0.79 %
    Unrealized: $14,776.71
    Volume: $93,311.67
"""

MOCK_STATUS_BEAR = MOCK_STATUS_BULL.replace("BULL", "BEAR")
MOCK_OBJ_BEAR   = MOCK_OBJ_BULL.replace("BULL", "BEAR")


def _make_mock_cmd(status_output=MOCK_STATUS_BULL, obj_output=MOCK_OBJ_BULL,
                   returncode=0):
    """生成 run_live_cmd 的 mock side_effect"""
    async def _mock(cmd, *args):
        if cmd == "status":
            return {"output": status_output, "stderr": "", "returncode": returncode}
        return {"output": obj_output, "stderr": "", "returncode": returncode}
    return _mock


# ──────────────────────────────────────────────────────────────────────────────
# 白名单 / 黑名单
# ──────────────────────────────────────────────────────────────────────────────

class TestCommandWhitelist:
    def test_allowed_cmds_contains_read_only_ops(self):
        assert {"status", "logs", "orders", "objectstore"} <= ALLOWED_CMDS

    def test_forbidden_cmds_blocks_destructive_ops(self):
        assert "compile" in FORBIDDEN_CMDS
        assert "deploy" in FORBIDDEN_CMDS

    def test_run_live_cmd_rejects_forbidden(self):
        with pytest.raises(AssertionError, match="forbidden"):
            asyncio.run(run_live_cmd("compile"))

    def test_run_live_cmd_rejects_unknown(self):
        with pytest.raises(AssertionError, match="forbidden"):
            asyncio.run(run_live_cmd("rm -rf /"))

    def test_run_live_cmd_rejects_empty_string(self):
        with pytest.raises(AssertionError):
            asyncio.run(run_live_cmd(""))


# ──────────────────────────────────────────────────────────────────────────────
# run_live_structured — session 解析
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuredSessionParsing:
    def _run(self, status=MOCK_STATUS_BULL, obj=MOCK_OBJ_BULL):
        with patch("live_bridge.run_live_cmd", side_effect=_make_mock_cmd(status, obj)):
            return asyncio.run(run_live_structured())

    def test_returns_expected_keys(self):
        r = self._run()
        assert set(r.keys()) >= {"session", "regime", "runtime_stats", "errors"}

    def test_project_id_parsed(self):
        r = self._run()
        assert r["session"]["project_id"] == "29000050"

    def test_session_id_parsed(self):
        r = self._run()
        assert r["session"]["session_id"] == "L-fd306a0df5070ba71857ab2d69764532"

    def test_strategy_name_parsed(self):
        r = self._run()
        assert "DualKLoss" in r["session"].get("name", "")

    def test_status_running_parsed(self):
        r = self._run()
        assert r["session"]["status"] == "Running"

    def test_launched_parsed(self):
        r = self._run()
        assert "2026-06-07" in r["session"].get("launched", "")


# ──────────────────────────────────────────────────────────────────────────────
# run_live_structured — Regime 解析
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuredRegimeParsing:
    def _run(self, status=MOCK_STATUS_BULL, obj=MOCK_OBJ_BULL):
        with patch("live_bridge.run_live_cmd", side_effect=_make_mock_cmd(status, obj)):
            return asyncio.run(run_live_structured())

    def test_bull_regime_parsed(self):
        assert self._run()["regime"] == "BULL"

    def test_bear_regime_parsed(self):
        r = self._run(status=MOCK_STATUS_BEAR, obj=MOCK_OBJ_BEAR)
        assert r["regime"] == "BEAR"

    def test_regime_not_in_runtime_stats(self):
        r = self._run()
        assert "Regime" not in r["runtime_stats"]

    def test_regime_from_status_takes_priority(self):
        """status 里的 Regime 应优先于 objectstore 里的"""
        status_bull = MOCK_STATUS_BULL  # BULL
        obj_bear    = MOCK_OBJ_BEAR     # BEAR
        r = self._run(status=status_bull, obj=obj_bear)
        assert r["regime"] == "BULL"


# ──────────────────────────────────────────────────────────────────────────────
# run_live_structured — runtime_stats 解析
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuredRuntimeStats:
    def _run(self):
        with patch("live_bridge.run_live_cmd", side_effect=_make_mock_cmd()):
            return asyncio.run(run_live_structured())

    def test_equity_parsed(self):
        assert self._run()["runtime_stats"]["Equity"] == "$117,135.06"

    def test_holdings_parsed(self):
        assert self._run()["runtime_stats"]["Holdings"] == "$123,279.19"

    def test_net_profit_parsed(self):
        assert self._run()["runtime_stats"]["Net Profit"] == "$-3,526.22"

    def test_unrealized_parsed(self):
        assert self._run()["runtime_stats"]["Unrealized"] == "$14,776.71"

    def test_fees_parsed(self):
        assert self._run()["runtime_stats"]["Fees"] == "-$41.19"

    def test_return_parsed(self):
        assert self._run()["runtime_stats"]["Return"] == "-0.79 %"


# ──────────────────────────────────────────────────────────────────────────────
# run_live_structured — 异常 / 空输出处理
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuredEdgeCases:
    def test_empty_output_returns_safe_defaults(self):
        async def empty_cmd(cmd, *args):
            return {"output": "", "stderr": "timeout", "returncode": -1}

        with patch("live_bridge.run_live_cmd", side_effect=empty_cmd):
            r = asyncio.run(run_live_structured())

        assert r["regime"] is None
        assert r["session"] == {}
        assert r["runtime_stats"] == {}

    def test_partial_output_no_crash(self):
        async def partial_cmd(cmd, *args):
            if cmd == "status":
                return {"output": "项目 ID : 29000050", "stderr": "", "returncode": 0}
            return {"output": "", "stderr": "", "returncode": 0}

        with patch("live_bridge.run_live_cmd", side_effect=partial_cmd):
            r = asyncio.run(run_live_structured())

        assert r["session"].get("project_id") == "29000050"
        assert r["runtime_stats"] == {}

    def test_errors_field_contains_stderr(self):
        async def err_cmd(cmd, *args):
            return {"output": "", "stderr": "Connection refused", "returncode": 1}

        with patch("live_bridge.run_live_cmd", side_effect=err_cmd):
            r = asyncio.run(run_live_structured())

        assert "Connection refused" in r["errors"]["status"]
        assert "Connection refused" in r["errors"]["objectstore"]

    def test_no_regime_in_output_returns_none(self):
        async def no_regime_cmd(cmd, *args):
            return {"output": "Some output without regime info", "stderr": "", "returncode": 0}

        with patch("live_bridge.run_live_cmd", side_effect=no_regime_cmd):
            r = asyncio.run(run_live_structured())

        assert r["regime"] is None
