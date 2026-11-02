from __future__ import annotations

from pathlib import Path
from typing import Any

import git


def git_log(project_root: Path, filepath: str, n: int = 5) -> dict[str, Any]:
    try:
        repo = git.Repo(project_root, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        return {"filepath": filepath, "commits": [], "error": "not a git repository"}
    relative_path = str(Path(filepath))
    if not (project_root / relative_path).exists():
        return {"filepath": filepath, "commits": [], "error": "file not found"}
    commits = list(repo.iter_commits(paths=relative_path, max_count=min(max(n, 1), 20)))
    return {
        "filepath": filepath,
        "commits": [
            {
                "hash": commit.hexsha[:7],
                "timestamp": commit.committed_datetime.isoformat(),
                "author": commit.author.email,
                "message": commit.message.strip(),
                "files_changed": list(commit.stats.files.keys()),
            }
            for commit in commits
        ],
        "error": None,
    }


def get_commit_message(project_root: Path, commit_hash: str) -> dict[str, Any]:
    try:
        repo = git.Repo(project_root, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        return {"hash": commit_hash, "error": "not a git repository"}
    try:
        commit = repo.commit(commit_hash)
    except Exception:
        return {"hash": commit_hash, "error": "commit not found"}
    total_insertions = sum(stats["insertions"] for stats in commit.stats.files.values())
    total_deletions = sum(stats["deletions"] for stats in commit.stats.files.values())
    return {
        "hash": commit.hexsha,
        "timestamp": commit.committed_datetime.isoformat(),
        "author": commit.author.email,
        "message": commit.message.strip(),
        "diff_stat": {
            "files_changed": len(commit.stats.files),
            "insertions": total_insertions,
            "deletions": total_deletions,
        },
        "error": None,
    }

