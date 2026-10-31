# CLAUDE.md

Project-specific guidance for Claude Code. All canonical workflow, CI, commit, and standardization rules live in the `ai-cc-tools` plugin (`augint-workflow`, `ai-standardize-*` skills) — do not duplicate them here.

## Overview

Python CLI tool (`ai-shell`) for launching AI coding tools and local LLMs in Docker containers. Published to PyPI as `augint-shell`. Replaces Makefile + docker-compose.yml workflow with per-project containers and optional `.ai-shell.yaml` config.

## Development

```bash
uv sync --all-extras                         # Install all deps
uv run pytest                                # All tests
uv run pytest tests/unit/test_config.py      # Single test file
uv run pytest -k "test_load_missing"         # Single test by name
uv run pytest --cov=src --cov-fail-under=80  # With coverage
uv run ruff check src/                       # Lint
uv run ruff format src/ tests/               # Format
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # All pre-commit hooks
```

## Architecture

### Dependency flow

```
CLI commands (cli/commands/)
  -> ContainerManager (container.py)
    -> AiShellConfig (config.py)
    -> defaults.py (constants, mount/env builders)
    -> gpu.py (NVIDIA detection)
```

### Two container categories

1. **Per-project dev containers** (`augint-shell-{project}-dev`) — one per project directory. Created on-demand, reused if running. Uses `tail -f /dev/null` to stay alive; commands exec into it.
2. **Host-level LLM stack** (singletons) — Ollama, Open WebUI, Kokoro TTS, Speaches STT, voice-agent, and n8n containers shared across projects via the `augint-shell-llm` Docker network. Persistent named volumes. GPU auto-detected for Ollama, Kokoro, and Whisper; those containers auto-recreate when GPU availability changes. Voice-agent image is built locally on first use.

### Config layering (highest priority first)

1. CLI flags (`--project`)
2. Environment variables (`AI_SHELL_*` prefix)
3. Project config (first match: `.ai-shell.yaml` > `.ai-shell.yml` > `.ai-shell.toml` > `ai-shell.toml`)
4. Global config (`~/.augint/.ai-shell.yaml` > `~/.ai-shell.yaml` > `~/.ai-shell.yml` > `~/.ai-shell.toml` > `~/.config/ai-shell/config.*`)
5. Hard-coded defaults in `defaults.py`

### Container naming

`project_dir.name` -> `sanitize_project_name()` (lowercase, special chars to hyphens, collapsed) -> `dev_container_name()` -> `augint-shell-{name}-dev`. Override with `--project` flag.

### Mount assembly

Dev containers mount: project dir, UV cache volume (shared), and conditionally: `~/.claude`, `~/.codex`, `~/.pi`, `~/.augint`, `~/.ssh` (ro), `~/.aws`, `~/.config/gh`, `~/.gitconfig` (ro), Docker socket (ro), plus `extra_volumes` from config.

**node_modules overlays**: the project root `node_modules` is always a per-project named volume. Workspace globs from `pnpm-workspace.yaml` (`packages:`) and `package.json` (`workspaces`) are read by `workspace_node_modules_globs()` and every matching directory that has a `package.json` gets its own overlay too, so pnpm on the Windows host and pnpm in the container never rewrite each other's workspace links. `container.node_modules_paths` adds explicit globs (no `package.json` requirement).

**Home-config isolation**: `container.isolate_home_paths` (config key, `AI_SHELL_ISOLATE_HOME_PATHS` env var) lists home-config basenames (e.g. `.claude`, `.codex`) to back with a shared named volume (`augint-shell-home-{name}`) instead of a host bind mount, so nothing is written into the host home dir. The volume persists across container recreations and is shared across all projects — set it in `~/.augint/.ai-shell.yaml` to apply machine-wide. Single-file configs can't be volume-backed: when named (or, for `.claude.json`, when `.claude` is isolated) their host bind is dropped and config stays container-local. Empty (default) = current bind-mount behavior. See `build_dev_mounts` / `home_config_volume_name` in `defaults.py`.

### Environment assembly

