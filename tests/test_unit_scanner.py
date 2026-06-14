"""单元测试 — scanner.py

覆盖：_parse_group / _safe_float / scan_backtests / get_backtest_detail /
      get_trades / get_charts / scan_wft / scan_phase23
"""
import pytest
import os
import json
import tempfile
from unittest.mock import patch

from scanner import (
    _parse_group, _safe_float,
    scan_backtests, get_backtest_detail, get_trades, get_charts,
    scan_wft, scan_phase23,
)

# ──────────────────────────────────────────────────────────────────────────────
# _parse_group
# ──────────────────────────────────────────────────────────────────────────────

class TestParseGroup:
    def test_bt_prefix_is_early(self):
        assert _parse_group("BT_20230101_something") == "early"

    def test_bt_phase1_prefix(self):
        assert _parse_group("bt_phase1_20260101") == "phase1"

    def test_bt_p1_prefix(self):
        assert _parse_group("bt_p1_20260101") == "phase1"

    def test_bt_p23_prefix(self):
        assert _parse_group("bt_p23_config_a") == "phase23"

    def test_wft_configE(self):
        assert _parse_group("wft_ConfigE_20260101") == "wft_configE"

    def test_wft_configF(self):
        assert _parse_group("wft_ConfigF_20260101") == "wft_configF"

    def test_wft_capm3m(self):
        assert _parse_group("wft_capm3m_20260101") == "wft_capm3m"

    def test_wft_dynamic(self):
        assert _parse_group("wft_dynamic_20260101") == "wft_dynamic"

    def test_unknown_name_is_other(self):
        assert _parse_group("random_experiment_xyz") == "other"

    def test_empty_string_is_other(self):
        assert _parse_group("") == "other"


# ──────────────────────────────────────────────────────────────────────────────
# _safe_float
# ──────────────────────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_plain_float(self):
        assert _safe_float(1.5) == 1.5

    def test_integer(self):
        assert _safe_float(42) == 42.0

    def test_string_with_percent(self):
        assert _safe_float("45.3%") == 45.3

    def test_string_with_dollar(self):
        assert _safe_float("$1,234.56") == 1234.56

    def test_negative_string(self):
        assert _safe_float("-0.79 %") == pytest.approx(-0.79)

    def test_zero(self):
        assert _safe_float("0") == 0.0

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_not_a_number_returns_none(self):
        assert _safe_float("N/A") is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_dict_returns_none(self):
        assert _safe_float({}) is None


# ──────────────────────────────────────────────────────────────────────────────
# scan_backtests  (uses real DATA_DIR files)
# ──────────────────────────────────────────────────────────────────────────────

class TestScanBacktests:
    @pytest.fixture(autouse=True)
    def run_scan(self):
        self.result = scan_backtests()

    def test_returns_nonempty_list(self):
        assert isinstance(self.result, list)
        assert len(self.result) > 0

    def test_each_item_has_required_fields(self):
        required = ["backtestId", "name", "group", "created",
                    "sharpe", "annualReturn", "drawdown", "status"]
        for item in self.result:
            for field in required:
                assert field in item, f"Missing field '{field}' in {item.get('name')}"

    def test_sorted_newest_first(self):
        dates = [x["created"] for x in self.result if x["created"]]
        assert dates == sorted(dates, reverse=True)

    def test_group_values_are_valid(self):
        valid = {"early", "phase1", "phase23",
                 "wft_configE", "wft_configF", "wft_capm3m", "wft_dynamic", "other"}
        for item in self.result:
            assert item["group"] in valid, f"Unknown group: {item['group']}"

    def test_sharpe_is_float_or_none(self):
        for item in self.result:
            assert item["sharpe"] is None or isinstance(item["sharpe"], float)

    def test_no_duplicate_backtest_ids(self):
        ids = [x["backtestId"] for x in self.result]
        assert len(ids) == len(set(ids)), "Duplicate backtestId found"

    def test_total_count_matches_expectation(self):
        # We know there are 83 backtest dirs; allow some flexibility
        assert len(self.result) >= 80


# ──────────────────────────────────────────────────────────────────────────────
# get_backtest_detail
# ──────────────────────────────────────────────────────────────────────────────

class TestGetBacktestDetail:
    def test_valid_id_returns_dict(self):
        items = scan_backtests()
        bid = items[0]["backtestId"]
        detail = get_backtest_detail(bid)
        assert detail is not None
        assert isinstance(detail, dict)

    def test_result_has_full_result_and_portfolio_statistics(self):
        bid = scan_backtests()[0]["backtestId"]
        detail = get_backtest_detail(bid)
        assert "full_result" in detail
        assert "portfolio_statistics" in detail
        assert "dirPath" in detail

    def test_full_result_has_backtest_id(self):
        bid = scan_backtests()[0]["backtestId"]
        detail = get_backtest_detail(bid)
        fr = detail["full_result"]
        assert "backtestId" in fr or "name" in fr

    def test_invalid_id_returns_none(self):
        assert get_backtest_detail("nonexistent_id_zzz999") is None

    def test_partial_id_not_matched(self):
        bid = scan_backtests()[0]["backtestId"]
        # Truncate ID — should not match
        assert get_backtest_detail(bid[:5]) is None


# ──────────────────────────────────────────────────────────────────────────────
# get_trades
# ──────────────────────────────────────────────────────────────────────────────

class TestGetTrades:
    def test_valid_id_returns_list(self):
        bid = scan_backtests()[0]["backtestId"]
        trades = get_trades(bid)
        assert isinstance(trades, list)

    def test_trade_items_have_expected_shape(self):
        bid = scan_backtests()[0]["backtestId"]
        trades = get_trades(bid)
        if trades:  # skip if backtest has no trades
            t = trades[0]
            assert any(k in t for k in ["entryTime", "exitTime", "profitLoss",
                                         "symbols", "id"])

    def test_invalid_id_returns_none(self):
        assert get_trades("nonexistent_id_zzz") is None


