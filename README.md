# augint-shell

Launch AI coding tools and local LLMs in Docker containers.

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
primary_model = "qwen3.5:27b"
fallback_model = "qwen3-coder-next"
context_size = 32768
ollama_port = 11434
webui_port = 3000

[aider]
model = "ollama_chat/qwen3.5:27b"
```

Global config at `~/.config/ai-shell/config.toml` is also supported.

## How It Works

- Pulls a pre-built Docker image from Docker Hub (`svange/augint-shell`)
- Creates per-project containers named `augint-shell-{project}-dev`
- Mounts your project directory, SSH keys, AWS credentials, and tool configs
- Runs AI tools interactively inside the container
- Supports concurrent instances across multiple projects

## Requirements

- Docker
- Python >= 3.12