Priority: `extra_env` > `./.env` > `~/.augint/.env` > `os.environ` > defaults. Layered .env loading merges `~/.augint/.env` (global shared) then `./.env` (project override). AWS IAM keys are intentionally NOT passed through (only `AWS_PROFILE` + `AWS_REGION`; relies on `~/.aws` bind mount). `IS_SANDBOX=1` is always set. Shared vars (`PRIMARY_CHAT_MODEL`, `OLLAMA_PORT`, `ANTHROPIC_API_KEY`, etc.) are passed through to container env for sibling tools. `PATH` includes `/root/.opencode/bin`.

**GitHub auth**: Default auth is SSO via the `~/.config/gh` bind mount. `GH_TOKEN`/`GITHUB_TOKEN` are NOT injected by default. Pass `--env [.env]` on any dev container CLI command (`claude`, `codex`, `opencode`, `pi`, `shell`, `manage env`) to opt in to loading a `.env` file and injecting GH_TOKEN. Without a value, `--env` defaults to `./.env`.

**Claude accounts**: `ai-shell claude --account NAME` (or `claude.account` config / `AI_SHELL_CLAUDE_ACCOUNT`) injects `.env` key `CLAUDE_CODE_OAUTH_TOKEN_{NAME}` as `CLAUDE_CODE_OAUTH_TOKEN` at exec time. `default` injects nothing. Suffixed tokens are never passed through to containers. Because `docker exec -e` cannot remove container-level vars, the claude command is prefixed with `env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN` (tmux panes: `unset ...;`, token via `tmux new-session -e`). `--account` with no value lists accounts. See `build_dev_environment` and `_claude_exec_env` in `cli/commands/tools.py`.

**Login profiles**: a second credential kind for an account. `CLAUDE_CONFIG_DIR=/root/.augint/claude-accounts/{slug}` (host: `~/.augint/claude-accounts/{slug}`, inside the existing `~/.augint` bind, so no mount change) gives the account its own `claude auth login`, settings and history. Chosen when `--rc` or `--login` is given (`claude_login=True` in `build_dev_environment`), or when the account has no token but the directory exists. In that mode `CLAUDE_CODE_OAUTH_TOKEN` is also unset (`CLAUDE_REMOTE_CONTROL_UNSET_VARS`). Before launch, `claude auth status` (exit 0 = logged in; for `--rc` its `authMethod` must be `claude.ai`) decides whether `claude auth login` runs first (`_ensure_claude_login`). That login is driven from the host over pipes (`claude_login.py`): the authorize URL is read from the process output and opened in the account's Chrome through the DevTools port (`PUT /json/new`), the code is read from a `click.prompt` on the host and written to the process stdin. Passing both through the `docker exec -it` TTY on Windows mangles them (wrapped URL -> broken `state` -> "That code wasn't accepted"). If no URL appears, it falls back to the interactive TTY login. Per-account defaults live in `claude.accounts.<name>` (`ClaudeAccountConfig`: `chrome_profile`, `local_chrome`). A new profile is seeded with a `CLAUDE.md` that imports the host's `~/.claude/CLAUDE.md` (`seed_claude_login_profile`, written only when the profile has none); settings, plugins and rules are not shared.

**Remote Control**: `ai-shell claude --rc [NAME]` runs `claude remote-control --name NAME [--permission-mode bypassPermissions]` via `exec_interactive` (no `-c` retry). Claude Code rejects API keys, setup-token tokens and Bedrock for it, so the exec env is stripped of `CLAUDE_REMOTE_CONTROL_UNSET_VARS` and `--aws` errors. Server mode also refuses global flags such as `--mcp-config`, so with `--local-chrome` the chrome-devtools server is registered with `claude mcp add-json --scope local` in the active config dir and project workdir (`_register_chrome_mcp`). Incompatible with `--multi`/`--team`/`--interactive`.

**Account-scoped Chrome**: with a named account, `--local-chrome` keys the host Chrome (profile dir + debug port) by `account-{chrome_profile or account}` instead of the project (`local_chrome._chrome_slug`), so one account shares one browser across repos and two accounts never share one.

