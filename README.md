# RepoAgentBench

[![PyPI version](https://img.shields.io/pypi/v/repoagentbench.svg)](https://pypi.org/project/repoagentbench/)
[![Tests](https://github.com/HumphreySun98/repoagentbench/actions/workflows/test.yml/badge.svg)](https://github.com/HumphreySun98/repoagentbench/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **SWE-bench for your codebase.**

Turn your merged PRs into reproducible coding-agent benchmarks. Find out which AI coding agent actually works on **your** repo, **your** tests, **your** constraints — with structured, replayable, diffable run artifacts instead of opaque chat logs.

Today: `mock-fix` (oracle baseline), `claude-code` (native Anthropic CLI), and `aider` (multi-vendor: Opus 4.7, GPT-5.5, Sonnet 4.6, Gemini 3.1 Pro all verified). Codex CLI and Gemini CLI native adapters are next — see [Roadmap](#roadmap).

[![asciicast](https://asciinema.org/a/3LhSATzz3ckQhbUf.svg)](https://asciinema.org/a/3LhSATzz3ckQhbUf)

## Sample leaderboard

Three Click bug-fix PRs × four current vendor flagships (driven by `aider`) + `mock-fix` oracle + native `claude-code`. Tasks were mined with `repoagentbench infer` and run with the harness's default settings.

| Model / Agent | [#3299][p1] | [#3240][p2] | [#3364][p3] | Pass rate |
|---|---|---|---|---|
| `mock-fix` (oracle, applies actual PR diff) | PASS | PASS | PASS | **3 / 3** |
| `aider` + `anthropic/claude-opus-4-7` | FAIL | **PASS** | **PASS** | 2 / 3 |
| `aider` + `gemini/gemini-3.1-pro-preview` | FAIL | **PASS** | **PASS** | 2 / 3 |
| `aider` + `anthropic/claude-sonnet-4-6` | FAIL | FAIL | **PASS** | 1 / 3 |
| `aider` + `openai/gpt-5.5` | **PASS** | FAIL | FAIL | 1 / 3 |
| `claude-code` (native CLI) | **PASS** | — | — | 1 / 1 |

[p1]: https://github.com/pallets/click/pull/3299
[p2]: https://github.com/pallets/click/pull/3240
[p3]: https://github.com/pallets/click/pull/3364

**No frontier model passed all three PRs.** Each one fails on a different bug. Specifically:

- **PR #3299** (`isinstance(default, str) and default == ""` fix): only **GPT-5.5** matched the canonical one-line fix. **Opus 4.7** wrote `default == str()` — a literal no-op (`str()` evaluates to `""`) with a comment claiming it "avoids TypeError." **Sonnet 4.6** wrote `try/except TypeError` but the test class raises `ValueError`. **Gemini 3.1 Pro** patched the wrong function entirely (line 2408 `_value_is_missing` instead of line 3113 `get_help_extra`).

- **PR #3299, harness comparison:** the same Anthropic model family that failed via `aider` **passes via `claude-code`** — the native agent harness wrote the canonical `isinstance` fix where aider+Opus produced a no-op. **Same model, different harness, different result.** The agent harness is part of the system under test, not just a passthrough.

- **PR #3240 / PR #3364:** the win/loss pattern flips — Opus and Gemini pass both, GPT-5.5 fails both, Sonnet flips. The "winner" on one PR is the "loser" on the next.

These are real-codebase failure modes you cannot see on public benchmarks. They surface here because every run executes the project's real test suite against each agent's actual diff — captured in `diff.patch`, `agent.log`, and `events.jsonl` for inspection (see [How it works](#how-it-works)).

> [!NOTE]
> Total real-API spend on this leaderboard: ~$11. Reproduce with `repoagentbench run-one --task tasks/click-pr-3299 --agent aider` (set `RAB_AIDER_MODEL` and the appropriate vendor key first).

## Why

Public benchmarks tell you which agent wins on curated, generic tasks. They do not tell you which agent works on the codebase you actually maintain. And recent research argues those benchmarks are increasingly compromised:

- ["Saving SWE-Bench" (arxiv:2510.08996, Jan 2026)](https://arxiv.org/abs/2510.08996) — public benchmarks overestimate agent capability by 20–50%.
- ["Does SWE-Bench-Verified Test Agent Ability or Model Memory?" (arxiv:2512.10218, Dec 2025)](https://arxiv.org/abs/2512.10218) — frontier models perform 3× better on SWE-Bench-Verified than on benchmarks built from training-cutoff-fresh PRs, suggesting heavy training-data overlap.

RepoAgentBench dodges both problems. It is local-first: your code never leaves your machine. The differentiator: **every merged PR can become a benchmark task.** PR description → goal. PR tests → acceptance criteria. Diff (split into test and source halves) → broken starting state. Mine PRs that post-date the model's training cutoff and you have a contamination-free benchmark of your own.

## Quickstart

**30-second smoke test** (no API key, mock-fix oracle just applies a known diff):

```bash
pip install repoagentbench
git clone https://github.com/HumphreySun98/repoagentbench.git && cd repoagentbench
repoagentbench run-one --task examples/demo --agent mock-fix
```

**Real agent on a real PR**:

```bash
# Mine a benchmark task from any merged GitHub PR (gh CLI required)
repoagentbench infer --from-pr https://github.com/pallets/click/pull/3299 --out tasks/click-3299

# Option A — Aider (multi-vendor; recommended for the leaderboard)
conda create -n aider-rab python=3.11 -y && conda run -n aider-rab pip install aider-chat
export ANTHROPIC_API_KEY=sk-ant-...        # or OPENAI_API_KEY / GEMINI_API_KEY
RAB_AIDER_MODEL=anthropic/claude-opus-4-7 \
    repoagentbench run-one --task tasks/click-3299 --agent aider

# Option B — Claude Code (native)
repoagentbench run-one --task tasks/click-3299 --agent claude-code

repoagentbench report                       # markdown leaderboard of every run
```

Aider model is set via `RAB_AIDER_MODEL` (any LiteLLM-compatible string). Aider binary discovery: `RAB_AIDER_BIN` env var > `~/miniforge/envs/aider-rab/bin/aider` > `$PATH`. Claude Code is auto-discovered from VSCode/Cursor extension dirs.

## How it works

**Mining a PR into a task** (`infer`):

1. Pull the PR title, body, base SHA, and unified diff via `gh`.
2. Clone the repo at the PR's base commit. `.git` is preserved so projects using `setuptools_scm` / `hatch-vcs` install cleanly.
3. Split the PR diff into `solution_tests.patch` and `solution_source.patch`. Apply the test portion to the task folder so the starting state is **"post-PR tests vs pre-PR source"** — without this, `pre_verify` would trivially pass on PRs that add new tests.
4. Auto-generate `verify.sh` for the detected test framework. For pytest projects, the generated script discovers and installs from `requirements*.txt`, `[project.optional-dependencies]`, and PEP 735 `[dependency-groups]`.

**Running a task** (`run-one`):

1. Copy the task into a fresh `.runs/<run_id>/workdir/`.
2. Bootstrap a per-task venv (`.venv-rab/`) inside the workdir. Pip-install the project under test there — never into your system Python.
3. Run `verify.sh` once (`pre_verify`, must FAIL — establishes a broken baseline).
4. Invoke the agent against the goal.
5. Run `verify.sh` again (`post_verify`, must PASS — proves the fix).
6. Emit a self-describing artifact bundle (see below).

**Aggregating runs** (`report` / `replay` / `diff`):

```bash
repoagentbench report                          # markdown leaderboard of every run
repoagentbench report --task click-pr-3299     # filter to one task
repoagentbench replay --run <id_or_prefix>     # re-run same task+agent (variance check)
repoagentbench diff   --run <a> --run <b>      # side-by-side comparison
```

<details>
<summary><b>Run artifact layout</b></summary>

```
.runs/<ISO_ts>__<task>__<agent>__<short_id>/
  manifest.json        # run_id, task_id, agent, base_commit, started_at, harness_version
  status.json          # final outcome: status, failure_stage, summary, durations
  verification.json    # pre/post phases: command, passed, exit_code, duration_seconds
  events.jsonl         # streaming lifecycle events with ms timestamps
  pre_verify.log       # raw test output before the agent ran (must fail)
  post_verify.log      # raw test output after the agent ran (must pass)
  agent.log            # what the agent did (stdout + stderr)
  diff.patch           # what the agent actually changed
  venv_bootstrap.log   # per-task venv setup output
  workdir/             # isolated copy of the task (with `.venv-rab/` inside)
```

Run ids are sortable and human-readable: `20260429T060601Z__click-pr-3299__mock-fix__daf638`.

</details>

## Caveats

> [!WARNING]
> This is v0.1.0 / early alpha. Concrete things you should know before reading too much into the leaderboard:

- **n=3 is small.** The Click sweep above is enough to falsify "Model X is best" but not enough to rank models. The point of the project is to let you build your own benchmark on your own PRs — not to publish a definitive ranking from this README.
- **Single project, single language so far.** The verified leaderboard is all Python (Click). The verify.sh generator covers Go / Cargo / npm too, but those paths haven't been stress-tested end-to-end. If you try a non-Python repo and hit a snag, file an issue.
- **Aider is one harness among many.** Aider's repo-map / edit format / summarizer all influence outcomes. The native `claude-code` row in the leaderboard already shows this. Codex CLI and Gemini CLI native adapters are next (v0.2).
- **PR selection bias.** I picked PRs that compile, have a clean test diff, and don't gate on optional deps. About 30–50% of merged PRs in a typical Python repo will fail one of those checks today; better mining heuristics are roadmap work.
- **No statistical confidence yet.** Pass / fail is the metric; bootstrap CIs and run-to-run variance estimation are v0.3.

If any of these would change your interpretation of the leaderboard, please tell me — happy to adjust the README or the harness.

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

- [x] **v0.1.0** — single-task runner, PR-to-task mining (test/source split, `.git` preserved, PEP 735 dep-groups), per-task venv isolation, structured run-dir (`manifest.json` / `events.jsonl` / `verification.json`), `report` / `replay` / `diff` subcommands, adapters for `mock-fix` / `claude-code` / `aider` (4 frontier models verified). [Full version history](https://github.com/HumphreySun98/repoagentbench/commits/main).
- [ ] **v0.2** — Codex CLI + Gemini CLI native adapters; parallel multi-agent eval; HTML report.
- [ ] **v0.3** — bootstrap confidence intervals, pairwise statistical comparison, run-to-run variance estimation.
- [ ] **v0.4** — real-repo demo suite (3+ OSS repos × historical PRs × all adapters); permission modes (readonly / workspace-write / bypass).

## License

MIT

## Author

**Haofei Sun** — [humphreysun98@gmail.com](mailto:humphreysun98@gmail.com) · [github.com/HumphreySun98](https://github.com/HumphreySun98)

Reach out about agent-eval / devtools / infra roles, RepoAgentBench feedback, or contributions.
