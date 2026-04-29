from pathlib import Path

import click

from .agents import AGENT_NAMES
from .pr_mining import infer_from_pr
from .runner import run_one_task
from .runs import RunSummary, list_runs, render_diff, render_report, resolve_run_dir


@click.group()
@click.version_option()
def main():
    """RepoAgentBench: SWE-bench for your codebase."""


@main.command("run-one")
@click.option(
    "--task", "task_path",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to a task folder (must contain goal.md).",
)
@click.option(
    "--agent",
    default="mock-fix",
    type=click.Choice(list(AGENT_NAMES)),
    show_default=True,
    help="Which agent to invoke.",
)
@click.option(
    "--out", "out_dir",
    default=Path(".runs"),
    type=click.Path(path_type=Path),
    show_default=True,
    help="Where to write run artifacts.",
)
def run_one(task_path: Path, agent: str, out_dir: Path):
    """Run a single task through one agent and capture results."""
    result = run_one_task(task_path, agent, out_dir)
    click.echo(f"\nrun_id:      {result.run_id}")
    click.echo(f"run_dir:     {result.run_dir}")
    click.echo(f"pre_verify:  {'PASS' if result.pre_verify_passed else 'FAIL'}  (expected FAIL)")
    click.echo(f"post_verify: {'PASS' if result.post_verify_passed else 'FAIL'}  (expected PASS)")
    click.echo(f"status:      {result.status}")
    click.echo(f"duration:    {result.duration_seconds:.1f}s")


@main.command("infer")
@click.option(
    "--from-pr", "pr_url",
    required=True,
    help="Full GitHub PR URL, e.g. https://github.com/owner/repo/pull/123",
)
@click.option(
    "--out", "out_dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output task folder (must not exist or be empty).",
)
def infer(pr_url: str, out_dir: Path):
    """Generate a task folder from a merged GitHub PR."""
    task_dir, inference = infer_from_pr(pr_url, out_dir)
    click.echo(f"Task generated: {task_dir}")
    click.echo("  goal.md, solution.patch, task.json, repo at PR base SHA")
    if inference.script is not None:
        click.echo(f"  verify.sh:     auto-generated for {inference.framework} "
                   f"({len(inference.test_files)} test file(s) detected)")
        click.echo(f"  Next: repoagentbench run-one --task {task_dir} --agent mock-fix")
    else:
        click.echo(f"  verify.sh:     NOT generated — {inference.note}")
        click.echo(f"  Next: write {task_dir}/verify.sh, then run-one")


@main.command("report")
@click.option(
    "--runs-dir",
    default=Path(".runs"),
    type=click.Path(path_type=Path),
    show_default=True,
    help="Directory containing run artifacts.",
)
@click.option(
    "--task", "task_filter",
    default=None,
    help="Only include runs for this task_id.",
)
@click.option(
    "--output", "output",
    default=None,
    type=click.Path(path_type=Path),
    help="Write the report to this file instead of stdout.",
)
def report(runs_dir: Path, task_filter: str, output: Path):
    """Aggregate run-dirs into a markdown leaderboard."""
    summaries = list_runs(runs_dir)
    if not summaries:
        click.echo(f"No runs found under {runs_dir}.", err=True)
        raise click.exceptions.Exit(1)
    text = render_report(summaries, task_filter=task_filter)
    if output:
        output.write_text(text)
        click.echo(f"Wrote {output} ({len(summaries)} run(s))")
    else:
        click.echo(text)


@main.command("replay")
@click.option(
    "--run", "run_id",
    required=True,
    help="The run_id (or unique prefix) of the run to replay.",
)
@click.option(
    "--runs-dir",
    default=Path(".runs"),
    type=click.Path(path_type=Path),
    show_default=True,
    help="Directory containing run artifacts.",
)
def replay(run_id: str, runs_dir: Path):
    """Re-run a task using the manifest from a previous run-dir.

    The original task_path and agent are read from manifest.json; a new
    run with a fresh run_id is produced under --runs-dir.
    """
    src = resolve_run_dir(run_id, runs_dir)
    summary = RunSummary.from_run_dir(src)
    if not summary.task_path.exists():
        click.echo(f"Original task path no longer exists: {summary.task_path}", err=True)
        raise click.exceptions.Exit(1)
    click.echo(f"Replaying {summary.run_id}")
    click.echo(f"  task:   {summary.task_path}")
    click.echo(f"  agent:  {summary.agent}")
    result = run_one_task(summary.task_path, summary.agent, runs_dir)
    click.echo(f"\nnew run_id:  {result.run_id}")
    click.echo(f"status:      {result.status}  (was {summary.status})")
    click.echo(f"duration:    {result.duration_seconds:.1f}s  (was {summary.duration_seconds:.1f}s)")


@main.command("diff")
@click.option(
    "--run", "run_ids",
    multiple=True,
    required=True,
    help="Two --run flags: the runs to compare.",
)
@click.option(
    "--runs-dir",
    default=Path(".runs"),
    type=click.Path(path_type=Path),
    show_default=True,
    help="Directory containing run artifacts.",
)
def diff(run_ids: tuple[str, ...], runs_dir: Path):
    """Compare two runs side-by-side."""
    if len(run_ids) != 2:
        raise click.UsageError("Pass exactly two --run flags.")
    a = RunSummary.from_run_dir(resolve_run_dir(run_ids[0], runs_dir))
    b = RunSummary.from_run_dir(resolve_run_dir(run_ids[1], runs_dir))
    click.echo(render_diff(a, b))


if __name__ == "__main__":
    main()