**Chrome proxy and the VPN container**: `--chrome-proxy` > `claude.accounts.<name>.chrome_proxy` > `claude.chrome_proxy` / `AI_SHELL_CHROME_PROXY` (`_account_chrome_proxy`) becomes Chrome's `--proxy-server` when ai-shell launches it (`launch_chrome(proxy=)`), for a host whose own address sites refuse. The value `vpn` means ai-shell's own container (`vpn.py`): gluetun, NordVPN over WireGuard, host-level singleton `augint-shell-vpn`, HTTP proxy on `127.0.0.1:<vpn.proxy_port>`, `NET_ADMIN` + `/dev/net/tun` (rootless Podman is enough). `_resolve_chrome_proxy` starts it (`ensure_vpn_for_config`) before any window opens. The credential is `NORDVPN_TOKEN` (or `NORDVPN_WIREGUARD_PRIVATE_KEY`) from the layered `.env`; the token is exchanged once for the key (`fetch_wireguard_key`) and cached at `~/.augint/vpn/nordvpn-wireguard.key`. A label (`ai-shell.vpn.config`) holds a digest of the settings, so a change recreates the container; a firewall failure in the log recreates it once with `FIREWALL=off` and writes `~/.augint/vpn/firewall-off`. `ai-shell vpn up|down|status` in `cli/commands/vpn.py`. Only the browser is proxied, never the dev container.

**Sign-in without the DevTools port**: Google refuses to sign in inside a browser with a DevTools port. With `--local-chrome`, `_launch_loaded_config_claude` therefore runs the login BEFORE `_configure_local_chrome`: `_plain_chrome_login` checks `claude auth status` (`_claude_login_needed`) and, when a login is due, drives the piped login with an `open_url` that calls `launch_plain_chrome(..., close_running=True)` (same profile dir, no port, configured proxy; a running debug-port Chrome on that profile is quit first by `close_chrome_profile`, `pkill -f` on POSIX / `taskkill` via PowerShell on Windows), then closes the window (`PlainChrome.close`, graceful so cookies flush) and lets the debug-port Chrome open on the session. `ai-shell chrome [--account NAME] [URL]` is the same window by hand. Without `--local-chrome` the piped login prints the URL for any browser.

**Host Chrome on Linux/macOS**: `find_chrome()` checks Windows paths, macOS app bundles, then `PATH` (`google-chrome`, `chromium`, ...). `chrome_bind_address()` decides what the debug port binds to: loopback on Docker Desktop hosts, but on Linux the IP the container resolves for `host.docker.internal` (`getent hosts` inside the container), because Linux containers cannot reach a loopback-only listener. The in-container node proxy and `host.docker.internal` (`extra_hosts: host-gateway`) are unchanged. Untested on podman; needs the `docker` CLI shim and podman 4.1+.

### OpenCode web mode

`opencode` is a Click group (`invoke_without_command=True`). Default invocation launches the TUI; subcommands add web server features.

- **`opencode --web`** — runs `opencode web` inside the container with `--mdns`, `--cors '*'`, `--hostname 0.0.0.0`. Interactive (foreground).
- **`opencode serve`** — runs `opencode serve` detached (`exec_detached()`), then discovers git repos under CWD and registers each as a project via the opencode HTTP API (`POST /project/:base64path/session`). Prints server URL, mDNS name, and registered project list.
- **`opencode status`** — parses `pgrep -af opencode` output inside the container to show server state and attached terminal count.

mDNS domain defaults to `sanitize_project_name().local`. PATH includes `/root/.opencode/bin` so `opencode` is available in interactive shells.

### Claude retry logic

Default: runs with `-c` (continue previous conversation). If it fails fast (< 5 seconds), retries without `-c` (assumes no prior conversation exists).

### Pi integration

Pi (`@mariozechner/pi-coding-agent`) is a provider-agnostic terminal coding agent installed via npm. It connects to Ollama via `models.json` (template in `src/ai_shell/templates/pi/`). The `ai-shell pi` command checks Ollama is running before launch. Config persists via `~/.pi` bind mount. Supports `--aws` (Bedrock), `--openai-profile`, and `--login` (OAuth).

### T3 Code integration

`--t3` on `claude`, `codex`, `pi`, `opencode` and `shell` runs `t3 serve` (npm package `t3`) inside the dev container so the project can be driven from the T3 Code desktop/web/mobile app. Logic lives in `t3.py`; the CLI commands only call `_attach_t3` in `cli/commands/tools.py`.

