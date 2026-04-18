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
| `ai-shell shell [bash\|zsh\|fish]` | Interactive shell in dev container (Starship prompt, Oh My Zsh, Fisher) |

### LLM Stack

| Command | Description |
|---|---|
| `ai-shell llm up` | Start Ollama (add `--webui`, `--whisper`, `--voice-agent`, `--n8n`, `--image-gen`, or `--all`) |
| `ai-shell llm down` | Stop LLM stack |
| `ai-shell llm pull` | Pull configured models |
| `ai-shell llm models` | Browse curated model catalog with config/pulled/available status |
| `ai-shell llm unload [MODEL]` | Unload models from VRAM (frees GPU for ComfyUI, etc.) |
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
| `ai-shell manage env` | Show resolved environment variables (add `--aws` for Bedrock env) |

## Configuration

Optional `.ai-shell.yaml` in your project root (YAML is the default; TOML is
also accepted — see `ai-shell init` for the full generated template with
per-section rationale):

```yaml
container:
  image: svange/augint-shell
  image_tag: latest
  extra_env:
    MY_VAR: value
  dev_ports: [3000, 4200, 5000, 5173, 5678, 8000, 8080, 8888]  # forwarded from container
  extra_ports: []  # additional container ports to forward

openai:
  profile: work  # resolves OPENAI_API_KEY_WORK from .env (see --openai-profile)

llm:
  primary_chat_model: qwen3.5:27b
  secondary_chat_model: huihui_ai/qwen3.5-abliterated:27b
  primary_coding_model: qwen3-coder:30b-a3b-q4_K_M
  secondary_coding_model: huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M
  context_size: 32768
  ollama_port: 11434
  webui_port: 3000
  comfyui_port: 8188
  extra_models: []   # additional Ollama tags to pull alongside the 4 slots
```

Global config at `~/.ai-shell.yaml` or `~/.config/ai-shell/config.yaml` is
also supported.

> The previous `primary_model` / `fallback_model` keys were removed. They were
> role-ambiguous (chat vs. coding). If you had them set, move them to the
> matching slot above. ai-shell will refuse to start with those legacy keys
> present and print a migration hint.

`ai-shell` does not manage tool-specific config files for Codex, OpenCode, or
Aider. Use `augint-opencodex` or the tools' native config files for those, and
use `ai-shell` for container/runtime settings such as AWS profiles, local LLM
ports, and Claude options.

### Local LLM stack

Four role-specific model slots, each sized for an RTX 4090 (24 GiB VRAM). All
four defaults together total ~74 GB on disk.

| Slot | Default | Size | Role | Routed to |
|---|---|---|---|---|
| `primary_chat_model` | `qwen3.5:27b` | 17 GB | Best chat model that fits a 4090 | Open WebUI default |
| `secondary_chat_model` | `huihui_ai/qwen3.5-abliterated:27b` | 17 GB | Best uncensored chat (abliterated Qwen3.5) | Open WebUI (selectable) |
| `primary_coding_model` | `qwen3-coder:30b-a3b-q4_K_M` | 19 GB | Best agentic coder with explicit Ollama tools badge | OpenCode / Aider default |
| `secondary_coding_model` | `huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M` | 19 GB | Best uncensored coder (abliterated Qwen3-Coder) | OpenCode (selectable) |

Each pair shares a base model — primary is the standard aligned release;
secondary is the huihui.ai abliterated variant (refusal directions neutralized
via weight surgery, benchmark quality preserved). Switching primary <->
secondary within a slot keeps tool formats and context semantics identical.

`ai-shell llm pull` / `ai-shell llm setup` downloads all 4 slots plus any
`extra_models` entries, deduped.

**Three caveats worth knowing:**

1. **Qwen3.5 Ollama tool calling is broken** ([ollama #14493](https://github.com/ollama/ollama/issues/14493), open). This does not affect Open WebUI's default chat with web search and RAG — those run server-side in WebUI without touching Ollama's tools API. It does affect agent CLIs routed through Ollama's `/v1/chat/completions` tools array, which is why the chat slots are Qwen3.5 and the coding slots are Qwen3-Coder (explicit tools badge, working parser).
2. **Ollama `num_ctx` defaults to 4096** for every model, well below what modern agent prompts need (Claude Code sends ~35K tokens). `context_size` in your config is applied via Modelfile override during `llm setup` — leave it at 32768 unless you have a reason.
3. **Qwen3-Coder tool-count cliff**: reliable native `tool_calls` emission below ~5 registered tools; above that the model may emit XML inside content and some parsers miss it. Keep agent tool sets tight.

**Optional stacks** (not auto-started; opt-in with `ai-shell llm up --<flag>` or `--all`):

| Flag | Service | Port | Notes |
|---|---|---|---|
| `--webui` | Open WebUI | 3000 | Implies `--voice` so Kokoro is wired as the "read aloud" backend. Use `--no-voice` to skip. |
| `--voice` | Kokoro TTS | 8880 | OpenAI-compatible `/v1/audio/speech`. |
| `--whisper` | Speaches STT | 8001 | OpenAI-compatible `/v1/audio/transcriptions`. Default model: `Systran/faster-distil-whisper-large-v3` (preloaded). GPU image used automatically when NVIDIA is detected; container auto-recreates if GPU availability changes. |
| `--voice-agent` | Pipecat voice agent | 8010 | Experimental. Built locally on first use from `docker/voice-agent/`. Push-to-talk PWA over WebSocket (Speaches STT -> Ollama -> Kokoro TTS). See `VOICE_AGENT_PLAN.md`. |
| `--image-gen` | ComfyUI | 8188 | GPU image generation. Wires into WebUI when combined with `--webui`. Pass `HF_TOKEN` via `--env` for FLUX.1-dev downloads. |
| `--n8n` | n8n | 5678 | Workflow automation, standalone. |

## How It Works

- Pulls a pre-built Docker image from Docker Hub (`svange/augint-shell`)
- Creates per-project containers named `augint-shell-{project}-dev`
- Mounts your project directory, SSH keys, AWS credentials, and tool configs
- Runs AI tools interactively inside the container
- Supports concurrent instances across multiple projects
- **Deterministic port mapping**: each project gets stable, unique host ports via hash so multiple projects can run simultaneously without conflicts
- **Stale image detection**: when using the `latest` tag, automatically detects outdated container images and recreates with the latest pull
- **MOTD dashboard**: on shell entry, displays tool versions, GitHub pipeline status, masked API keys, mount availability, LLM service status, and port mappings
- GPU-capable containers (Ollama, Kokoro, Whisper, ComfyUI) auto-detect NVIDIA GPUs and recreate themselves if GPU availability changes

## OpenAI multi-account switching (`--openai-profile`)

Codex and opencode support switching between multiple OpenAI accounts via named
profiles stored in your `.env` file:

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

`--openai-profile <NAME>` resolves `OPENAI_API_KEY_{NAME}` (and optionally
`OPENAI_ORG_ID_{NAME}`) from `.env` and injects them as `OPENAI_API_KEY` /
`OPENAI_ORG_ID` into the container. You can also set a default in config:

```yaml
openai:
  profile: work
```

Or via environment variable: `AI_SHELL_OPENAI_PROFILE=work`.

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

## Requirements

- Docker
- Python >= 3.12
