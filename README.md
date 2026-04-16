# augint-shell CLI

[![PyPI version](https://badge.fury.io/py/augint-shell.svg)](https://badge.fury.io/py/augint-shell)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/svange/augint-shell/actions/workflows/pipeline.yaml/badge.svg)](https://github.com/svange/augint-shell/actions)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)

Launch AI coding tools and local LLMs in Docker containers.

## Documentation & Reports

| Resource | Description |
|----------|-------------|
| [API Documentation](https://svange.github.io/augint-shell/ai_shell.html) | pdoc-generated API reference |
| [Test Coverage](https://svange.github.io/augint-shell/coverage/htmlcov/) | HTML coverage report |
| [Test Results](https://svange.github.io/augint-shell/tests/test-report.html) | Unit test results |
| [Security Scans](https://svange.github.io/augint-shell/security/security-reports.html) | Bandit, pip-audit results |
| [License Compliance](https://svange.github.io/augint-shell/compliance/license-report.html) | Dependency license report |
| [PyPI Package](https://pypi.org/project/augint-shell/) | Published package |

## Installation

```bash
pip install augint-shell
```

Or as a dev dependency:

```bash
uv add --dev augint-shell
```

## Quick Start

```bash
# Launch Claude Code in the current project
ai-shell claude

# Launch with extra args
ai-shell claude -- --debug

# Set up local LLM stack (first time)
ai-shell llm setup

# Launch opencode with local LLM
ai-shell opencode
```

## Commands

### AI Tools

| Command | Description |
|---|---|
| `ai-shell claude` | Launch Claude Code |
| `ai-shell claude-x` | Claude Code with skip-permissions |
| `ai-shell codex` | Launch Codex |
| `ai-shell opencode` | Launch opencode |
| `ai-shell aider` | Launch aider with local LLM |
| `ai-shell shell` | Bash shell in dev container |

### LLM Stack

| Command | Description |
|---|---|
| `ai-shell llm up` | Start Ollama + Open WebUI |
| `ai-shell llm down` | Stop LLM stack |
| `ai-shell llm pull` | Pull configured models |
| `ai-shell llm setup` | First-time setup (up + pull + configure) |
| `ai-shell llm status` | Show status and available models |
| `ai-shell llm logs` | Tail LLM stack logs |
| `ai-shell llm shell` | Shell into Ollama container |

### Container Management

| Command | Description |
|---|---|
| `ai-shell manage status` | Show dev container status |
| `ai-shell manage stop` | Stop dev container |
| `ai-shell manage clean` | Remove container and volumes |
| `ai-shell manage logs` | Tail dev container logs |
| `ai-shell manage pull` | Pull latest Docker image |

## Configuration

Optional `ai-shell.toml` in your project root:

```toml
[container]
image = "svange/augint-shell"
image_tag = "latest"
extra_env = { MY_VAR = "value" }

[llm]
primary_model = "qwen3-coder:30b-a3b-q4_K_M"
fallback_model = "huihui_ai/llama3.3-abliterated"
context_size = 32768
ollama_port = 11434
webui_port = 3000
```

Global config at `~/.config/ai-shell/config.toml` is also supported.

`ai-shell` does not manage tool-specific config files for Codex, OpenCode, or
Aider. Use `augint-opencodex` or the tools' native config files for those, and
use `ai-shell` for container/runtime settings such as AWS profiles, local LLM
ports, and Claude options.

## How It Works

- Pulls a pre-built Docker image from Docker Hub (`svange/augint-shell`)
- Creates per-project containers named `augint-shell-{project}-dev`
- Mounts your project directory, SSH keys, AWS credentials, and tool configs
- Runs AI tools interactively inside the container
- Supports concurrent instances across multiple projects

## Attaching to your Windows Chrome (`--local-chrome`)

The dev container cannot open a browser on the Windows host, which blocks OAuth popups, CAPTCHA pages, and any "click around in a logged-in site" task. `ai-shell claude --local-chrome` bridges Claude inside the container to your *real* Chrome on Windows through the Chrome DevTools Protocol, using the official [`chrome-devtools-mcp`](https://github.com/ChromeDevTools/chrome-devtools-mcp) server.

What you get:

- Claude drives Chrome tabs on your Windows desktop, visible in real time.
- Uses a **separate Chrome profile per project** -- your normal browsing is untouched, and each repo keeps its own logged-in state.
- No Chrome extension. No third-party service. All traffic stays on `localhost` between the container and the host.

### How it works

```bash
ai-shell claude --local-chrome
```

`ai-shell` automatically:
1. Computes a stable debug port and Chrome profile for the current project.
2. Reuses that project's Chrome if it is already running.
3. If not, **launches Chrome** for the project on its assigned port with its own profile under `%LOCALAPPDATA%\Google\Chrome\ai-shell\...`.
4. Starts a TCP proxy inside the container and injects `chrome-devtools-mcp` as an MCP server for Claude.

No manual setup required. Chrome stays open after Claude exits so your login sessions persist. Sign in to whatever accounts you need in that Chrome window (first time only; cookies persist in the profile).

### Persisting the flag

Add to `ai-shell.toml` (or the YAML equivalent) if you always want this on for a project:

```toml
[claude]
local_chrome = true
```

Or set the environment variable: `AI_SHELL_LOCAL_CHROME=1`.

### Manual Chrome launch (fallback)

If `ai-shell` can't find `chrome.exe` automatically, launch Chrome yourself using the project-specific port and profile path that `ai-shell` prints in the error message. The shape of the command is:

```
chrome.exe --remote-debugging-port=<project-port> --remote-debugging-address=127.0.0.1 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\Google\Chrome\ai-shell\<project-slug>"
```

### Troubleshooting

- **"Chrome could not be found or launched"** -- Chrome is not installed at a standard location. Use the manual launch command above, or set the path in your system PATH.
- **Tabs appear empty / not logged in** -- Sign in to the accounts you need inside the auto-launched Chrome for that project. Cookies persist in that project's profile across sessions.
- **A different repo opened the wrong Chrome window** -- Each project now gets its own Chrome profile and debug port. Re-run from the correct repo so `ai-shell` attaches to that repo's browser instance.
- **Firefox / Safari** -- not supported. `chrome-devtools-mcp` requires a Chromium-based browser. Edge works with the same flags but has not been tested here.

## Standardization architecture

`augint-shell` also ships the skill bundle and Python machinery for
repository standardization. The system distributes work across three
repositories:

- **augint-shell** — content owner: canonical vocabulary, templates,
  generators, and the orchestration skills.
- **augint-github** (`ai-gh`) — thin GitHub-state mutation API: rulesets
  apply, config standardize, OIDC trust.
- **augint-tools** (`ai-tools`) — multi-repo workflow helpers and
  workspace enumeration via `workspace.yaml`.

Each repo releases independently. Changing a gate name is a one-repo
change in augint-shell — downstream tools read the canon at runtime.

### Ownership matrix

| Concern | Owner | Surface |
|---|---|---|
| Gate canon (`gates.json`) | augint-shell | `templates/claude/skills/ai-standardize-repo/gates.json` |
| Ruleset spec generation | augint-shell | `ai_shell.standardize.rulesets` |
| Ruleset application to GitHub | augint-github | `ai-gh rulesets apply <spec>` |
| Workflow job snippets + minimum specs | augint-shell | `templates/.../ai-standardize-pipeline/jobs/` |
| Workflow file generation | augint-shell (AI-mediated prose) | `/ai-standardize-pipeline` skill |
| Renovate config | augint-shell | `ai-shell standardize renovate` |
| Pre-commit config | augint-shell | `ai-shell standardize precommit` |
| Semantic-release config | augint-shell | `ai-shell standardize release` (tomlkit merge for python) |
| Dotfiles (`.editorconfig`, `.gitignore`) | augint-shell | `ai-shell standardize dotfiles` |
| Repo merge settings | augint-github | `ai-gh config --standardize` |
| OIDC trust | augint-shell + augint-github | `/ai-setup-oidc` skill orchestrates |
| Secrets / variables | augint-github | `chezmoi` + `ai-gh sync` |
| Workspace enumeration | augint-tools | `workspace.yaml` + `ai-tools workspace inspect/graph/foreach/...` |
| Repo / workspace workflow helpers | augint-tools | `ai-tools repo`, `ai-tools workspace` |
| Standardization orchestration (single-repo) | augint-shell | `/ai-standardize-repo` |
| Standardization orchestration (workspace) | augint-shell | `/ai-workspace-standardize` |
| Workspace bulk verify | augint-shell skill layer | `/ai-workspace-standardize --verify` loops over children calling `ai-tools standardize <child-path> --verify --json` |
| AI agent configuration | augint-shell (`.ai-shell.toml`) | container/runtime settings only — NOT tool-specific Codex/OpenCode/Aider config |

### Canonical gate vocabulary

Every repo enforces the same 5 pre-merge gates as required status checks
via branch rulesets. iac repos additionally enforce 1 post-deploy gate on
the production branch. Source of truth:
`templates/claude/skills/ai-standardize-repo/gates.json`. Skills that
name a gate read it from there; they never hardcode.

| Gate | Scope | What it checks |
|---|---|---|
| **Code quality** | all repos | linting, formatting, type checking, file hygiene |
| **Security** | all repos | Bandit/Semgrep SAST, dependency vulnerabilities |
| **Unit tests** | all repos | tests + coverage floor (>=80%) |
| **Compliance** | all repos | GPL/AGPL/LGPL license rejection |
| **Build validation** | all repos | `uv build` / `sam build` / `cdk synth` / `npm run build` / `terraform validate` |
| **Acceptance tests** | iac production only | runs on dev's tip after deploy; required context on `iac_production` ruleset; satisfied on the promotion PR |

### Repo type and language detection

Detection is code-based via `ai-shell standardize detect --json`. There
is no `.ai-shell.toml` dependency for repo-shape decisions.

**Language:**
- **Python** — `pyproject.toml` with `[project].name` AND **no** `[tool.uv].package = false`
- **Node** — `package.json` AND (no `pyproject.toml` OR `pyproject.toml` has `[tool.uv].package = false`)
- The `package = false` marker is authoritative — it says "this
  pyproject is a dependency container, not a buildable Python package"

**Repo type:**
- **iac** if ANY of: `samconfig.toml`, `cdk.json`, `*.tf` at root,
  `serverless.yml`, OR a workflow file contains `sam deploy`, `cdk
  deploy`, `terraform apply`, `aws s3 sync`, or
  `aws-actions/configure-aws-credentials`
- **library** if a workflow file publishes via
  `pypa/gh-action-pypi-publish`, `twine upload`, `uv publish`, or `npm
  publish`
- **Publish wins over deploy** when both signals are present — a
  library with SAM-based test infrastructure (e.g. `ai-lls-lib`) is
  still a library

### Pipeline architecture principles

- **Single `pipeline.yaml` per repo.** All canonical gates inline as
  jobs in one workflow. No reusable workflow split (`_gate-*.yaml`).
  This preserves the unified GitHub Actions DAG view per CI run.
- **AI-mediated merge, not Python.** The Python layer is read-only:
  `validate(path)` returns a `DriftReport`; `canonical_jobs(language,
  repo_type)` returns inline job snippets the AI uses as reference. The
  `/ai-standardize-pipeline` skill drives Claude through the merge,
  handling legacy renames (`Pre-commit checks` -> `Code quality`,
  `Integration tests`/`Smoke tests`/`E2E *` -> `Acceptance tests`),
  missing gate insertion, custom job preservation, and special patterns
  like parallelized post-deploy tests (synthetic `Acceptance tests`
  aggregator that `needs: [<parallel test jobs>]`).
- **Minimum-spec validation.** Each canonical gate declares required
  steps in order. Users may add custom steps anywhere as long as
  required ones appear in the declared order. Action SHAs and step
  `name:` fields are ignored; only `uses:` (action path substring) and
  `run:` (regex, MULTILINE+DOTALL for multi-line shell continuations)
  count.
- **One-shot, no two-phase migration.** Standardization is a single
  invocation per repo. No "run once to scaffold, edit by hand, run
  again to verify."

### Execution scopes

| Command | Scope |
|---|---|
| `/ai-standardize-pipeline [<path>]` | Single section: `pipeline.yaml` merge (AI-mediated) |
| `/ai-standardize-precommit [<path>]` | Single section: pre-commit config |
| `/ai-standardize-renovate [<path>]` | Single section: Renovate config |
| `/ai-standardize-release [<path>]` | Single section: semantic-release config |
| `/ai-standardize-dotfiles [<path>]` | Single section: `.editorconfig`, `.gitignore` |
| `/ai-standardize-repo --all [<path>]` | Full single-repo 10-step sequence |
| `/ai-standardize-repo --verify [<path>]` | Read-only drift report for a single repo |
| `/ai-workspace-standardize [--verify] [--only ...]` | Workspace-level orchestration over every child repo in dep order |

## Requirements

- Docker
- Python >= 3.12