- Container port `3773` is in `DEFAULT_DEV_PORTS`, so every dev container publishes it on a stable per-project host port. `t3 serve` is pinned to `--host 0.0.0.0 --port 3773` because its web mode otherwise scans upward for a free port and lands outside the published mapping.
- `t3 pair` prints a URL built from the container's own address, which is unreachable from a phone. Only the token is portable, so `t3.py` re-builds the URL against the host LAN IP + published port and renders its own QR (segno).
- `t3 serve` does not auto-create a project for its cwd, hence the explicit `t3 project add`.
- `~/.t3` is a **per-project** named volume (`augint-shell-t3-{unique_project_name}`) — a T3 environment is its data dir, so sharing one across containers would mean several servers on one sqlite file. `~/.t3/tools` is a shared volume so the managed cloudflared binary downloads once. The host's `~/.t3` is deliberately never bind-mounted.
- Readiness probe is `GET /.well-known/t3/environment` (what t3's own CLI uses).

### Expo integration

`--expo` (and auto-detection) on `claude`, `codex`, `pi`, `opencode` and `shell` starts `npx expo start --tunnel` inside the dev container and prints the tunnel URL as a QR before the agent takes the terminal. Logic lives in `expo.py`; the CLI commands only call `_attach_expo` in `cli/commands/tools.py`.

- **Tunnel only.** ngrok dials outbound from the container, so no published port is involved. LAN mode is deliberately not implemented: dev ports are hash-assigned into 10000-39999, not identity-mapped, so Metro would advertise an unreachable `:8081`. Port 8081 (`EXPO_METRO_PORT`) is in `DEFAULT_DEV_PORTS` anyway for host browser access.
- **No Expo account required.** `@expo/cli` uses its own ngrok token and falls back to `anonymous` in the tunnel hostname when logged out. `~/.expo` is bind-mounted so `expo login`/EAS sessions persist. A *robot* `EXPO_TOKEN` makes the CLI refuse to tunnel (`NGROK_ROBOT`); `_startup_failure()` detects that signature in the log.
- **QR stability** comes for free: Expo persists the tunnel's random segment in the project's `.expo/settings.json`, which is bind-mounted. Nothing is pinned with `EXPO_TUNNEL_SUBDOMAIN`.
- **`@expo/ngrok`** is baked into the image and installed on demand by `ensure_ngrok()` for older images — the Expo CLI resolves it from the global install and will not prompt on a non-TTY start.
- **Detection** (`detect()`) requires an `expo` dependency *and* an app config for auto-start; `--expo` requires only the dependency. The installed-dependency check runs *inside* the container because `node_modules` is a container-local named volume.
- Tri-state flag: `--expo` (explicit, failures are fatal), `--no-expo`, or unset (auto-detect, failures degrade to a warning so a broken dev server never costs a Claude session). `expo.auto: false` / `AI_SHELL_EXPO_AUTO=0` disables auto-detection. `shell` never auto-detects.
- The detached server outlives the tool session; re-running just re-prints the QR.

### Scaffold system

`ai-shell init` and per-tool `--init`/`--update`/`--reset`/`--clean` flags write tool config files (`.claude/`, `.codex/`, `.agents/`, etc.) into the project. `--update` merges settings (preserves user customizations) and overwrites managed skills. `--reset` force-overwrites all managed files. `--clean` removes all managed paths then recreates them fresh.

**Claude Code skills** are delivered via the `augint-workflow` plugin in the `ai-cc-tools` repo, not scaffolded by `ai-shell`. `ai-shell claude --init` only writes `settings.json`. Skills for agents/opencode/codex are still scaffolded from `src/ai_shell/templates/agents/skills/`.

## Testing

All tests are unit tests in `tests/unit/`. Docker SDK is mocked via fixtures in `tests/conftest.py` (`mock_docker_client`, `mock_container_manager`). CLI tests use Click's `CliRunner` with patched `ContainerManager` and `load_config`. Tests verify command argument building and container creation kwargs, not actual Docker operations.

An autouse `isolate_home` fixture in `tests/unit/conftest.py` patches `pathlib.Path.home` to a clean temp dir for every test, preventing tests from reading real `~/.augint/` config. Tests that need specific global config content should either create files inside the yielded `fake_home` or use their own `with patch(...)` override.

## Project-specific notes

- Version lives in `pyproject.toml:project.version` and `src/ai_shell/__init__.py:__version__`. Python Semantic Release owns both.
- Tag format is `v{version}` (canonical per ai-standardize-release).
- Do not hand-edit files under `.agents/skills/` — scaffolded from `src/ai_shell/templates/agents/skills/`. Edit the templates and re-run scaffold.
