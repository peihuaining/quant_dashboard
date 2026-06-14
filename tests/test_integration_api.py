"""集成测试 — Quant Dashboard API（需要服务运行在 127.0.0.1:9001）

覆盖：所有 REST 端点 / 边界条件 / 安全限制 / 前端渲染
"""
import pytest
import httpx

BASE_URL = "http://127.0.0.1:9001"
pytestmark = pytest.mark.integration


# ──────────────────────────────────────────────────────────────────────────────
# /api/health
# ──────────────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200(self, api):
        assert api.get("/api/health").status_code == 200

    def test_status_ok(self, api):
        assert api.get("/api/health").json()["status"] == "ok"

    def test_backtest_count_positive(self, api):
        data = api.get("/api/health").json()
        assert data["backtest_count"] > 0

    def test_wft_experiment_count_positive(self, api):
        data = api.get("/api/health").json()
        assert data["wft_experiment_count"] > 0

    def test_has_timestamp(self, api):
        data = api.get("/api/health").json()
        assert "timestamp" in data
        assert "T" in data["timestamp"]  # ISO format


# ──────────────────────────────────────────────────────────────────────────────
# /api/backtests
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestList:
    def test_returns_200(self, api):
        assert api.get("/api/backtests").status_code == 200

    def test_has_items_and_total(self, api):
        data = api.get("/api/backtests").json()
        assert "items" in data
        assert "total" in data

    def test_total_matches_items_count(self, api):
        data = api.get("/api/backtests").json()
        assert data["total"] == len(data["items"])

    def test_total_greater_than_80(self, api):
        assert api.get("/api/backtests").json()["total"] > 80

    def test_filter_by_group_phase23(self, api):
        data = api.get("/api/backtests?group=phase23").json()
        for item in data["items"]:
            assert item["group"] == "phase23"

    def test_filter_by_group_all_returns_everything(self, api):
        total_all = api.get("/api/backtests").json()["total"]
        total_filtered = api.get("/api/backtests?group=all").json()["total"]
        assert total_all == total_filtered

    def test_filter_by_unknown_group_returns_empty(self, api):
        data = api.get("/api/backtests?group=nonexistent_group_xyz").json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_search_by_name(self, api):
        data = api.get("/api/backtests?name=phase1").json()
        for item in data["items"]:
            assert "phase1" in item["name"].lower()

    def test_items_sorted_newest_first(self, api):
        items = api.get("/api/backtests").json()["items"]
        dates = [x["created"] for x in items if x["created"]]
        assert dates == sorted(dates, reverse=True)

    def test_each_item_has_backtest_id(self, api):
        items = api.get("/api/backtests").json()["items"]
        for item in items:
            assert "backtestId" in item
            assert item["backtestId"]


# ──────────────────────────────────────────────────────────────────────────────
# /api/backtests/{id}
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestDetail:
    def test_returns_200_for_valid_id(self, api, first_backtest_id):
        assert api.get(f"/api/backtests/{first_backtest_id}").status_code == 200

    def test_has_required_fields(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}").json()
        for field in ["backtestId", "name", "statistics", "status"]:
            assert field in data

    def test_statistics_is_dict(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}").json()
        assert isinstance(data["statistics"], dict)

    def test_returns_404_for_invalid_id(self, api):
        r = api.get("/api/backtests/nonexistent_id_zzz999")
        assert r.status_code == 404

    def test_404_body_has_detail(self, api):
        r = api.get("/api/backtests/nonexistent")
        assert "detail" in r.json()

    def test_date_fields_present(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}").json()
        assert "backtestStart" in data
        assert "backtestEnd" in data


