# RepoAgentBench

> **SWE-bench for your codebase.**

Turn your merged PRs into reproducible coding-agent benchmarks. Find out which AI coding agent actually works on **your** repo, **your** tests, **your** constraints.

Today: a Claude Code adapter and a `mock-fix` oracle baseline. Aider, Codex CLI, and Gemini CLI adapters are next — see [Roadmap](#roadmap).

## Why

Public benchmarks tell you which agent wins on curated, generic tasks. They do not tell you which agent works on the codebase you actually maintain.

RepoAgentBench is local-first. The differentiator: **every merged PR can become a benchmark task.** PR description → goal. PR tests → acceptance criteria. Inverted diff → broken starting state.

## Status

**v0.0.4 — early alpha.** Single-task runner, PR-to-task mining (including patch splitting so the starting state is "post-PR tests vs pre-PR source"), and `verify.sh` auto-generation work end-to-end with the Claude Code adapter. A second real agent, multi-agent leaderboards, and statistical reporting are still coming. See [Roadmap](#roadmap).

## Quickstart

```bash
pip install -e .

# Smoke test (no API key, no CLI install required)
repoagentbench run-one --task examples/demo --agent mock-fix

# Real run (requires Claude Code CLI installed and authenticated)
repoagentbench run-one --task examples/demo --agent claude-code
```

## Mine a benchmark task from any merged GitHub PR

```bash
# Generate a task folder from a real PR
repoagentbench infer \
    --from-pr https://github.com/octocat/Hello-World/pull/6 \
    --out tasks/octocat-hello-pr-6

# Run it
repoagentbench run-one --task tasks/octocat-hello-pr-6 --agent mock-fix
```

The `infer` command:

- pulls the PR's title, body, base SHA, and unified diff via `gh`
- clones the repo at the PR's base commit (the "broken" pre-fix state)
- writes `goal.md` (PR title + body), `solution.patch` (the PR diff), and `task.json` (source metadata)
- **auto-generates `verify.sh`** from the PR's modified test files, when it can detect the project's test framework (pytest / `go test` / `cargo test` / `npm test`). When it can't, it writes a `TODO.md` explaining what to fill in.

> Requires the [`gh` CLI](https://cli.github.com/) installed and authenticated.

Outputs go to `.runs/<run_id>/`:

```
.runs/<run_id>/
  status.json        # final outcome
  pre_verify.log     # tests before agent ran (must fail)
  agent.log          # what the agent did
  diff.patch         # what the agent changed
  post_verify.log    # tests after agent ran (must pass)
  workdir/           # isolated copy of the task
```

## Task layout

```
examples/demo/
  goal.md            # natural-language task description
  solution.patch     # ground-truth fix (used by mock-fix and v2 PR-mining)
  src/               # broken code
  tests/             # tests that must pass after the fix
```

## How is this different from SWE-bench / CodeScaleBench?

| | SWE-bench | CodeScaleBench | **RepoAgentBench** |
|---|---|---|---|
| Tasks | 2,294 curated | 275 curated | **mined from your PRs** |
| Codebase | 12 OSS repos | enterprise OSS | **your repo** |
| Distribution | public dataset | public dataset | **local-first** |
| Question answered | which model is strongest in general | which agent leverages context tools well | **which agent works on this codebase** |

## Roadmap

- [x] v0.0.1 — single-task runner with `mock-fix` and `claude-code` adapters
- [x] v0.0.2 — `repoagentbench infer --from-pr <url>` mines tasks from merged GitHub PRs
- [x] v0.0.3 — `infer` auto-generates `verify.sh` for pytest / Go / Cargo / npm projects
- [x] v0.0.4 — `infer` splits PR diff into test/source patches so PR-mined tasks have a valid pre-fix starting state
- [ ] v0.1 — Aider adapter, second working agent for real comparisons
- [ ] v0.2 — parallel multi-agent eval, Markdown leaderboard report
- [ ] v0.3 — bootstrap CI, pairwise statistical comparison
- [ ] v0.4 — real-repo demo suite (3 OSS repos × historical PRs)

## License

MIT

## Author

Haofei Sun
