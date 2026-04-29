"""Generate task folders from merged GitHub PRs.

The differentiator of RepoAgentBench: instead of asking users to author benchmark
tasks by hand, mine them from the project's existing PR history. Each merged PR is
already a goal (PR title/body), a solution (the diff), and a verification harness
(the tests the PR added or modified) bundled together.
"""

import json
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PR_URL_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/", re.MULTILINE)

TEST_FILE_PATTERNS = [
    re.compile(r"(?:^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.py$"),
    re.compile(r"\.(test|spec)\.(jsx?|tsx?|mjs|cjs)$"),
    re.compile(r"(?:^|/)__tests__/.*\.(jsx?|tsx?|mjs|cjs)$"),
    re.compile(r"_test\.go$"),
    re.compile(r"(?:^|/)tests/.*\.rs$"),
    re.compile(r"(?:^|/)spec/.*_spec\.rb$"),
]


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


@dataclass
class VerifyInference:
    """Result of attempting to auto-generate verify.sh from a PR diff."""

    framework: Optional[str]
    test_files: list[str]
    script: Optional[str]
    note: str


def infer_from_pr(pr_url: str, out_dir: Path) -> tuple[Path, VerifyInference]:
    """Generate a task folder from a GitHub PR.

    Layout produced:

        out_dir/
          goal.md            PR title + body, framed as the agent's task
          solution.patch     the PR's unified diff (works with mock-fix agent)
          task.json          source metadata
          verify.sh          auto-generated when framework + tests detected
          TODO.md            written only when verify.sh could not be generated
          <repo contents>    codebase checked out at the PR's base SHA
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
        # Keep .git so projects that derive their version from git tags
        # (setuptools_scm, hatch-vcs, ...) install correctly during verify,
        # and so future replay/diff features can use base_sha as an anchor.
        for item in clone_dir.iterdir():
            shutil.move(str(item), str(out_dir / item.name))

    (out_dir / "goal.md").write_text(_render_goal(pr_meta))
    (out_dir / "solution.patch").write_text(diff)

    # Split the PR diff into test-only and source-only patches. Apply the
    # test portion to the task folder so the starting state is "post-PR tests
    # vs pre-PR source" — without this, pre_verify trivially passes (existing
    # tests at base_sha don't exercise the new behavior the PR adds).
    tests_patch, source_patch = split_diff_by_tests(diff)
    if tests_patch:
        (out_dir / "solution_tests.patch").write_text(tests_patch)
        _apply_patch(tests_patch, out_dir)
    if source_patch:
        (out_dir / "solution_source.patch").write_text(source_patch)

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
        "tests_patch_applied": bool(tests_patch),
    }, indent=2) + "\n")

    inference = infer_verify(diff, out_dir)
    if inference.script is not None:
        verify_path = out_dir / "verify.sh"
        verify_path.write_text(inference.script)
        verify_path.chmod(0o755)
    else:
        (out_dir / "TODO.md").write_text(_render_todo(inference))

    return out_dir, inference


def infer_verify(diff: str, workdir: Path) -> VerifyInference:
    """Auto-generate verify.sh body from a PR's diff and the cloned repo state."""
    test_files = extract_test_files_from_diff(diff)
    framework = detect_framework(workdir)

    if framework is None:
        return VerifyInference(
            framework=None,
            test_files=test_files,
            script=None,
            note="No supported framework detected (looked for pyproject.toml, package.json, go.mod, Cargo.toml).",
        )

    script = generate_verify_sh(test_files, framework, workdir)
    if script is None:
        return VerifyInference(
            framework=framework,
            test_files=test_files,
            script=None,
            note=f"Framework {framework!r} detected but no auto-generation rule defined.",
        )

    if test_files:
        note = (
            f"verify.sh auto-generated for {framework}; runs "
            f"{len(test_files)} PR-modified test file(s)."
        )
    else:
        note = (
            f"verify.sh auto-generated for {framework}; PR did not touch test "
            f"files, so the full {framework} suite will run."
        )
    return VerifyInference(framework=framework, test_files=test_files, script=script, note=note)


def split_diff_by_tests(diff: str) -> tuple[str, str]:
    """Split a unified diff into (tests_patch, source_patch).

    A "diff --git a/<path> b/<path>" line starts a new per-file section; each
    section is routed to one of the two output patches based on whether the
    path looks like a test file.
    """
    if not diff:
        return "", ""
    sections: list[tuple[str, list[str]]] = []  # (path, lines)
    current_path: Optional[str] = None
    current_lines: list[str] = []
    for line in diff.splitlines(keepends=True):
        m = DIFF_FILE_RE.match(line)
        if m:
            if current_path is not None:
                sections.append((current_path, current_lines))
            current_path = m.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_path is not None:
        sections.append((current_path, current_lines))

    test_lines: list[str] = []
    source_lines: list[str] = []
    for path, lines in sections:
        is_test = any(p.search(path) for p in TEST_FILE_PATTERNS)
        (test_lines if is_test else source_lines).extend(lines)
    return "".join(test_lines), "".join(source_lines)