# ──────────────────────────────────────────────────────────────────────────────
# get_charts
# ──────────────────────────────────────────────────────────────────────────────

class TestGetCharts:
    def test_returns_dict_with_equity_and_trade_curve(self):
        bid = scan_backtests()[0]["backtestId"]
        charts = get_charts(bid)
        assert charts is not None
        assert "equity" in charts
        assert "trade_curve" in charts
        assert "benchmark" in charts

    def test_equity_is_list_of_xy_points(self):
        bid = scan_backtests()[0]["backtestId"]
        charts = get_charts(bid)
        eq = charts["equity"]
        assert isinstance(eq, list)
        if eq:
            assert "x" in eq[0] and "y" in eq[0]

    def test_normalised_equity_starts_near_one(self):
        bid = scan_backtests()[0]["backtestId"]
        charts = get_charts(bid)
        eq = charts["equity"]
        if eq:
            assert abs(eq[0]["y"] - 1.0) < 0.01

    def test_trade_curve_is_list(self):
        bid = scan_backtests()[0]["backtestId"]
        charts = get_charts(bid)
        assert isinstance(charts["trade_curve"], list)

    def test_invalid_id_returns_none(self):
        assert get_charts("nonexistent_id_zzz") is None


# ──────────────────────────────────────────────────────────────────────────────
# scan_wft
# ──────────────────────────────────────────────────────────────────────────────

class TestScanWFT:
    @pytest.fixture(autouse=True)
    def run_scan(self):
        self.result = scan_wft()

    def test_returns_nonempty_list(self):
        assert isinstance(self.result, list)
        assert len(self.result) > 0

    def test_experiment_has_required_fields(self):
        required = ["name", "commit", "windows",
                    "avg_sharpe", "positive_windows", "total_windows", "multi_config"]
        for exp in self.result:
            for field in required:
                assert field in exp, f"Missing field '{field}' in experiment {exp.get('name')}"

    def test_windows_is_list(self):
        for exp in self.result:
            assert isinstance(exp["windows"], list)

    def test_window_items_have_expected_fields(self):
        for exp in self.result:
            for w in exp["windows"]:
                assert "window" in w
                assert "sharpe" in w

    def test_positive_windows_le_total_windows(self):
        for exp in self.result:
            assert exp["positive_windows"] <= exp["total_windows"]

    def test_avg_sharpe_is_float_or_none(self):
        for exp in self.result:
            assert exp["avg_sharpe"] is None or isinstance(exp["avg_sharpe"], float)


# ──────────────────────────────────────────────────────────────────────────────
# scan_phase23
# ──────────────────────────────────────────────────────────────────────────────

class TestScanPhase23:
    @pytest.fixture(autouse=True)
    def run_scan(self):
        self.result = scan_phase23()

    def test_returns_list(self):
        assert isinstance(self.result, list)

    def test_config_has_required_fields(self):
        for cfg in self.result:
            assert "name" in cfg
            assert "sharpe" in cfg
            assert "annualReturn" in cfg
            assert "drawdown" in cfg
            assert "auditPassed" in cfg

    def test_sharpe_is_numeric_or_none(self):
        for cfg in self.result:
            assert cfg["sharpe"] is None or isinstance(cfg["sharpe"], float)

    def test_audit_passed_is_bool_or_none(self):
        for cfg in self.result:
            assert cfg["auditPassed"] in (True, False, None)


# ──────────────────────────────────────────────────────────────────────────────
# scanner with corrupt / missing files (isolation via temp dir)
# ──────────────────────────────────────────────────────────────────────────────

class TestScannerRobustness:
    def test_missing_full_result_skipped(self, tmp_path):
        """目录内没有 full_result.json 时，该目录应被跳过"""
        bt_dir = tmp_path / "backtest_abc123"
        bt_dir.mkdir()
        (bt_dir / "portfolio_statistics.json").write_text("{}")

        with patch("scanner.DATA_DIR", str(tmp_path)):
            result = scan_backtests()
        assert result == []

    def test_corrupt_json_skipped(self, tmp_path):
        """full_result.json 内容损坏时，该目录应被跳过"""
        bt_dir = tmp_path / "backtest_corrupt"
        bt_dir.mkdir()
        (bt_dir / "full_result.json").write_text("NOT VALID JSON {{")

        with patch("scanner.DATA_DIR", str(tmp_path)):
            result = scan_backtests()
        assert result == []

    def test_valid_minimal_entry_included(self, tmp_path):
        """最小合法 full_result.json 应被正常解析"""
        bt_dir = tmp_path / "backtest_minimal"
        bt_dir.mkdir()
        payload = {
            "backtestId": "test_id_001",
            "name": "bt_phase1_test",
            "projectId": 30796820,
            "created": "2026-01-01T00:00:00",
            "backtestStart": "2025-01-01T00:00:00",
            "backtestEnd": "2026-01-01T00:00:00",
            "status": "Completed",
            "statistics": {"Sharpe Ratio": "1.23", "Compounding Annual Return": "25%"},
        }
        (bt_dir / "full_result.json").write_text(json.dumps(payload))

        with patch("scanner.DATA_DIR", str(tmp_path)):
            result = scan_backtests()

        assert len(result) == 1
        assert result[0]["backtestId"] == "test_id_001"
        assert result[0]["group"] == "phase1"
        assert result[0]["sharpe"] == pytest.approx(1.23)
