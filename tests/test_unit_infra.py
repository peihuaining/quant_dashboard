"""单元测试 — infra.py

覆盖：工具函数 / get_cron_status / get_git_info / get_network_status（含 SSH mock）
"""
import pytest
import os
import asyncio
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock

from infra import (
    _read_log_tail, _last_modified, _file_size_kb,
    get_cron_status, get_git_info, get_network_status,
    LOG_DIR, STRATEGY_DIR,
)

# ──────────────────────────────────────────────────────────────────────────────
# _read_log_tail
# ──────────────────────────────────────────────────────────────────────────────

class TestReadLogTail:
    def test_nonexistent_file_returns_empty_list(self):
        assert _read_log_tail("/nonexistent/path/file.log") == []

    def test_reads_last_n_lines(self, tmp_path):
        f = tmp_path / "test.log"
        f.write_text("\n".join(f"line {i}" for i in range(50)))
        result = _read_log_tail(str(f), lines=10)
        assert len(result) == 10
        assert "line 49" in result[-1]

    def test_fewer_lines_than_requested(self, tmp_path):
        f = tmp_path / "test.log"
        f.write_text("a\nb\nc\n")
        result = _read_log_tail(str(f), lines=30)
        assert result == ["a", "b", "c"]

    def test_filters_blank_lines(self, tmp_path):
        f = tmp_path / "test.log"
        f.write_text("line1\n\n   \nline2\n\n")
        result = _read_log_tail(str(f))
        assert result == ["line1", "line2"]

    def test_empty_file_returns_empty_list(self, tmp_path):
        f = tmp_path / "empty.log"
        f.write_text("")
        assert _read_log_tail(str(f)) == []


# ──────────────────────────────────────────────────────────────────────────────
# _last_modified
# ──────────────────────────────────────────────────────────────────────────────

