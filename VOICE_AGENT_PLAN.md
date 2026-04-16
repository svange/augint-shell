# Voice Agent — Implementation Plan

Experimental feature: always-listening voice assistant with wake word, STT,
tool-using agent, TTS response. Single-user, LAN-first, browser PWA client,
reverse-proxied through the user's Nginx Proxy Manager for TLS.

## Goal

From a browser on any device on the LAN (or eventually anywhere via the
user's NPM + domain), say a wake phrase and hold a barge-in-capable voice
conversation with an agent that has filesystem, web, and GitHub tools, and
persistent memory.

## Architecture

```
[Browser PWA on phone/laptop]                   [augint-shell host]
 mic (always-stream after login)                  Speaches (new, STT)
 audio player                      ─── audio ─▶  voice-agent (new, Pipecat)
 visual state machine              ◀── TTS  ───  Kokoro (existing)
                                                        │
                                                  openWakeWord (server-side)
                                                  Silero VAD (server-side, Pipecat)
                                                  Ollama (existing) default
                                                  providers: Anthropic/OpenAI (keys in ro mount)
                                                  tools: filesystem, Brave, GitHub (via Pipecat MCPClient)
                                                  memory: sqlite (named volume)
```

Transport: **WebSocket** (not WebRTC). Proxies cleanly through NPM, simpler
debugging, latency irrelevant at this scale.

Client: static PWA served by the voice-agent container. Browser captures mic
via `getUserMedia` and streams 16 kHz mono PCM over WebSocket continuously
after login. **Wake detection runs server-side** using the Python
`openwakeword` package against the incoming stream — the browser does not
run wake-word inference. Always-streaming on LAN is ~256 kbps, well within
budget, and avoids committing to an unmaintained browser WASM port. If
bandwidth becomes an issue later we can revisit browser-side wake via
`dnavarrom/openwakeword_wasm` (Phase 7+).

TLS: user routes a subdomain of `svrd.link` through their existing NPM with
a Let's Encrypt cert. Voice-agent container publishes an HTTP port on
0.0.0.0; NPM terminates TLS and proxies to it. No mkcert, no self-signed.

## Isolation posture

Voice-agent container bind mounts (all read-only unless noted):
- `~/.config/ai-shell/providers/` ro — per-provider API key files, chmod 600
- `~/.claude` ro — Claude Code OAuth session (reusable via Agent SDK)
- `~/.config/gh` ro — GitHub CLI auth for GitHub MCP
- `~/gigachad` rw — only writable host dir (read + write for filesystem MCP)
- Named volume for sqlite memory
- Network: `augint-shell-llm` only; no Docker socket, no host network

## Stack context (existing, don't re-invent)

Services defined as Python `ensure_*` methods, not docker-compose. Constants
in `defaults.py`, schema in `config.py` (dataclass + YAML loader), CLI in
`cli/commands/llm.py`. All new services follow this pattern.

Relevant files:
- `src/ai_shell/defaults.py` — container/image/volume/port constants
- `src/ai_shell/config.py` — `AiShellConfig` dataclass + YAML/TOML loader
- `src/ai_shell/container.py` — `ContainerManager` with `ensure_*` methods
- `src/ai_shell/cli/commands/llm.py` — Click CLI + `_stack_flags` decorator
- `tests/unit/conftest.py` — `mock_docker_client`, `mock_container_manager`
- `tests/unit/test_container_*.py` — patterns for testing `ensure_*`
- `tests/unit/test_cli_*.py` — patterns for testing CLI commands

Extension pattern for a new host-level service (follow `ensure_kokoro`):
1. Add constants to `defaults.py` (`FOO_CONTAINER`, `FOO_IMAGE`,
   `FOO_DATA_VOLUME`, `DEFAULT_FOO_PORT`)
2. Add fields to `AiShellConfig` and the YAML/env loader paths
3. Add `ensure_foo()` to `ContainerManager` (copy `ensure_kokoro` shape)
4. Add `--foo` flag to `_stack_flags` in `llm.py`, wire into `_resolve_stacks`
5. Wire into `llm_up`, `llm_down`, `llm_clean`, `llm_setup`, `llm_status`,
   `llm_logs`
6. Unit tests for the `ensure_*` method and CLI commands

Default LLM models (already in `defaults.py`, validated April 2026):
- Primary chat: `qwen3.5:27b`
- Secondary chat (uncensored): `huihui_ai/qwen3.5-abliterated:27b`
- Primary coding: `qwen3-coder:30b-a3b-q4_K_M`
- Secondary coding (uncensored): `huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M`

Voice-agent will reuse the primary chat slot by default, with its own model
override knobs in the voice config section (see Phase 2).

## Decisions locked in

| Decision | Choice |
|---|---|
| Wake-word engine | **server-side** Python `openwakeword`, pretrained "hey_jarvis"; browser streams audio always after login. Custom "GigaChad" deferred. |
| STT | **Speaches** (renamed successor to the archived `fedirz/faster-whisper-server`), OpenAI-compatible `/v1/audio/transcriptions`, Systran `distil-large-v3`. HTTP-only, final-transcripts-only — no interim results. |
| Voice-agent framework | **Pipecat 0.0.99** (pinned). 1.0.0 was released 2026-04-14, too fresh; upgrade in a dedicated ticket once the 1.0 API settles. |
| TTS | existing Kokoro via Pipecat's first-class `KokoroTTSService` (requires `pipecat-ai[kokoro]` extra). Do NOT route through `OpenAITTSService`. |
| VAD / barge-in | Silero VAD (built-in to Pipecat), VAD-driven `InterruptionFrame`. Note: `LLMUserAggregator.user_turn_strategies` (not deprecated `allow_interruptions`). |
| Audio transport | WebSocket (not WebRTC). Browser → server 16 kHz mono PCM. |
| Client | static PWA served by voice-agent |
| TLS | external, via user's NPM + Let's Encrypt |
| Auth | app-level session (bcrypt single-user from config, signed cookie) — not NPM basic auth |
| Filesystem scope | `~/gigachad` only (rw); deny `.env*` and `.git/` writes |
| Web search | Brave Search API |
| Tool protocol | MCP. Use Pipecat's built-in `MCPClient.register_tools(llm)` — it translates MCP tool schemas to each provider's native tool-calling format automatically. No per-provider plumbing needed. |
| MCP transports | stdio or Streamable HTTP (`mcp` PyPI 1.27.0 supports both). |
| Memory | sqlite, two-tier (session log + facts KV), summarize-after-N-turns |
| Providers | local Ollama default; Anthropic + OpenAI swappable; keys as ro-mounted files, never env vars |
| Model profiles | two named profiles in config (`resident` 14B+14B / `swap` 27B+8B); user-switchable, docs inline |
| Config format | YAML (`.ai-shell.yaml`), matches existing convention |

## Phased delivery

**Experimental phase**: user wants everything on main, no branch-per-phase.
Each phase still ends with a working state and tests, but no PR/automerge.

### Phase 1 — Whisper service (Speaches)

New host-level singleton. Independent and useful on its own.

Upstream: **Speaches** (`ghcr.io/speaches-ai/speaches`) is the current
maintained successor to the archived `fedirz/faster-whisper-server`. Same
OpenAI-compatible endpoint (`POST /v1/audio/transcriptions`), healthcheck
at `GET /health`, listens on port 8000 internally, runs as non-root
(`ubuntu`, UID 1000).

Deliverables:
- `defaults.py`:
  - `WHISPER_CONTAINER = "augint-shell-whisper"`
  - `WHISPER_IMAGE_GPU = "ghcr.io/speaches-ai/speaches:latest-cuda"`
  - `WHISPER_IMAGE_CPU = "ghcr.io/speaches-ai/speaches:latest-cpu"`
  - `WHISPER_DATA_VOLUME = "augint-shell-whisper-cache"`
  - `DEFAULT_WHISPER_PORT = 8001`
  - `DEFAULT_WHISPER_MODEL = "Systran/faster-distil-whisper-large-v3"`
- `config.py`: `whisper_port`, `whisper_model` fields on `AiShellConfig`;
  `llm.whisper_port` / `llm.whisper_model` YAML keys; env vars
  `AI_SHELL_WHISPER_PORT`, `AI_SHELL_WHISPER_MODEL`
- `container.py`: `ensure_whisper()` mirroring `ensure_kokoro` shape:
  - GPU auto-detect (GPU image when `detect_gpu()` returns True, CPU image otherwise)
  - Named volume mounted at **`/home/ubuntu/.cache/huggingface/hub`** (Speaches runs as `ubuntu`; a named Docker volume inherits correct ownership. Do NOT bind-mount a host dir here — it would need `chown 1000:1000` first.)
  - Publishes container port 8000/tcp → host `whisper_port` (default 8001)
  - Joins `augint-shell-llm` network
  - Env:
    - `WHISPER__INFERENCE_DEVICE=auto`
    - `PRELOAD_MODELS='["Systran/faster-distil-whisper-large-v3"]'` (pydantic-settings JSON array syntax, **not** comma-separated). Build this as `json.dumps([config.whisper_model])` to guarantee escaping.
  - No healthcheck in Docker SDK call needed (Speaches defines it in compose; we rely on status/logs).
- `cli/commands/llm.py`:
  - Add `--whisper` flag to `_stack_flags`
  - Extend `_resolve_stacks` signature to return 4-tuple `(webui, voice, whisper, n8n)` and update all call sites (llm_up, llm_down, llm_clean, llm_setup)
  - `--all` implies `--whisper`
  - Wire into `llm_up` (ensure + print URL), `llm_down` (add to targets), `llm_clean` (add to targets + volume list), `llm_setup` (ensure + URL), `llm_status` (new "Speaches stack" section + URL), `llm_logs` (include in logs loop)
- Tests:
  - Extend `test_container.py` with `TestEnsureWhisper` class mirroring `TestEnsureKokoro` (GPU image / CPU image / stopped-start / env passthrough / mount target / port mapping)
  - Extend `test_cli_llm.py`:
    - `_make_manager_config` gets `whisper_port=8001`, `whisper_model=<default>`
    - Add `_resolve_stacks` tests for `--whisper` standalone and `--all` coverage (the returned tuple now has 4 elements — update all existing assertions)
    - Add `llm up --whisper`, `llm down --whisper`, `llm clean --whisper`, status-shows-whisper tests
  - Extend `test_config.py` with whisper_port / whisper_model defaults, YAML/TOML overrides, env var overrides

Validation (manual):
- `ai-shell llm up --whisper` creates container, exposes port 8001
- `curl http://localhost:8001/health` returns 200
- `curl -F file=@test.wav -F model=Systran/faster-distil-whisper-large-v3 \
  http://localhost:8001/v1/audio/transcriptions` returns JSON transcript
- `status` / `logs` / `clean` work
- Cold-start pulls ~1.5 GB for distil-large-v3; subsequent starts are instant

### Phase 2 — Voice-agent scaffold (push-to-talk, Ollama only)

Proves the audio loop end-to-end. No wake word yet, no tools, no auth.

Deliverables:
- `defaults.py`: `VOICE_AGENT_CONTAINER`, `VOICE_AGENT_IMAGE` (locally-built
  from `docker/voice-agent/`), `VOICE_AGENT_DATA_VOLUME` for sqlite,
  `DEFAULT_VOICE_AGENT_PORT = 8010`
- `docker/voice-agent/Dockerfile` — `python:3.12-slim` +:
  - `pipecat-ai==0.0.99` with extras `[silero,kokoro,openai,ollama]` (pin
    until 1.0.0 stabilizes; 1.0.0 released 2026-04-14)
  - `openwakeword` (server-side wake detection against incoming PCM)
  - `mcp[ws]==1.27.0` (Pipecat's `MCPClient` wraps this; kept pinned)
  - `openai`, `anthropic` clients (Phase 6)
  - `fastapi`, `uvicorn[standard]`, `websockets`
  - `bcrypt`, `PyJWT` (Phase 3)
  - `httpx`, `pydantic-settings`, `pyyaml`
- `docker/voice-agent/app/`:
  - `main.py` FastAPI app: `/ws` audio WebSocket, `/` serves static PWA
  - `pipeline.py` Pipecat pipeline:
    WS audio in → Silero VAD → Speaches STT (`OpenAISTTService` pointed at
    Speaches `base_url`) → `OLLamaLLMService` → `KokoroTTSService` → WS
    audio out. Note: Pipecat's HTTP-based `OpenAISTTService` returns
    **final transcripts only** — no interim results. This is fine for our
    barge-in UX (VAD drives interruption, not STT).
  - `providers/ollama.py` — only adapter for this phase
  - `config.py` — reads `/config/voice-agent.yaml` inside container
- `config.py` (`AiShellConfig`): `voice_agent` section with nested dataclass:

  ```yaml
  voice_agent:
    port: 8010
    domain: ""                    # e.g. "x.svrd.link", empty = LAN only
    profile: "resident"
    profiles:
      resident:
        primary:   "qwen3.5:14b-instruct"
        secondary: "huihui_ai/qwen3.5-abliterated:14b"
      swap:
        primary:   "qwen3.5:27b"
        secondary: "dolphin3:8b"
    vad:
      silence_timeout_ms: 2500
      barge_in: true
    filesystem:
      root: "~/gigachad"
      read:  ["~/gigachad"]
      write: ["~/gigachad"]
      deny_glob: ["**/.env*", "**/.git/**"]
    memory:
      enabled: true
      summarize_after_turns: 20
    auth:
      username: ""                 # set before exposing through NPM
      password_bcrypt: ""
      session_secret: ""           # generated on first `voice-agent init`
    providers:
      default: "ollama"
      available: ["ollama"]        # "anthropic", "openai" in phase 6
    tools:
      filesystem: {enabled: false}  # phase 4
      web_search: {enabled: false, provider: "brave"}
      github:     {enabled: false}
    wake_word:
      enabled: false               # phase 3
      name: "hey_jarvis"
  ```

- `container.py`: `ensure_voice_agent()` — build image on first run if not
  present, run container with bind mounts listed in "Isolation posture",
  publish port on 0.0.0.0, connect to `augint-shell-llm` network
- `cli/commands/llm.py`: `--voice-agent` flag wired into the usual six places
  (implied by `--all`)
- Minimal PWA at `docker/voice-agent/app/static/`:
  - `index.html` with a push-to-talk button, mic capture, WS audio streaming
  - No wake word, no login
- Unit tests for `ensure_voice_agent`, CLI wiring, config loading

Validation (manual):
- `ai-shell llm up --voice-agent` (with Ollama, Kokoro, Whisper up)
- Browser to `http://<host>:8010`, click push-to-talk, speak, hear reply

### Phase 3 — Browser PWA + wake word + auth

Adds always-on UX and the auth boundary needed before NPM exposure.

**Wake word strategy**: server-side. The browser opens a WebSocket after
login and streams 16 kHz mono PCM continuously. A gating stage in the
Pipecat pipeline (or a pre-pipeline filter) runs `openwakeword` against
the incoming frames; only after "hey jarvis" fires does audio flow into
the STT stage. This is ~256 kbps upstream — negligible on LAN, and
avoids committing to an unmaintained browser WASM port
(`dnavarrom/openwakeword_wasm`, <6 months old, solo maintainer).

Deliverables:
- PWA overhaul:
  - `/login` page, posts to `/api/login`, sets httpOnly signed cookie
  - `/api/logout`, `/api/me`
  - WebSocket upgrade validates cookie; unauth connections dropped
  - Always-on mic capture (getUserMedia, 16 kHz mono, PCM framing)
  - Server pushes a state event when wake fires; client flips UI state
  - Barge-in UX: TTS playback cancellable (client listens for
    `InterruptionFrame`-equivalent server message and stops audio element),
    mic stays hot during playback
  - Visual state machine (idle / listening / thinking / speaking)
- Backend:
  - `auth.py` — bcrypt verify, PyJWT-signed cookies via `session_secret`
  - `wake.py` — `openwakeword.Model(wakeword_models=["hey_jarvis"])`
    feeding off the Pipecat audio-in frame. Emit a custom `WakeEventFrame`
    that gates the STT stage (either by pipeline branching or by a
    `WakeGate` processor that swallows frames pre-wake).
  - Silero VAD in Pipecat pipeline (post-wake), driven by
    `vad.silence_timeout_ms`. Barge-in uses Pipecat's built-in
    VAD→`InterruptionFrame` path. Configure via
    `LLMUserAggregator(user_turn_strategies=...)` — the 0.0.99+
    API. Do NOT use deprecated `allow_interruptions` on `PipelineParams`.
  - `ai-shell llm voice-agent set-password` CLI helper (bcrypts + writes to
    config), also generates `session_secret` if missing
- Config: `voice_agent.wake_word.enabled = true`; fail loudly on startup if
  `voice_agent.domain` is set but auth fields are empty
- Tests: auth flow (login/logout/cookie), wake-gate swallows pre-wake
  frames, VAD config wiring, startup guards

Validation:
- Login at `https://<sub>.svrd.link` (through NPM with WebSockets toggle on)
- Wake with "hey jarvis"
- Interrupt mid-response, confirm agent stops speaking

### Phase 4 — Tools via MCP

Agent gains real capabilities. Pipecat's built-in `MCPClient` handles
tool registration and per-provider schema translation — no manual
plumbing per LLM provider.

Deliverables:
- Filesystem MCP server, configurable roots, enforces `deny_glob`, scoped to
  `~/gigachad`. Use the official `@modelcontextprotocol/server-filesystem`
  (Node-based) or a small Python wrapper around the `mcp` SDK.
- Brave Search MCP — reads API key from
  `~/.config/ai-shell/providers/brave.key`
- GitHub MCP — uses `~/.config/gh` auth. Prefer the official
  `@modelcontextprotocol/server-github` if the Node dependency is
  acceptable; else wrap the `gh` CLI from Python via the `mcp` SDK.
- Wiring: one `MCPClient` per configured server (stdio transport is
  simplest). Call `MCPClient.register_tools(llm)` after the Pipecat LLM
  service is constructed — it translates MCP tool schemas into each
  provider's native tool-call format (OpenAI, Anthropic, Ollama-with-tools).
- Tool-call telemetry recorded to memory (phase 5 consumes)
- Tests: MCP wiring, deny-glob enforcement, per-tool enable/disable

Node runtime: if we adopt the official TS MCP servers, the voice-agent
Dockerfile adds a Node stage (`node:20-slim` or similar). Decision
deferred to the open-items section.

Validation:
- "Hey Jarvis, list my projects" → filesystem tool lists `~/gigachad`
- "Search for X" → Brave
- "List my open issues on repo Y" → GitHub MCP

### Phase 5 — Memory (sqlite two-tier)

Deliverables:
- Sqlite schema in named volume `augint-shell-voice-agent-data`:
  - `sessions` (id, started_at, ended_at)
  - `turns` (session_id, role, content, ts, tokens, model)
  - `tool_calls` (turn_id, tool, args_json, result_summary, ts)
  - `facts` (key, value, created_at, last_used_at)
- Retrieval on each new turn:
  - Last N turns in current session (raw)
  - Running summary if session exceeds `summarize_after_turns`
  - Top-K fact recall via simple match (no embeddings yet)
- Built-in tool `remember_this(key, value)` for deliberate fact writes
- CLI: `ai-shell llm voice-agent memory-dump` for inspection
- Tests: schema migrations, compaction trigger, fact recall

### Phase 6 — Provider swap + remote models

Deliverables:
- Provider adapters:
  - `OllamaProvider` (already)
  - `AnthropicProvider` — reads
    `~/.config/ai-shell/providers/anthropic.key`; falls back to `~/.claude`
    session via Agent SDK when present
  - `OpenAIProvider` — reads `~/.config/ai-shell/providers/openai.key`
- Runtime swap: `voice_agent.providers.default`; plus voice command
  "Hey Jarvis, switch to Claude" (built-in `set_provider(name)` tool)
- `profiles.resident` vs `profiles.swap` wired with explanatory comments in
  the generated default config
- Pipecat's `llm` stage becomes a thin facade delegating to the active
  adapter; all adapters present OpenAI-style messages + tool-calls internally
- Tests: adapter contract, per-provider tool-call translation, missing-key
  fails loudly

## Testing

All tests are unit tests in `tests/unit/`. Docker SDK is mocked (see existing
`mock_docker_client`, `mock_container_manager`). Patterns:
- `test_container_whisper.py`: mirror `test_container_kokoro.py`
- `test_cli_llm_whisper.py`: mirror stack-flag tests in `test_cli_llm.py`
- Voice-agent Pipecat pipeline: unit-test pipeline construction with mocked
  STT/LLM/TTS; don't stand up real audio in CI
- PWA: no harness in this repo today; manual validation per phase

Coverage floor is 80% (`--cov-fail-under=80`). Every phase must leave
coverage at or above floor.

## Out of scope (for now)

- Custom "GigaChad" wake-word training (pretrained "hey_jarvis" ships;
  training notebook link documented, user runs later)
- Tailscale / off-LAN remote access (user can add NPM external DNS later)
- Multi-user, SSO / OAuth (single user is explicit requirement)
- Mobile native app (PWA suffices)
- TURN/STUN / WebRTC (WebSocket transport chosen explicitly)
- RAG / knowledge base service (separate conversation — Qdrant + LlamaIndex
  if needed later)
- OpenHands / full coding-agent runtime (voice-agent is stateless
  request/response per turn)

## Open items to confirm during implementation

- `voice_agent.domain` default: probably leave empty. User sets it when they
  point an NPM proxy host at it.
- **Pipecat 1.0.0 upgrade**: we pin `==0.0.99` for Phases 2-5. Schedule a
  dedicated ticket after Phase 5 to migrate once the 1.0.x series has a
  few patch releases and third-party examples catch up.
- **openWakeWord model file**: ships `hey_jarvis_v0.1.onnx` via the
  `openwakeword` PyPI package's auto-download. We inherit that path; no
  need to vendor the `.onnx` in-repo. Verify model cache location in the
  container (set `HOME` / use a named volume if persistence across
  container recreations matters — small file, but saves a re-download).
- **Speaches model preload vs lazy**: `PRELOAD_MODELS` loads at container
  start. Distil-large-v3 is ~1.5 GB VRAM. Alternative: leave it empty and
  let the first request trigger a lazy load (delays first transcript by
  ~5-10 s). Default to preload for consistent latency.
- **GitHub MCP server choice**: official TS `@modelcontextprotocol/server-github`
  vs. Python wrapper around the `gh` CLI. TS means adding Node to the
  voice-agent image (~50 MB); worth the weight if the official server is
  materially better.
- **Voice-agent image publish target**: build in-repo (Dockerfile
  committed, built on first `ensure_*` call) or publish to ghcr? In-repo
  is simpler for experimental; publish when the interface stabilizes.
- **Browser wake-word revisit trigger**: if total server CPU from the
  always-on `openwakeword` process exceeds 20% of one core sustained, or
  if we add a second concurrent user, revisit `dnavarrom/openwakeword_wasm`
  for client-side detection.