# ──────────────────────────────────────────────────────────────────────────────
# /api/backtests/{id}/trades
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestTrades:
    def test_returns_200(self, api, first_backtest_id):
        r = api.get(f"/api/backtests/{first_backtest_id}/trades")
        assert r.status_code == 200

    def test_has_trades_and_total(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/trades").json()
        assert "trades" in data
        assert "total" in data

    def test_default_limit_50(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/trades").json()
        assert len(data["trades"]) <= 50

    def test_custom_limit(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/trades?limit=10").json()
        assert len(data["trades"]) <= 10

    def test_pagination_skip(self, api, first_backtest_id):
        r1 = api.get(f"/api/backtests/{first_backtest_id}/trades?skip=0&limit=5").json()
        r2 = api.get(f"/api/backtests/{first_backtest_id}/trades?skip=5&limit=5").json()
        ids1 = [t.get("id") for t in r1["trades"]]
        ids2 = [t.get("id") for t in r2["trades"]]
        assert ids1 != ids2 or r1["total"] <= 5  # skip worked or very few trades

    def test_trade_items_have_symbol(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/trades").json()
        for t in data["trades"]:
            assert "symbol" in t

    def test_invalid_id_returns_404(self, api):
        assert api.get("/api/backtests/zzz_invalid/trades").status_code == 404

    def test_limit_over_500_rejected(self, api, first_backtest_id):
        r = api.get(f"/api/backtests/{first_backtest_id}/trades?limit=9999")
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# /api/backtests/{id}/charts
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestCharts:
    def test_returns_200(self, api, first_backtest_id):
        assert api.get(f"/api/backtests/{first_backtest_id}/charts").status_code == 200

    def test_has_equity_and_trade_curve(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/charts").json()
        assert "equity" in data
        assert "trade_curve" in data

    def test_equity_points_have_x_y(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/charts").json()
        for pt in data["equity"]:
            assert "x" in pt and "y" in pt

    def test_equity_starts_at_one(self, api, first_backtest_id):
        data = api.get(f"/api/backtests/{first_backtest_id}/charts").json()
        equity = data["equity"]
        if equity:
            assert abs(equity[0]["y"] - 1.0) < 0.01

    def test_invalid_id_returns_404(self, api):
        assert api.get("/api/backtests/zzz_invalid/charts").status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# /api/compare
# ──────────────────────────────────────────────────────────────────────────────

class TestCompare:
    @pytest.fixture
    def two_ids(self, api):
        items = api.get("/api/backtests").json()["items"]
        return items[0]["backtestId"], items[1]["backtestId"]

    def test_returns_200(self, api, two_ids):
        ids = ",".join(two_ids)
        assert api.get(f"/api/compare?ids={ids}").status_code == 200

    def test_returns_correct_count(self, api, two_ids):
        ids = ",".join(two_ids)
        data = api.get(f"/api/compare?ids={ids}").json()
        assert len(data["items"]) == 2

    def test_three_ids_capped(self, api):
        items = api.get("/api/backtests").json()["items"][:4]
        ids = ",".join(i["backtestId"] for i in items)
        data = api.get(f"/api/compare?ids={ids}").json()
        assert len(data["items"]) <= 3  # capped at 3

    def test_invalid_ids_excluded(self, api):
        ids = "invalid_id_xyz,another_bad_id"
        data = api.get(f"/api/compare?ids={ids}").json()
        assert data["items"] == []

    def test_missing_ids_param_returns_422(self, api):
        assert api.get("/api/compare").status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# /api/wft
# ──────────────────────────────────────────────────────────────────────────────

class TestWFT:
    def test_returns_200(self, api):
        assert api.get("/api/wft").status_code == 200

    def test_has_experiments(self, api):
        data = api.get("/api/wft").json()
        assert "experiments" in data

    def test_experiments_nonempty(self, api):
        data = api.get("/api/wft").json()
        assert len(data["experiments"]) > 0

    def test_experiment_has_required_fields(self, api):
        experiments = api.get("/api/wft").json()["experiments"]
        for exp in experiments:
            for field in ["name", "windows", "avg_sharpe", "positive_windows", "total_windows"]:
                assert field in exp

    def test_windows_are_lists(self, api):
        experiments = api.get("/api/wft").json()["experiments"]
        for exp in experiments:
            assert isinstance(exp["windows"], list)


# ──────────────────────────────────────────────────────────────────────────────
# /api/phase23
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase23:
    def test_returns_200(self, api):
        assert api.get("/api/phase23").status_code == 200

    def test_has_configs(self, api):
        data = api.get("/api/phase23").json()
        assert "configs" in data

    def test_configs_have_required_fields(self, api):
        configs = api.get("/api/phase23").json()["configs"]
        for cfg in configs:
            assert "name" in cfg
            assert "sharpe" in cfg
            assert "auditPassed" in cfg


# ──────────────────────────────────────────────────────────────────────────────
# /api/live/*
# ──────────────────────────────────────────────────────────────────────────────

class TestLiveRaw:
    def test_status_returns_200(self, api):
        assert api.get("/api/live/status").status_code == 200

    def test_status_has_output(self, api):
        data = api.get("/api/live/status").json()
        assert "output" in data
        assert len(data["output"]) > 0

    def test_orders_returns_200(self, api):
        assert api.get("/api/live/orders?n=5").status_code == 200

    def test_orders_has_output(self, api):
        data = api.get("/api/live/orders?n=5").json()
        assert "output" in data

    def test_logs_returns_200(self, api):
        assert api.get("/api/live/logs?hours=1").status_code == 200

    def test_logs_has_output(self, api):
        data = api.get("/api/live/logs?hours=1").json()
        assert "output" in data

    def test_objectstore_returns_200(self, api):
        assert api.get("/api/live/objectstore").status_code == 200

    def test_logs_hours_validation(self, api):
        # hours > 24 should be rejected
        r = api.get("/api/live/logs?hours=999")
        assert r.status_code == 422


class TestLiveStructured:
    @pytest.fixture(autouse=True, scope="class")
    def fetch(self, api):
        r = api.get("/api/live/structured")
        assert r.status_code == 200
        self.__class__.data = r.json()

    def test_has_session_key(self):
        assert "session" in self.data

    def test_has_regime_key(self):
        assert "regime" in self.data

    def test_has_runtime_stats(self):
        assert "runtime_stats" in self.data

    def test_has_errors_key(self):
        assert "errors" in self.data

    def test_session_has_project_id(self):
        assert self.data["session"].get("project_id") == "29000050"

    def test_session_has_session_id(self):
        sid = self.data["session"].get("session_id", "")
        assert sid.startswith("L-")

    def test_session_status_is_running(self):
        assert self.data["session"].get("status") == "Running"

    def test_regime_is_bull_or_bear(self):
        assert self.data["regime"] in ("BULL", "BEAR", None)

    def test_regime_not_in_runtime_stats(self):
        assert "Regime" not in self.data["runtime_stats"]

    def test_equity_present(self):
        assert "Equity" in self.data["runtime_stats"]
        assert "$" in self.data["runtime_stats"]["Equity"]

    def test_net_profit_present(self):
        assert "Net Profit" in self.data["runtime_stats"]

    def test_holdings_present(self):
        assert "Holdings" in self.data["runtime_stats"]


# ──────────────────────────────────────────────────────────────────────────────
# /api/infra/*
# ──────────────────────────────────────────────────────────────────────────────

class TestInfraGit:
    @pytest.fixture(autouse=True, scope="class")
    def fetch(self, api):
        r = api.get("/api/infra/git")
        assert r.status_code == 200
        self.__class__.data = r.json()

    def test_has_current_key(self):
        assert "current" in self.data

    def test_current_is_string(self):
        assert isinstance(self.data["current"], str)

    def test_has_branches_list(self):
        assert isinstance(self.data["branches"], list)
        assert len(self.data["branches"]) > 0

    def test_exactly_one_current_branch(self):
        current = [b for b in self.data["branches"] if b["current"]]
        assert len(current) == 1

    def test_live_branch_marked(self):
        live = [b for b in self.data["branches"] if b.get("is_live")]
        assert len(live) == 1
        assert live[0]["name"] == "feature/live-ema50-correction"

    def test_has_recent_commits(self):
        assert isinstance(self.data["recent_commits"], list)
        assert len(self.data["recent_commits"]) > 0


class TestInfraCron:
    @pytest.fixture(autouse=True, scope="class")
    def fetch(self, api):
        r = api.get("/api/infra/cron")
        assert r.status_code == 200
        self.__class__.data = r.json()

    def test_has_node_monitor(self):
        assert "node_monitor" in self.data

    def test_has_network_check(self):
        assert "network_check" in self.data

    def test_has_daily_check(self):
        assert "daily_check" in self.data

    def test_size_kb_nonnegative(self):
        for val in self.data.values():
            assert val["size_kb"] >= 0

    def test_node_monitor_exists(self):
        assert self.data["node_monitor"]["exists"] is True


class TestInfraNetwork:
    @pytest.fixture(autouse=True, scope="class")
    def fetch(self, api):
        r = api.get("/api/infra/network", timeout=15.0)
        assert r.status_code == 200
        self.__class__.data = r.json()

    def test_has_router_reachable(self):
        assert "router_reachable" in self.data
        assert isinstance(self.data["router_reachable"], bool)

    def test_has_current_node(self):
        assert "current_node" in self.data

    def test_has_node_monitor_info(self):
        nm = self.data["node_monitor"]
        assert "last_modified" in nm
        assert "size_kb" in nm
        assert "recent_lines" in nm

    def test_has_network_check_info(self):
        nc = self.data["network_check"]
        assert "last_modified" in nc
        assert "size_kb" in nc

    def test_when_reachable_has_node_id(self):
        if self.data["router_reachable"]:
            node = self.data["current_node"]
            assert node is not None
            assert len(node.get("id", "")) > 0
            assert len(node.get("remarks", "")) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 前端 HTML
# ──────────────────────────────────────────────────────────────────────────────

class TestFrontend:
    def test_root_returns_200(self, api):
        assert api.get("/").status_code == 200

    def test_content_type_is_html(self, api):
        r = api.get("/")
        assert "text/html" in r.headers.get("content-type", "")

    def test_all_tabs_present(self, api):
        html = api.get("/").text
        for tab in ["回测", "WFT", "Phase-23", "实盘", "基础设施"]:
            assert tab in html, f"Tab '{tab}' not found in HTML"

    def test_alpine_js_loaded(self, api):
        assert "alpinejs" in api.get("/").text

    def test_chart_js_loaded(self, api):
        assert "chart.js" in api.get("/").text

    def test_api_base_url_set(self, api):
        assert "const API = ''" in api.get("/").text

    def test_live_kpis_defined(self, api):
        html = api.get("/").text
        assert "liveKpis" in html

    def test_infra_tab_logic_present(self, api):
        html = api.get("/").text
        assert "loadInfra" in html
        assert "infraData" in html

    def test_auto_refresh_toggle_present(self, api):
        assert "liveAutoRefresh" in api.get("/").text


# ──────────────────────────────────────────────────────────────────────────────
# 安全测试
# ──────────────────────────────────────────────────────────────────────────────

class TestSecurity:
    DANGEROUS_PATHS = [
        "/api/live/compile",
        "/api/live/deploy",
        "/api/live/backtest",
        "/api/live/upload",
        "/api/live/delete",
    ]

    def test_no_dangerous_endpoints_accessible(self, api):
        for path in self.DANGEROUS_PATHS:
            r = api.get(path)
            assert r.status_code in (404, 405), \
                f"Dangerous endpoint {path} is accessible (status {r.status_code})"

    def test_openapi_docs_available(self, api):
        # Docs endpoint is fine — readonly
        r = api.get("/api/docs")
        assert r.status_code == 200

    def test_post_to_read_endpoints_rejected(self, api):
        # All our endpoints are GET-only
        r = api.post("/api/backtests")
        assert r.status_code in (405, 422)

    def test_skip_negative_rejected(self, api, first_backtest_id):
        r = api.get(f"/api/backtests/{first_backtest_id}/trades?skip=-1")
        assert r.status_code == 422

    def test_limit_zero_rejected(self, api, first_backtest_id):
        r = api.get(f"/api/backtests/{first_backtest_id}/trades?limit=0")
        assert r.status_code == 422
