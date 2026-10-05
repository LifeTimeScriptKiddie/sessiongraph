"""Which repository a session worked in (plan step CC1).

The repo is the git root of the transcript's `cwd`, so linked worktrees of one
repo (`agentctl/dev-*`, `.claude/worktrees/*`) resolve to the main checkout and
count as one repo. A `cwd` that no longer exists is "unknown": it is never
guessed from the directory name. An existing directory outside git is its own
location, reported as-is.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

UNKNOWN = "unknown"


def _main_checkout(dot_git: Path) -> Path:
    """The main checkout for a `.git` entry; a worktree's `.git` file points into the main repo."""
    if dot_git.is_dir():
        return dot_git.parent
    try:
        line = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return dot_git.parent
    if not line.startswith("gitdir:"):
        return dot_git.parent
    gitdir = Path(line.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (dot_git.parent / gitdir).resolve()
    common = gitdir / "commondir"
    try:
        common_dir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        return dot_git.parent  # a submodule or a broken worktree: the checkout itself
    return common_dir.parent if common_dir.name == ".git" else common_dir


@lru_cache(maxsize=None)
def repo_of(cwd: str | None) -> str:
    """Absolute path of the repo for `cwd`, or UNKNOWN when it is missing or gone."""
    if not cwd:
        return UNKNOWN
    here = Path(cwd).expanduser()
    if not here.is_dir():
        return UNKNOWN
    here = here.resolve()
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return str(_main_checkout(folder / ".git"))
    return str(here)


def display(repo: str) -> str:
    """A repo path with the home directory shortened to ~."""
    home = str(Path.home())
    return "~" + repo[len(home):] if repo == home or repo.startswith(home + "/") else repo


def slugs(repos: set[str]) -> dict[str, str]:
    """Short, unique, dot-free names for repos (used in family names and metric keys)."""
    def clean(text: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "-" for c in text) or "root"

    out: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    for repo in repos:
        by_name.setdefault(clean(Path(repo).name if repo != UNKNOWN else UNKNOWN), []).append(repo)
    for name, members in by_name.items():
        if len(members) == 1:
            out[members[0]] = name
            continue
        for repo in members:  # same folder name in two places: add the parent folder
            out[repo] = f"{clean(Path(repo).parent.name)}-{name}"
    return out
