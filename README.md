# augint-shell

[![PyPI version](https://badge.fury.io/py/augint-shell.svg)](https://pypi.org/project/augint-shell/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Pipeline](https://github.com/svange/augint-shell/actions/workflows/pipeline.yaml/badge.svg)](https://github.com/svange/augint-shell/actions/workflows/pipeline.yaml)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)

Launch AI coding tools (Claude Code, Codex, opencode, aider) and local LLMs (Ollama, Open WebUI, Kokoro TTS, Speaches STT) in per-project Docker containers.

---

## Pipeline Artifacts

> Reports are published to GitHub Pages on every push to `main`.

| Report | Link |
|--------|------|
| API docs | [svange.github.io/augint-shell/ai_shell.html](https://svange.github.io/augint-shell/ai_shell.html) |
| Test coverage | [svange.github.io/augint-shell/coverage/htmlcov/](https://svange.github.io/augint-shell/coverage/htmlcov/) |
| Test results | [svange.github.io/augint-shell/tests/test-report.html](https://svange.github.io/augint-shell/tests/test-report.html) |
| Security scans | [svange.github.io/augint-shell/security/](https://svange.github.io/augint-shell/security/) |
| License compliance | [svange.github.io/augint-shell/compliance/](https://svange.github.io/augint-shell/compliance/) |
| PyPI package | [pypi.org/project/augint-shell/](https://pypi.org/project/augint-shell/) |

---

## What This Does

`ai-shell` is a Python CLI that stands up:

1. **Per-project dev containers** (`augint-shell-{project}-dev`) — one per repo, runs Claude Code, Codex, opencode, or aider with your project mounted, SSH keys, AWS creds, and tool configs wired in.
2. **Host-level LLM stack** (shared singletons) — Ollama, Open WebUI, Kokoro TTS, Speaches STT, a Pipecat voice agent, and n8n on a common Docker network. GPU auto-detected.

One command replaces the old Makefile + docker-compose.yml workflow.

---

## Getting Started

> This project uses AI-assisted development. You do not need to memorize
> git commands or CI configuration — your AI agent handles that.

### Prerequisites

- Docker
- Python >= 3.12
- (Optional) NVIDIA GPU + drivers for local LLM acceleration

### First-time setup

```bash
pip install augint-shell
# or:  uv add --dev augint-shell
```

### Running locally

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

---

## How to Contribute

> Contributions are made through AI agents (Claude Code, Copilot, etc.).
> You describe what you want changed in plain language; the agent handles
> branching, coding, testing, and submitting a pull request.

1. **Open Claude Code** (or your AI agent) in this repo.
2. **Describe the change** you want — a bug fix, a new feature, a doc update.
3. The agent will:
   - Create a feature branch
   - Make the changes
   - Run pre-commit checks and tests
   - Open a pull request
4. **Review the PR** when the agent is done. CI runs automatically.
5. **Merge** once CI is green.

---

## Commands

### AI Tools

| Command | Description |
|---|---|
| `ai-shell claude` | Launch Claude Code |
| `ai-shell claude-x` | Claude Code with skip-permissions |
| `ai-shell codex` | Launch Codex |
| `ai-shell opencode` | Launch opencode |
| `ai-shell aider` | Launch aider with local LLM |
| `ai-shell shell [bash\|zsh\|fish]` | Interactive shell in dev container |

### LLM Stack

| Command | Description |
|---|---|
| `ai-shell llm up` | Start Ollama (add `--webui`, `--whisper`, `--voice-agent`, `--n8n`, `--image-gen`, or `--all`) |
| `ai-shell llm down` | Stop LLM stack |
| `ai-shell llm pull` | Pull configured models |
| `ai-shell llm models` | Browse curated model catalog |
| `ai-shell llm unload [MODEL]` | Unload models from VRAM |
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
| `ai-shell manage env [--aws]` | Show resolved environment variables |

---

## Configuration

Optional `.ai-shell.yaml` in your project root (YAML default, TOML also accepted). Run `ai-shell init` for the full template.

```yaml
container:
  image: svange/augint-shell
  image_tag: latest
  extra_env:
    MY_VAR: value
  dev_ports: [3000, 4200, 5000, 5173, 5678, 8000, 8080, 8888]
  extra_ports: []

openai:
  profile: work  # resolves OPENAI_API_KEY_WORK from .env

llm:
  primary_chat_model: qwen3.5:27b
  secondary_chat_model: huihui_ai/qwen3.5-abliterated:27b
  primary_coding_model: qwen3-coder:30b-a3b-q4_K_M
  secondary_coding_model: huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M
  context_size: 32768
  ollama_port: 11434
  webui_port: 3000
  comfyui_port: 8188
  extra_models: []
```

Global config at `~/.ai-shell.yaml` or `~/.config/ai-shell/config.yaml` also supported.

---

## Local LLM stack

Four role-specific model slots, each sized for an RTX 4090 (24 GiB VRAM). All four defaults together total ~74 GB on disk.

| Slot | Default | Size | Role | Routed to |
|---|---|---|---|---|
| `primary_chat_model` | `qwen3.5:27b` | 17 GB | Best chat model that fits a 4090 | Open WebUI default |
| `secondary_chat_model` | `huihui_ai/qwen3.5-abliterated:27b` | 17 GB | Best uncensored chat (abliterated Qwen3.5) | Open WebUI (selectable) |
| `primary_coding_model` | `qwen3-coder:30b-a3b-q4_K_M` | 19 GB | Best agentic coder with explicit Ollama tools badge | opencode / aider default |
| `secondary_coding_model` | `huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M` | 19 GB | Best uncensored coder | opencode (selectable) |

**Optional stacks** (not auto-started; opt-in with `ai-shell llm up --<flag>` or `--all`):

| Flag | Service | Port | Notes |
|---|---|---|---|
| `--webui` | Open WebUI | 3000 | Implies `--voice` so Kokoro is wired as "read aloud" backend. Use `--no-voice` to skip. |
| `--voice` | Kokoro TTS | 8880 | OpenAI-compatible `/v1/audio/speech` |
| `--whisper` | Speaches STT | 8001 | OpenAI-compatible `/v1/audio/transcriptions`. GPU image auto-used when NVIDIA is detected |
| `--voice-agent` | Pipecat voice agent | 8010 | Push-to-talk PWA (Speaches → Ollama → Kokoro). See `VOICE_AGENT_PLAN.md` |
| `--image-gen` | ComfyUI | 8188 | GPU image generation. Wires into WebUI when combined with `--webui` |
| `--n8n` | n8n | 5678 | Workflow automation |

---

## OpenAI multi-account switching (`--openai-profile`)

Codex and opencode support switching between multiple OpenAI accounts via named profiles in `.env`:

```bash
# .env
OPENAI_API_KEY_WORK=sk-proj-...
OPENAI_ORG_ID_WORK=org-...
OPENAI_API_KEY_PERSONAL=sk-proj-...
```

```bash
ai-shell codex --openai-profile work
ai-shell opencode --openai-profile personal
```

Set a default in config (`openai.profile: work`) or via `AI_SHELL_OPENAI_PROFILE=work`.

---

## Attaching to Windows Chrome (`--local-chrome`)

`ai-shell claude --local-chrome` bridges Claude inside the container to your real Chrome on Windows via the Chrome DevTools Protocol (using `chrome-devtools-mcp`). Unblocks OAuth popups, CAPTCHA pages, and "click around in a logged-in site" tasks.

- Claude drives Chrome tabs on your Windows desktop in real time.
- **Separate Chrome profile per project** — your normal browsing untouched, each repo keeps its own logged-in state.
- All traffic stays on `localhost`.

Set `[claude] local_chrome = true` in `ai-shell.toml` (or `AI_SHELL_LOCAL_CHROME=1`) to persist.

---

## Requirements

- Docker
- Python >= 3.12
- (Optional) NVIDIA GPU for local LLM acceleration