class TestLastModified:
    def test_nonexistent_file_returns_none(self):
        assert _last_modified("/nonexistent/file.log") is None

    def test_existing_file_returns_formatted_string(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("x")
        result = _last_modified(str(f))
        assert result is not None
        # Format: YYYY-MM-DD HH:MM:SS
        assert len(result) == 19
        assert result[4] == "-" and result[7] == "-"
        assert result[10] == " " and result[13] == ":"


# ──────────────────────────────────────────────────────────────────────────────
# _file_size_kb
# ──────────────────────────────────────────────────────────────────────────────

class TestFileSizeKb:
    def test_nonexistent_returns_zero(self):
        assert _file_size_kb("/nonexistent/file") == 0.0

    def test_empty_file_is_zero_kb(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert _file_size_kb(str(f)) == 0.0

    def test_known_size_one_kb(self, tmp_path):
        f = tmp_path / "one_kb.bin"
        f.write_bytes(b"x" * 1024)
        assert _file_size_kb(str(f)) == 1.0

    def test_returns_float(self, tmp_path):
        f = tmp_path / "t.bin"
        f.write_bytes(b"x" * 512)
        result = _file_size_kb(str(f))
        assert isinstance(result, float)
        assert result == 0.5


# ──────────────────────────────────────────────────────────────────────────────
# get_cron_status
# ──────────────────────────────────────────────────────────────────────────────

class TestGetCronStatus:
    EXPECTED_KEYS = [
        "node_monitor", "network_check", "daily_check",
        "chatdev_backend", "chatdev_frontend", "qc_assistant",
    ]

    def test_returns_all_expected_keys(self):
        result = get_cron_status()
        for key in self.EXPECTED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_each_entry_has_required_subfields(self):
        result = get_cron_status()
        for key, val in result.items():
            assert "last_modified" in val, f"{key} missing last_modified"
            assert "size_kb" in val, f"{key} missing size_kb"
            assert "exists" in val, f"{key} missing exists"

    def test_exists_field_is_bool(self):
        result = get_cron_status()
        for val in result.values():
            assert isinstance(val["exists"], bool)

    def test_size_kb_is_nonnegative(self):
        result = get_cron_status()
        for val in result.values():
            assert val["size_kb"] >= 0.0

    def test_actual_log_files_detected(self):
        result = get_cron_status()
        # We know node_monitor.log exists in the data dir
        assert result["node_monitor"]["exists"] is True


# ──────────────────────────────────────────────────────────────────────────────
# get_git_info  (使用真实 git 仓库)
# ──────────────────────────────────────────────────────────────────────────────

class TestGetGitInfo:
    @pytest.fixture(autouse=True)
    def run(self):
        self.result = asyncio.run(get_git_info())

    def test_returns_expected_top_level_keys(self):
        assert "current" in self.result
        assert "branches" in self.result
        assert "recent_commits" in self.result

    def test_current_branch_is_string(self):
        assert isinstance(self.result["current"], str)
        assert len(self.result["current"]) > 0

    def test_branches_is_nonempty_list(self):
        branches = self.result["branches"]
        assert isinstance(branches, list)
        assert len(branches) > 0

    def test_each_branch_has_required_fields(self):
        for br in self.result["branches"]:
            assert "name" in br
            assert "commit" in br
            assert "current" in br
            assert "is_live" in br

    def test_exactly_one_current_branch(self):
        current_branches = [b for b in self.result["branches"] if b["current"]]
        assert len(current_branches) == 1

    def test_current_branch_name_matches_current_field(self):
        current_branches = [b for b in self.result["branches"] if b["current"]]
        assert current_branches[0]["name"] == self.result["current"]

    def test_live_branch_marked(self):
        live_branches = [b for b in self.result["branches"] if b["is_live"]]
        assert len(live_branches) == 1
        assert live_branches[0]["name"] == "feature/live-ema50-correction"

    def test_recent_commits_is_list(self):
        assert isinstance(self.result["recent_commits"], list)

    def test_recent_commits_have_hash_prefix(self):
        for c in self.result["recent_commits"]:
            parts = c.split()
            assert len(parts[0]) == 7  # short hash is 7 chars

    def test_git_failure_returns_safe_defaults(self):
        """当 git 命令失败时，返回安全的空结构"""
        async def fail_proc(*args, **kwargs):
            raise Exception("git not found")

        with patch("asyncio.create_subprocess_exec", side_effect=Exception("git not found")):
            r = asyncio.run(get_git_info())

        assert r["current"] is None
        assert r["branches"] == []
        assert r["recent_commits"] == []
        assert "error" in r


# ──────────────────────────────────────────────────────────────────────────────
# get_network_status
# ──────────────────────────────────────────────────────────────────────────────

class TestGetNetworkStatus:
    @pytest.fixture(autouse=True)
    def run(self):
        self.result = asyncio.run(get_network_status())

    def test_returns_required_keys(self):
        for key in ["router_reachable", "current_node", "node_monitor", "network_check"]:
            assert key in self.result

    def test_node_monitor_struct(self):
        nm = self.result["node_monitor"]
        assert "last_modified" in nm
        assert "size_kb" in nm
        assert "recent_lines" in nm
        assert isinstance(nm["recent_lines"], list)

    def test_network_check_struct(self):
        nc = self.result["network_check"]
        assert "last_modified" in nc
        assert "size_kb" in nc
        assert "recent_lines" in nc

    def test_router_reachable_is_bool(self):
        assert isinstance(self.result["router_reachable"], bool)

    def test_when_reachable_node_has_id_and_remarks(self):
        if self.result["router_reachable"]:
            node = self.result["current_node"]
            assert node is not None
            assert "id" in node
            assert "remarks" in node
            assert len(node["id"]) > 0

    def test_ssh_exception_sets_unreachable(self):
        """SSH 异常时，router_reachable 应为 False"""
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("refused")):
            r = asyncio.run(get_network_status())

        assert r["router_reachable"] is False
        assert r["current_node"] is None

    def test_ssh_timeout_sets_unreachable(self):
        """SSH 超时时，router_reachable 应为 False"""
        async def mock_proc(*args, **kwargs):
            mock = MagicMock()
            async def mock_communicate():
                raise asyncio.TimeoutError()
            mock.communicate = mock_communicate
            return mock

        with patch("asyncio.create_subprocess_exec", side_effect=asyncio.TimeoutError):
            r = asyncio.run(get_network_status())

        assert r["router_reachable"] is False

    def test_ssh_empty_output_sets_unreachable(self):
        """SSH 返回空输出时（无法匹配 NID），router_reachable 应为 False"""
        async def mock_proc(*args, **kwargs):
            mock = MagicMock()
            async def mock_communicate():
                return (b"", b"")
            mock.communicate = mock_communicate
            return mock

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc()):
            # We need to create the proc properly
            pass

        # Test directly with empty stdout
        async def run_test():
            proc_mock = AsyncMock()
            proc_mock.communicate = AsyncMock(return_value=(b"", b""))

            with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
                return await get_network_status()

        r = asyncio.run(run_test())
        assert r["router_reachable"] is False
