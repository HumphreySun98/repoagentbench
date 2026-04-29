# RepoAgentBench

> **SWE-bench for your codebase.**

Turn your merged PRs into reproducible coding-agent benchmarks. Find out which AI coding agent actually works on **your** repo, **your** tests, **your** constraints — with structured, replayable, diffable run artifacts instead of opaque chat logs.

Today: `mock-fix` (oracle baseline), `claude-code`, and `aider` adapters. Codex CLI and Gemini CLI are next — see [Roadmap](#roadmap).

## Sample leaderboard

One `repoagentbench report` after running `mock-fix` (the oracle that applies the PR's actual diff) and `aider` (Claude Sonnet 4.6) on a real merged PR (Click #3299) and a synthetic demo task:

| Task | Agent | Status | Pre | Post | Files | Duration |
|---|---|---|---|---|---|---|
| click-pr-3299 | mock-fix | **PASS** | FAIL | PASS | 1 | 8.8s |
| click-pr-3299 | aider (sonnet-4-6) | **FAIL** | FAIL | FAIL | 2 | 610s |
| demo | mock-fix | **PASS** | FAIL | PASS | 1 | 4.1s |
| demo | aider (sonnet-4-6) | **FAIL** | FAIL | FAIL | 1 | 8.8s |

| Agent | Runs | Passed | Pass rate | Avg duration |
|---|---|---|---|---|
| mock-fix | 2 | 2 | 100% | 6.5s |
| aider/sonnet-4-6 | 2 | 0 | 0% | 309s |

**Why aider failed on click PR #3299:** the bug is `default == ""` raising `ValueError` on objects with a custom `__eq__`. Aider produced a defensive `try/except TypeError` — but the test class raises `ValueError`, so one assertion still fails. The actual one-line PR fix added an `isinstance(default, str)` short-circuit instead of catching exceptions.

**Why aider failed on the demo task:** Sonnet's whole-file edit reply truncated an unrelated `multiply()` function while fixing `add()`. The test importing `multiply` then errors at collection.

Both are real-codebase failure modes you cannot see on public benchmarks. They surface here because every run executes the project's actual test suite and the run artifacts (`diff.patch`, `agent.log`, `events.jsonl`) capture exactly what each agent did and why it failed.

## Why

Public benchmarks tell you which agent wins on curated, generic tasks. They do not tell you which agent works on the codebase you actually maintain. And recent research argues those benchmarks are increasingly compromised:

- ["Saving SWE-Bench" (arxiv:2510.08996, Jan 2026)](https://arxiv.org/abs/2510.08996) — public benchmarks overestimate agent capability by 20–50%.
- ["Does SWE-Bench-Verified Test Agent Ability or Model Memory?" (arxiv:2512.10218, Dec 2025)](https://arxiv.org/abs/2512.10218) — frontier models perform 3× better on SWE-Bench-Verified than on benchmarks built from training-cutoff-fresh PRs, suggesting heavy training-data overlap.

RepoAgentBench dodges both problems. It is local-first: your code never leaves your machine. The differentiator: **every merged PR can become a benchmark task.** PR description → goal. PR tests → acceptance criteria. Diff (split into test and source halves) → broken starting state. Mine PRs that post-date the model's training cutoff and you have a contamination-free benchmark of your own.

## Status

**v0.1.0 — early alpha.** Single-task runner with per-task venv isolation, PR-to-task mining (test/source patch splitting), `verify.sh` auto-generation (`requirements*.txt`, `[project.optional-dependencies]`, PEP 735 `[dependency-groups]`), structured run artifacts (`manifest.json`, `events.jsonl`, `verification.json`), `report` / `replay` / `diff` subcommands, and adapters for `mock-fix` / `claude-code` / `aider`. Validated end-to-end on a real OSS PR (Click #3299) with real Claude API. Codex CLI / Gemini CLI adapters, parallel multi-agent eval, and statistical reporting are next. See [Roadmap](#roadmap).

## Quickstart

```bash
pip install -e .

# Smoke test (no API key, no CLI install required)
repoagentbench run-one --task examples/demo --agent mock-fix
```

For real agents:

```bash
# Aider (recommended path: dedicated conda env so Aider's deps don't conflict with task deps)
conda create -n aider-rab python=3.11 -y
conda run -n aider-rab pip install aider-chat
export ANTHROPIC_API_KEY=sk-ant-...
repoagentbench run-one --task examples/demo --agent aider

# Claude Code
# Install Claude Code CLI per https://docs.claude.com/en/docs/claude-code, then:
repoagentbench run-one --task examples/demo --agent claude-code
```

Aider defaults to `anthropic/claude-sonnet-4-6`. Override with `RAB_AIDER_MODEL=anthropic/claude-opus-4-7` (or any LiteLLM-compatible model). Override the binary path with `RAB_AIDER_BIN=/path/to/aider`.

## Mine a benchmark task from any merged GitHub PR

```bash
repoagentbench infer \
    --from-pr https://github.com/pallets/click/pull/3299 \
    --out tasks/click-pr-3299

repoagentbench run-one --task tasks/click-pr-3299 --agent mock-fix
repoagentbench run-one --task tasks/click-pr-3299 --agent aider
```

The `infer` command:

- pulls the PR's title, body, base SHA, and unified diff via `gh`
- clones the repo at the PR's base commit (preserves `.git` so projects using `setuptools_scm` / `hatch-vcs` / similar still install)
- splits the PR diff into `solution_tests.patch` and `solution_source.patch`, then applies the test portion to the task folder so the starting state is "post-PR tests vs pre-PR source" — without that, `pre_verify` would trivially pass on PRs that add new tests
- writes `goal.md` (PR title + body), `solution.patch` (full diff for reference), and `task.json` (source metadata)
- **auto-generates `verify.sh`** based on the test framework it detects (pytest / `go test` / `cargo test` / `npm test`). For pytest projects, the generated script discovers and installs from `requirements*.txt`, `[project.optional-dependencies]` extras, and PEP 735 `[dependency-groups]`. When no framework can be detected it writes a `TODO.md` explaining what to fill in.

> Requires the [`gh` CLI](https://cli.github.com/) installed and authenticated.

## Run artifacts

Each run-dir is a self-describing bundle:

```
.runs/<ISO_ts>__<task>__<agent>__<short_id>/
  manifest.json        # run_id, task_id, agent, base_commit, started_at, harness_version
  status.json          # final outcome: status, failure_stage, summary, durations
  verification.json    # pre/post phases: command, passed, exit_code, duration_seconds
  events.jsonl         # streaming lifecycle events with millisecond timestamps
                       # (run.started, verify.*, agent.*, diff.captured, run.finished)
  pre_verify.log       # raw test output before the agent ran (must fail)
  post_verify.log      # raw test output after the agent ran (must pass)
  agent.log            # what the agent did (stdout + stderr)
  diff.patch           # what the agent actually changed
  venv_bootstrap.log   # per-task venv setup output
  workdir/             # isolated copy of the task (with `.venv-rab/` inside)
```

Run ids are sortable and human-readable: `20260429T060601Z__click-pr-3299__mock-fix__daf638`. Each task runs inside its own `.venv-rab` venv so installing the project under test does not pollute your system Python or break the harness itself.

## Aggregate, replay, compare

```bash
repoagentbench report                              # markdown leaderboard of every run
repoagentbench report --task click-pr-3299         # filter to one task
repoagentbench report --output report.md           # write to file

repoagentbench replay --run <run_id_or_prefix>     # re-run the same task+agent (variance check)
repoagentbench diff   --run <id_a> --run <id_b>    # side-by-side comparison
```

`report` groups runs by task and includes a per-agent aggregate (runs, passed, pass rate, average duration). `replay` reads `manifest.json` so the same task and agent are reused — useful for measuring run-to-run variance or re-validating after upgrading the harness. `diff` highlights the fields that changed between two runs.

## How is this different from SWE-bench / CodeScaleBench?

| | SWE-bench | CodeScaleBench | **RepoAgentBench** |
|---|---|---|---|
| Tasks | 2,294 curated | 275 curated | **mined from your PRs** |
| Codebase | 12 OSS repos | enterprise OSS | **your repo** |
| Distribution | public dataset | public dataset | **local-first** |
| Training-data contamination | known issue [^1] | known issue | **avoidable** (mine PRs after model cutoff) |
| Question answered | which model is strongest in general | which agent leverages context tools well | **which agent works on this codebase** |

[^1]: Bian et al., 2025 — "Does SWE-Bench-Verified Test Agent Ability or Model Memory?" — finds frontier models score 3× higher on SWE-Bench-Verified than on equivalent training-fresh tasks.

## Roadmap

- [x] v0.0.1 — single-task runner with `mock-fix` and `claude-code` adapters
- [x] v0.0.2 — `repoagentbench infer --from-pr <url>` mines tasks from merged GitHub PRs
- [x] v0.0.3 — `infer` auto-generates `verify.sh` for pytest / Go / Cargo / npm projects
- [x] v0.0.4 — `infer` splits PR diff into test/source patches so PR-mined tasks have a valid pre-fix starting state
- [x] v0.0.5 — per-task venv isolation; `verify.sh` handles `requirements*.txt` and PEP 735 `[dependency-groups]`
- [x] v0.0.6 — structured run-dir (`manifest.json`, `events.jsonl`, `verification.json`); sortable human-readable `run_id`s
- [x] v0.0.7 — `report` / `replay` / `diff` subcommands
- [x] v0.1.0 — Aider adapter; first real Claude API leaderboard data
- [ ] v0.2 — Codex CLI adapter; parallel multi-agent eval; HTML report
- [ ] v0.3 — bootstrap confidence intervals, pairwise statistical comparison
- [ ] v0.4 — real-repo demo suite (3 OSS repos × historical PRs × all agents)

## License

MIT

## Author

Haofei Sun — [github.com/HumphreySun98](https://github.com/HumphreySun98). Reach out about agent-eval / devtools / infra roles, RepoAgentBench feedback, or contributions.
