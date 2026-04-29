"""Generate task folders from merged GitHub PRs.

The differentiator of RepoAgentBench: instead of asking users to author benchmark
tasks by hand, mine them from the project's existing PR history. Each merged PR is
already a goal (PR title/body), a solution (the diff), and a verification harness
(the tests the PR added or modified) bundled together.
"""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PR_URL_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


@dataclass
class PRRef:
    owner: str
    repo: str
    number: int

    @classmethod
    def from_url(cls, url: str) -> "PRRef":
        m = PR_URL_RE.match(url.strip())
        if not m:
            raise ValueError(f"Not a recognizable GitHub PR URL: {url}")
        return cls(owner=m.group(1), repo=m.group(2), number=int(m.group(3)))

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def infer_from_pr(pr_url: str, out_dir: Path) -> Path:
    """Generate a task folder from a GitHub PR.

    Layout produced:

        out_dir/
          goal.md            PR title + body, framed as the agent's task
          solution.patch     the PR's unified diff (works with mock-fix agent)
          task.json          source metadata
          TODO.md            what the user needs to fill in (verify.sh)
          <repo contents>    codebase checked out at the PR's base SHA

    The user must add `verify.sh` (or run pytest if that's the project's
    convention) before this task can be evaluated end-to-end.
    """
    if shutil.which("gh") is None:
        raise RuntimeError(
            "`gh` CLI is required for PR mining. Install: https://cli.github.com/"
        )

    pr = PRRef.from_url(pr_url)
    pr_meta = _gh_pr_view(pr)
    diff = _gh_pr_diff(pr)
    base_sha = pr_meta["baseRefOid"]

    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RuntimeError(f"Output directory exists and is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "repo"
        subprocess.run(
            ["git", "clone", "--quiet",
             f"https://github.com/{pr.slug}.git", str(clone_dir)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "checkout", "--quiet", base_sha],
            check=True,
        )
        shutil.rmtree(clone_dir / ".git")
        for item in clone_dir.iterdir():
            shutil.move(str(item), str(out_dir / item.name))

    (out_dir / "goal.md").write_text(_render_goal(pr_meta))
    (out_dir / "solution.patch").write_text(diff)
    (out_dir / "task.json").write_text(json.dumps({
        "source": {
            "type": "github_pr",
            "owner": pr.owner,
            "repo": pr.repo,
            "number": pr.number,
            "url": pr_meta["url"],
        },
        "base_sha": base_sha,
        "title": pr_meta["title"],
        "state": pr_meta["state"],
    }, indent=2) + "\n")
    (out_dir / "TODO.md").write_text(_render_todo())

    return out_dir


def _gh_pr_view(pr: PRRef) -> dict:
    proc = subprocess.run(
        ["gh", "pr", "view", str(pr.number),
         "--repo", pr.slug,
         "--json", "title,body,number,url,baseRefOid,state"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def _gh_pr_diff(pr: PRRef) -> str:
    proc = subprocess.run(
        ["gh", "pr", "diff", str(pr.number), "--repo", pr.slug],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def _render_goal(pr_meta: dict) -> str:
    title = pr_meta["title"]
    body = (pr_meta.get("body") or "").strip() or "_No PR description provided._"
    return (
        f"# {title}\n\n"
        f"{body}\n\n"
        f"---\n\n"
        f"**Source:** {pr_meta['url']}\n"
    )


def _render_todo() -> str:
    return (
        "# TODO before this task can be evaluated\n\n"
        "1. Add a `verify.sh` script that runs the tests this PR added or "
        "modified. Without it, `repoagentbench run-one` will fall back to a "
        "bare `pytest` invocation, which may not match the project's "
        "conventions.\n\n"
        "2. Sanity-check that `solution.patch` applies cleanly:\n\n"
        "       cd <task-folder> && patch -p1 --dry-run -i solution.patch\n\n"
        "3. Smoke-test the harness with the mock-fix agent:\n\n"
        "       repoagentbench run-one --task <task-folder> --agent mock-fix\n"
    )
