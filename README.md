# RepoAgentBench

> **SWE-bench for your codebase.**

Turn your merged PRs into reproducible coding-agent benchmarks. Find out which AI coding agent — Claude Code, Codex, Aider, Gemini CLI — actually works on **your** repo, **your** tests, **your** constraints.

## Why

Public benchmarks tell you which agent wins on curated, generic tasks. They do not tell you which agent works on the codebase you actually maintain.

RepoAgentBench is local-first. The differentiator: **every merged PR can become a benchmark task.** PR description → goal. PR tests → acceptance criteria. Inverted diff → broken starting state.

## Status

**v0.0.1 — pre-alpha.** Single-task runner only. PR mining, multi-agent leaderboards, and statistical reporting all coming. See [Roadmap](#roadmap).

## Quickstart

```bash
pip install -e .

# Smoke test (no API key, no CLI install required)
repoagentbench run-one --task examples/demo --agent mock-fix

# Real run (requires Claude Code CLI installed and authenticated)
repoagentbench run-one --task examples/demo --agent claude-code
```

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
- [ ] v0.1 — PR-mining (`repoagentbench infer --from-pr 123`), Aider adapter
- [ ] v0.2 — parallel multi-agent eval, Markdown leaderboard report
- [ ] v0.3 — bootstrap CI, pairwise statistical comparison
- [ ] v0.4 — real-repo demo suite (3 OSS repos × historical PRs)

## License

MIT
