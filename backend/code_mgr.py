"""代码分支管理 — git diff / commits / 分支对比"""
import asyncio
import re
from typing import Optional

STRATEGY_DIR = "/opt/lean-trading/lean-workspace/MyStrategy"
BASE_BRANCH = "master"
LIVE_BRANCH = "feature/live-ema50-correction"

ALLOWED_FILES = {
    "main.py", "alpha.py", "dailytradeprocessor.py",
    "ordermanage.py", "dkreporter.py", "repo.py",
    "telegramrobot.py", "config.py", "universe.py",
}

_BRANCH_RE = re.compile(r'^[a-zA-Z0-9/_\-\.]+$')


def _safe_branch(name: str) -> bool:
    return bool(_BRANCH_RE.match(name)) and len(name) <= 100


async def _git(args: list) -> tuple:
    """Run git in STRATEGY_DIR; return (stdout, stderr, returncode)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=STRATEGY_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        return stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), proc.returncode
    except asyncio.TimeoutError:
        return "", "git timeout", -1
    except Exception as e:
        return "", str(e), -1


async def get_diff(from_branch: str, to_branch: str, file: Optional[str] = None) -> dict:
    """Unified diff between two branches (optionally scoped to one file)."""
    if not _safe_branch(from_branch) or not _safe_branch(to_branch):
        return {"error": "invalid branch name", "diff": "", "additions": 0, "deletions": 0}
    if file and file not in ALLOWED_FILES:
        return {"error": f"file '{file}' not in allowlist", "diff": "", "additions": 0, "deletions": 0}

    diff_args = ["diff", f"{from_branch}...{to_branch}", "--no-color", "-U3"]
    if file:
        diff_args += ["--", file]

    stat_args = ["diff", "--stat", f"{from_branch}...{to_branch}"]
    if file:
        stat_args += ["--", file]

    (diff_out, diff_err, diff_rc), (stat_out, _, _) = await asyncio.gather(
        _git(diff_args), _git(stat_args)
    )

    lines = diff_out.splitlines()
    additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))

    return {
        "from_branch": from_branch,
        "to_branch": to_branch,
        "file": file,
        "diff": diff_out,
        "additions": additions,
        "deletions": deletions,
        "stat": stat_out.strip(),
        "error": diff_err.strip() if diff_rc != 0 else None,
    }


async def get_commits(branch: str, n: int = 15, base: Optional[str] = None) -> dict:
    """Recent commits on a branch; if base given, show only commits not in base."""
    if not _safe_branch(branch):
        return {"error": "invalid branch", "commits": []}

    if base:
        if not _safe_branch(base):
            return {"error": "invalid base branch", "commits": []}
        rev_range = f"{base}..{branch}"
    else:
        rev_range = branch

    stdout, stderr, rc = await _git([
        "log", rev_range, f"--max-count={n}",
        "--pretty=format:%h|%ad|%an|%s", "--date=short"
    ])

    commits = []
    for line in stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "date": parts[1],
                "author": parts[2],
                "message": parts[3],
            })

    return {
        "branch": branch,
        "base": base,
        "commits": commits,
        "error": stderr.strip() if rc != 0 else None,
    }


async def get_ahead_behind(branch: str, base: str = BASE_BRANCH) -> dict:
    """How many commits ahead/behind branch is vs base."""
    if not _safe_branch(branch) or not _safe_branch(base):
        return {"ahead": 0, "behind": 0, "error": "invalid branch"}
    stdout, _, rc = await _git(["rev-list", "--left-right", "--count", f"{base}...{branch}"])
    parts = stdout.strip().split()
    if len(parts) == 2:
        return {"ahead": int(parts[1]), "behind": int(parts[0]), "error": None}
    return {"ahead": 0, "behind": 0, "error": "parse error" if rc == 0 else "git error"}


async def get_branches_with_stats() -> dict:
    """All branches with ahead/behind vs master and last commit info."""
    stdout, _, _ = await _git([
        "branch", "-a", "--format=%(refname:short)|%(objectname:short)|%(subject)|%(committerdate:short)"
    ])
    branches = []
    for line in stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        name = parts[0].strip()
        if name.startswith("origin/") or name.startswith("remotes/"):
            continue
        branches.append({
            "name": name,
            "commit": parts[1],
            "message": parts[3],
            "date": parts[2] if len(parts) > 2 else "",
            "is_live": name == LIVE_BRANCH,
        })

    # Get current branch
    cur_out, _, _ = await _git(["branch", "--show-current"])
    current = cur_out.strip()

    for br in branches:
        br["current"] = (br["name"] == current)

    return {"branches": branches, "current": current}