def _apply_patch(patch_text: str, workdir: Path) -> None:
    """Apply a unified diff to workdir using `patch -p1`. Raises on failure."""
    proc = subprocess.run(
        ["patch", "-p1", "--forward"],
        cwd=workdir,
        input=patch_text,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to apply patch in {workdir}:\n"
            f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}"
        )


def extract_test_files_from_diff(diff: str) -> list[str]:
    """Return file paths from the diff that look like test files."""
    files = DIFF_FILE_RE.findall(diff)
    test_files = [f for f in files if any(p.search(f) for p in TEST_FILE_PATTERNS)]
    seen = set()
    deduped = []
    for f in test_files:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


def detect_framework(workdir: Path) -> Optional[str]:
    """Return a string identifying the project's test framework, based on files at the repo root."""
    if (workdir / "Cargo.toml").exists():
        return "cargo"
    if (workdir / "go.mod").exists():
        return "go"
    if (workdir / "package.json").exists():
        return "npm"
    pytest_signals = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini")
    if any((workdir / s).exists() for s in pytest_signals):
        return "pytest"
    if next(workdir.rglob("*.py"), None) is not None:
        return "pytest"
    if next(workdir.rglob("*.go"), None) is not None:
        return "go"
    return None


def generate_verify_sh(test_files: list[str], framework: str, workdir: Path) -> Optional[str]:
    """Generate the body of verify.sh, or None if we cannot."""
    header = "#!/bin/bash\n# Auto-generated by `repoagentbench infer`.\nset -uo pipefail\n"
    if framework == "pytest":
        install = _pytest_install_block(workdir)
        runner = "python -m pytest -x --tb=short"
        if test_files:
            paths = " ".join(shlex.quote(f) for f in test_files)
            return header + install + f"{runner} {paths}\n"
        return header + install + f"{runner}\n"
    if framework == "go":
        return header + "go test ./...\n"
    if framework == "cargo":
        return header + "cargo test\n"
    if framework == "npm":
        # `npm test` runs whatever script the project defines; per-file targeting is project-specific.
        return header + "npm install --silent\nnpm test --silent\n"
    return None


def _pytest_install_block(workdir: Path) -> str:
    """Best-effort dependency install for a pytest project. Discovers what
    install conventions the project uses (requirements*.txt, [project.optional-dependencies],
    PEP 735 [dependency-groups]) and emits matching pip commands. Each command
    tolerates failure so the unused conventions don't break the run.

    Verify.sh is invoked under a per-task venv (see runner._bootstrap_venv),
    so these installs do not pollute the user's system Python.
    """
    lines = [
        "# Best-effort install of project + test deps. Each line tolerates failure so projects",
        "# that use only one convention don't trip on the others.",
    ]
    for req in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "tests/requirements.txt"):
        if (workdir / req).exists():
            lines.append(f"pip install -r {req} --quiet 2>/dev/null || true")
    lines.append(
        "pip install -e '.[dev]' --quiet 2>/dev/null \\\n"
        "  || pip install -e '.[test]' --quiet 2>/dev/null \\\n"
        "  || pip install -e . --quiet 2>/dev/null \\\n"
        "  || true"
    )
    pyproject = workdir / "pyproject.toml"
    if pyproject.exists() and "[dependency-groups]" in pyproject.read_text():
        lines.append("pip install --group tests --quiet 2>/dev/null || true")
        lines.append("pip install --group dev --quiet 2>/dev/null || true")
    return "\n".join(lines) + "\n"


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


def _render_todo(inference: VerifyInference) -> str:
    lines = [
        "# verify.sh was not auto-generated",
        "",
        f"Reason: {inference.note}",
        "",
    ]
    if inference.test_files:
        lines += [
            "Detected test files in the PR diff (you can wire these into `verify.sh`):",
            "",
            *(f"- `{f}`" for f in inference.test_files),
            "",
        ]
    lines += [
        "Once you write `verify.sh`, smoke-test with:",
        "",
        "    repoagentbench run-one --task <task-folder> --agent mock-fix",
        "",
    ]
    return "\n".join(lines)
