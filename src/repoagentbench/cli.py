from pathlib import Path

import click

from .runner import run_one_task


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
    type=click.Choice(["claude-code", "mock-fix"]),
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


if __name__ == "__main__":
    main()
