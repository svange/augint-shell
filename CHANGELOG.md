# CHANGELOG

<!-- version list -->

## v0.75.0 (2026-04-15)

### Features

- Add chat interface output to WebUI status in llm.py
  ([`d7d98c9`](https://github.com/svange/augint-shell/commit/d7d98c99c89d2e6f4a2fa40b1531fac681118e0b))


## v0.74.0 (2026-04-15)

### Features

- Add --skip-updates option to CLI for skipping tool freshness checks
  ([`c8ff02f`](https://github.com/svange/augint-shell/commit/c8ff02fcf02c2051a91ee6e3dedd2e08d15aeaad))


## v0.73.0 (2026-04-15)

### Features

- Implement auto-update mechanism for tools in Docker containers
  ([`b9289c1`](https://github.com/svange/augint-shell/commit/b9289c1ba44b41cff94a94df126c74bf7df2d52a))


## v0.72.0 (2026-04-15)

### Bug Fixes

- Add type hint for probe_fn parameter in _wait_until_ready function
  ([`30a15a8`](https://github.com/svange/augint-shell/commit/30a15a83d1058aabf85bf7d650aee10b446750ab))

- Replace urlopen with HTTPConnection for probing Chrome debug port
  ([`5be52c0`](https://github.com/svange/augint-shell/commit/5be52c0c00a50e5d600f2c3e1bff788b529ec919))

### Features

- Enhance local Chrome integration with project-specific profiles and debug ports
  ([`f5de8e4`](https://github.com/svange/augint-shell/commit/f5de8e43adacb77de916bc1b06dca926691282c9))

- Update tmux status-right and add quick-start instructions
  ([`42625ff`](https://github.com/svange/augint-shell/commit/42625ff37e3abd79fe23aae258c7e4536a82809b))


## v0.71.2 (2026-04-14)

### Bug Fixes

- Prefer SSO keyring token over PAT in container entrypoint
  ([`f162690`](https://github.com/svange/augint-shell/commit/f1626907771baaf0e42d58201b6e66b3114ca214))


## v0.71.1 (2026-04-14)

### Refactoring

- Strip scaffolding from tool commands, rename shell to bash, extend global config path
  ([`c53f144`](https://github.com/svange/augint-shell/commit/c53f144f41799edc7b52c913916b65146ee21605))


## v0.71.0 (2026-04-14)

### Features

- Add interactive multi-pane wizard for claude --multi -i
  ([`3236d49`](https://github.com/svange/augint-shell/commit/3236d49a115a7c197ca54a9b6b21cfce13120094))


## v0.70.0 (2026-04-14)

### Features

- Add local Chrome integration for Windows with setup instructions
  ([`7735386`](https://github.com/svange/augint-shell/commit/77353860a0a099bc5512c5d74534e06fc6ecd439))

- Implement local Chrome bridge for Windows with MCP configuration
  ([`4431f57`](https://github.com/svange/augint-shell/commit/4431f57a61436ad32ed298252b33b410d438f042))


## v0.69.0 (2026-04-14)

### Features

- Support --multi for single repos via git worktrees
  ([`8b69210`](https://github.com/svange/augint-shell/commit/8b692103f8f7fd4ad1b162815d8c0dcf2b75cdfb))


## v0.68.0 (2026-04-14)

### Features

- Add RTX 5070 Ti model guide and example configurations
  ([`6e3e02c`](https://github.com/svange/augint-shell/commit/6e3e02cd7818448f2f2c1738ab30aeff9d64f37d))


## v0.67.1 (2026-04-14)

### Refactoring

- Remove institutional knowledge file and related code
  ([`3fa1f98`](https://github.com/svange/augint-shell/commit/3fa1f984ed0c639b0f579686d189da767d5e6783))


## v0.67.0 (2026-04-14)

### Features

- Add support for new LLMs on RTX 4090 (Qwen3.5, Qwen2.5-Coder, Llama 3.1, Dolphin3)
  ([`afd2183`](https://github.com/svange/augint-shell/commit/afd2183b8bab542364308fc7be7ce8b5e81b4790))


## v0.66.0 (2026-04-14)

### Features

- Use named volume for gh config when no host path found
  ([`c4d6382`](https://github.com/svange/augint-shell/commit/c4d6382c3bd995c97c97d9435acd41951aeb277a))


## v0.65.0 (2026-04-14)


## v0.64.1 (2026-04-14)

### Bug Fixes

- Detect Windows gh CLI config path for WSL2 users
  ([`86543d1`](https://github.com/svange/augint-shell/commit/86543d1540de56dfc542db9e001ede52273c15d8))


## v0.64.0 (2026-04-13)

### Features

- Add GitHub token handling from hosts.yml and update mount paths
  ([`e0a727b`](https://github.com/svange/augint-shell/commit/e0a727be0c7e83231e219f85ecb2994438ce765e))

- Add GitHub token handling from hosts.yml and update mount paths
  ([`fd78c40`](https://github.com/svange/augint-shell/commit/fd78c40e9a9e88719eddc730463ce310669dbe2d))


## v0.63.0 (2026-04-13)

### Features

- Remove standardize engine and templates
  ([`d319bc6`](https://github.com/svange/augint-shell/commit/d319bc607a4af45d243d93a9c835f42692ef139f))


## v0.62.0 (2026-04-13)

### Features

- Migrate configuration from TOML to YAML format and remove deprecated sections
  ([`b5c31f9`](https://github.com/svange/augint-shell/commit/b5c31f928b6b57e61624fa6c51e74ab68aef3902))


## v0.61.0 (2026-04-13)

### Features

- Implement per-repo UV_PROJECT_ENVIRONMENT path handling and update git settings in entrypoint
  ([`5a54a8e`](https://github.com/svange/augint-shell/commit/5a54a8ea4e2fda15f1dbab54a33096546b9bd1e6))


## v0.60.0 (2026-04-13)

### Features

- Update workspace context handling in Claude command execution
  ([`97bbaee`](https://github.com/svange/augint-shell/commit/97bbaeea167b31ba1057bb3d887734fb42613820))


## v0.59.0 (2026-04-13)

### Features

- Add npm cache volume and dependency installation for Node.js projects
  ([`b15668c`](https://github.com/svange/augint-shell/commit/b15668ccd36031200c1acd9bc35cac6e366e1f0f))


## v0.58.0 (2026-04-13)

### Features

- Update tmux pane border colors to amber for active and dusty mauve for inactive
  ([`3b5f182`](https://github.com/svange/augint-shell/commit/3b5f182ef6f5228e07aa485ad62dcccbbe9fb76c))


## v0.57.0 (2026-04-13)

### Features

- Update tmux pane border colors to use dim cyan for inactive state
  ([`f3a22db`](https://github.com/svange/augint-shell/commit/f3a22db489bd78a13e2a0f3e3e9d105996129f92))


## v0.56.0 (2026-04-13)

### Features

- Enhance tmux layout handling for 3 panes with main pane height adjustment
  ([`c50b06b`](https://github.com/svange/augint-shell/commit/c50b06bac7bf1cf21a85b05b9cb6b2a9fbe49505))


## v0.55.0 (2026-04-13)

### Features

- Add session management for tmux with reconnect prompt and command enhancements
  ([`e87f6fd`](https://github.com/svange/augint-shell/commit/e87f6fdcb3ae23242ef31479753ed5072dfcebd9))


## v0.54.0 (2026-04-13)

### Features

- Enhance tmux configuration with improved pane borders and terminal options
  ([`d541aa9`](https://github.com/svange/augint-shell/commit/d541aa90e1772870e0ba1756ac0ad21c16564278))


## v0.53.0 (2026-04-13)

### Features

- Add standardization data files and update resource loading for improved structure
  ([`29f7710`](https://github.com/svange/augint-shell/commit/29f7710ce43270885f7fd93e28aa3b508ad91dcc))


## v0.52.1 (2026-04-13)

### Refactoring

- Improve OIDC setup messaging and formatting in _run_ai_setup_oidc function
  ([`a6792ca`](https://github.com/svange/augint-shell/commit/a6792ca4baa3e33ba72f2331a8a37beddcdfef87))


## v0.52.0 (2026-04-13)

### Features

- Add multi-repo support with interactive selection in tmux
  ([`288ee3b`](https://github.com/svange/augint-shell/commit/288ee3bffe1646b3359957d0c752a3847bc9a9fa))

### Refactoring

- Remove duplicate service option from click command line arguments
  ([`4cba41c`](https://github.com/svange/augint-shell/commit/4cba41c8fb3d145b32dbcce06ed31023f8656df4))


## v0.51.0 (2026-04-13)

### Features

- Update templates and configs for standards polish
  ([`1f7b1e6`](https://github.com/svange/augint-shell/commit/1f7b1e6786f3c9561bf935014d4881974b307013))

### Refactoring

- Enhance commit scheme and pre-commit configuration for improved standards
  ([`1117b89`](https://github.com/svange/augint-shell/commit/1117b8959af3343ccdc585aa756e56b7542f9af3))

- Implement resolve_dev_container method for improved container name resolution
  ([`cb08fae`](https://github.com/svange/augint-shell/commit/cb08fae754a35d220c11d4968f53d4968c8265b1))

- Rename IaC repo type to service across entire codebase
  ([`da0254e`](https://github.com/svange/augint-shell/commit/da0254e6c35a4d8eca4da7cca62bda4d74378abb))


## v0.50.0 (2026-04-12)

### Features

- Update CLAUDE.md and SKILL.md with new guidelines for CI control keywords and AWS credential
  patterns
  ([`c770155`](https://github.com/svange/augint-shell/commit/c770155c03c1840a5a3075927cbeb6a9e707383d))


## v0.49.0 (2026-04-11)

### Features

- Enhance legacy gate detection for publisher jobs and update tests
  ([`fe8364c`](https://github.com/svange/augint-shell/commit/fe8364c3e66aa5cd000e0de0a2e4bab63a1fb96c))


## v0.48.0 (2026-04-11)

### Features

- Add husky pre-commit hook and standardization configuration files
  ([`d1eadda`](https://github.com/svange/augint-shell/commit/d1eadda134bfbe33754d26769777ffdbc23376df))


## v0.47.0 (2026-04-11)

### Features

- Implement dotfiles standardization with idempotent writes for .editorconfig and .gitignore
  ([`4d6d1a6`](https://github.com/svange/augint-shell/commit/4d6d1a6c50ca970458de6a4ebc733562c45a17cc))


## v0.46.0 (2026-04-11)

### Features

- Enhance standardization process with dry-run and JSON output options
  ([`4062b79`](https://github.com/svange/augint-shell/commit/4062b796483c93e0bc275523c70485b1c9c42f74))


## v0.45.0 (2026-04-11)

### Features

- Enhance standardization documentation and add workspace-level orchestration skill
  ([`d069a6e`](https://github.com/svange/augint-shell/commit/d069a6e6340f101f2cc41fb23f280080282fdb93))


## v0.44.0 (2026-04-11)

### Features

- **standardize**: Revert reusable workflows; AI-mediated pipeline merge
  ([`e04128a`](https://github.com/svange/augint-shell/commit/e04128acd458d684ba03a12ab58cacbb511ad740))


## v0.43.0 (2026-04-11)

### Features

- Add CI/CD pipeline configuration and enhance standardization process
  ([`3958d2c`](https://github.com/svange/augint-shell/commit/3958d2c58130b43a72cbd90cc77c9454059a6148))


## v0.42.0 (2026-04-11)

### Features

- Update templates to remove ADAPT comments and add gitleaks to pre-commit config
  ([`1eb3482`](https://github.com/svange/augint-shell/commit/1eb3482d50f57b35689ffbbd06a4c8f37ea1f5e0))


## v0.41.0 (2026-04-11)

### Features

- Initialize woxom-ecosystem with standard templates and configurations
  ([`cc21259`](https://github.com/svange/augint-shell/commit/cc2125990a8dfe5caa3cd55834d2d8576558bad6))


## v0.40.0 (2026-04-09)

### Features

- **cli**: Add -h as alias for --help across all commands
  ([`40be7b5`](https://github.com/svange/augint-shell/commit/40be7b5f6311396156cd60a8320461edfec2a8da))


## v0.39.0 (2026-04-09)

### Bug Fixes

- Add git worktree prune to docker-entrypoint.sh
  ([#43](https://github.com/svange/augint-shell/pull/43),
  [`da30da5`](https://github.com/svange/augint-shell/commit/da30da5aeaa114b87f6bc027eba19fa073778f8b))

- Restore test_codex_command and apply ruff format fixes
  ([#43](https://github.com/svange/augint-shell/pull/43),
  [`da30da5`](https://github.com/svange/augint-shell/commit/da30da5aeaa114b87f6bc027eba19fa073778f8b))

- Restore test_codex_command definition and apply ruff format fixes
  ([#43](https://github.com/svange/augint-shell/pull/43),
  [`da30da5`](https://github.com/svange/augint-shell/commit/da30da5aeaa114b87f6bc027eba19fa073778f8b))

### Features

- Add --worktree/-w flag to ai-shell claude and git worktree prune to docker entrypoint
  ([#43](https://github.com/svange/augint-shell/pull/43),
  [`da30da5`](https://github.com/svange/augint-shell/commit/da30da5aeaa114b87f6bc027eba19fa073778f8b))

- Add --worktree/-w flag to ai-shell claude for isolated git worktree sessions
  ([#43](https://github.com/svange/augint-shell/pull/43),
  [`da30da5`](https://github.com/svange/augint-shell/commit/da30da5aeaa114b87f6bc027eba19fa073778f8b))


## v0.38.1 (2026-04-09)

### Chores

- Remove remote session support and delete obsolete tests
  ([`284d9d3`](https://github.com/svange/augint-shell/commit/284d9d30923c1714e316ecd89f5d5a8179801e74))

- **workspace**: Rename all `mono` commands to `workspace` in skills and docs
  ([`51d67cc`](https://github.com/svange/augint-shell/commit/51d67cc7c1e0a279dc70ce3de09c6ef1da793ce2))


## v0.38.0 (2026-04-09)

### Bug Fixes

- **claude**: Auto-infer remote session name and set GIT_TERMINAL_PROMPT with GH_TOKEN
  ([`e2cd48e`](https://github.com/svange/augint-shell/commit/e2cd48e2c7aa12c15fb8fbf530a6b4bba42dd8f7))

- **templates**: Use `uv run ai-tools` in all skill and notes templates
  ([`70f1b55`](https://github.com/svange/augint-shell/commit/70f1b55d3807a78f4fd0e68e0863dd8cde2a08bb))

### Build System

- Add augint-tools as dev dependency
  ([`eba512c`](https://github.com/svange/augint-shell/commit/eba512c04bca635b3c094cbc8bf749364d892d91))

### Features

- **claude**: Add --remote and --name flags for named remote sessions
  ([`161d85b`](https://github.com/svange/augint-shell/commit/161d85ba3ca506f834fe8321a8373b54b1b0453a))


## v0.37.1 (2026-04-08)

### Bug Fixes

- **workspace**: Update skills and docs to use ai-tools mono commands (main)
  ([`f89d81f`](https://github.com/svange/augint-shell/commit/f89d81f6ee28aadfabe0154cd2e0372fee6532e8))


## v0.37.0 (2026-04-08)

### Bug Fixes

- **workspace**: Add ai-repo-health skill documentation (main)
  ([`9c94f72`](https://github.com/svange/augint-shell/commit/9c94f72536985942da2ba861abfb0ee6e7114a0e))

- **workspace**: Update skills to use ai-tools mono commands (main)
  ([`70ffb04`](https://github.com/svange/augint-shell/commit/70ffb041e79e1112799a9a96c8882c06c9ac51f4))

### Documentation

- **workspace**: Remove deprecated legacy ai-* autonomous workflow skills (main)
  ([`b668fa6`](https://github.com/svange/augint-shell/commit/b668fa6676ddbe0b5abd30316528f744b49bbbc0))

- **workspace**: Update workspace and ai-tools usage conventions (main)
  ([`eafe6d5`](https://github.com/svange/augint-shell/commit/eafe6d5bf7111deba2b8cb99f318d27b1eed1493))

- **workspace**: Update workspace and ai-tools usage conventions (main)
  ([`71ad67f`](https://github.com/svange/augint-shell/commit/71ad67ff2092b4027623fe263ae889c1974e45f5))

### Features

- Augint-tools integrations with monorepo workflow
  ([`5f4c4bc`](https://github.com/svange/augint-shell/commit/5f4c4bca26c07e904691460a9119106f8aad1391))

- **repo**: Add Codex provider support with AWS Bedrock integration (main)
  ([`285a6d3`](https://github.com/svange/augint-shell/commit/285a6d3942e8b71022db2e7ad0096538cee1426b))

- **repo**: Update standardization and new project docs with institutional knowledge
  ([`2e91e6f`](https://github.com/svange/augint-shell/commit/2e91e6f54759fedad39d61c332271584a80e21d0))

### Refactoring

- Replace legacy workspace mono scaffolding
  ([`4be77e8`](https://github.com/svange/augint-shell/commit/4be77e892b1817a2911c0f69292f06e179a002aa))


## v0.36.0 (2026-04-07)

### Features

- **gpu**: Intelligent VRAM management and CPU priority for Ollama
  ([`80f0dcf`](https://github.com/svange/augint-shell/commit/80f0dcf1cd796a10fb56b7ef330fc159998cb741))


## v0.35.0 (2026-04-07)

### Features

- **cli**: Add URLs and config to llm status output
  ([`9d5f98c`](https://github.com/svange/augint-shell/commit/9d5f98c0f413a4f84bccb9c50b88778e3c071701))


## v0.34.0 (2026-04-07)

### Features

- **cli**: Auto-init config on first run, default to local provider
  ([`39944e1`](https://github.com/svange/augint-shell/commit/39944e10b2803d654196f4daaaa40f3f89824cf5))


## v0.33.0 (2026-04-07)

### Features

- **cli**: Add --no-preflight flag to claude and opencode commands
  ([`ef618da`](https://github.com/svange/augint-shell/commit/ef618da59df66f39cc5aec5086728ceb6e4c9728))


## v0.32.3 (2026-04-07)

### Bug Fixes

- **cli**: Use fileb:// and printf for Bedrock pre-flight body
  ([`4e10a9c`](https://github.com/svange/augint-shell/commit/4e10a9cb644823f723cb9929f3eaa9ab3839a33d))


## v0.32.2 (2026-04-07)

### Bug Fixes

- **defaults**: Use cross-region inference profile for Bedrock pre-flight
  ([`55e654f`](https://github.com/svange/augint-shell/commit/55e654f2e3e79cc8bade4e380396984e241ac133))


## v0.32.1 (2026-04-06)


## v0.32.0 (2026-04-06)


## v0.31.0 (2026-04-06)

### Features

- **cli**: Add Bedrock diagnostics and user feedback
  ([`bd8d368`](https://github.com/svange/augint-shell/commit/bd8d368bbff4ae742919573a6f77f2e546a23299))


## v0.30.0 (2026-04-06)


## v0.29.0 (2026-04-05)

### Features

- Add first-class Amazon Bedrock support for Claude Code and opencode
  ([`4d91813`](https://github.com/svange/augint-shell/commit/4d91813631c8dcb12f2fd34ce09f37061ec77c05))


## v0.28.0 (2026-04-05)

### Features

- **scaffold**: Add ai-fix-repo-standards skill for GitHub repo remediation
  ([`dab03f8`](https://github.com/svange/augint-shell/commit/dab03f8b9f7891f5534469f9ee4a5694143c8352))


## v0.27.0 (2026-04-05)

### Features

- **scaffold**: Filter Renovate dependency dashboard from issue picker
  ([`dc2776b`](https://github.com/svange/augint-shell/commit/dc2776b3148c8e14e6404b721eedcde51be2facf))


## v0.26.1 (2026-04-05)

### Bug Fixes

- **docker**: Set core.filemode false in container git config
  ([`16d7efa`](https://github.com/svange/augint-shell/commit/16d7efaf1cd66bbd1040350b77536b3471677f72))


## v0.26.0 (2026-04-05)

### Bug Fixes

- Add lingering files
  ([`92385a7`](https://github.com/svange/augint-shell/commit/92385a79ae446d3ba7537256984950080869bca7))

### Features

- **scaffold**: Rewrite ai-mono-* skills to consume CLI --json output
  ([#22](https://github.com/svange/augint-shell/pull/22),
  [`fce3a9b`](https://github.com/svange/augint-shell/commit/fce3a9b25a23733acc627c823392b97ab7f9edbd))


## v0.25.0 (2026-04-05)

### Bug Fixes

- **scaffold**: Remove local rebase deny rules from settings template
  ([`59c9f70`](https://github.com/svange/augint-shell/commit/59c9f70265a775a3aa637a8ee827679be4cd5f6f))

### Features

- **scaffold**: Bootstrap CLAUDE.md on update and detect stale branches
  ([`1ae230b`](https://github.com/svange/augint-shell/commit/1ae230bb5599dcdf0a41ecbdcd5bdb97e963ef9d))

- **scaffold**: Switch from squash to merge commits across all templates
  ([`ce7962f`](https://github.com/svange/augint-shell/commit/ce7962f463c086ff23677fa5c3b025dccdf0c970))


## v0.24.0 (2026-04-05)

### Features

- **scaffold**: Add repo-type flags and monorepo skill support
  ([#20](https://github.com/svange/augint-shell/pull/20),
  [`dced272`](https://github.com/svange/augint-shell/commit/dced2729f2ceceb5a39ff56595b53fa780c0afb6))


## v0.23.0 (2026-04-04)

### Features

- **scaffold**: Add --reset flag, make --update safe with JSON merge
  ([`6f94151`](https://github.com/svange/augint-shell/commit/6f94151fbe596c863cc60c78b36c69c21f62ea3c))


## v0.22.5 (2026-04-04)

### Bug Fixes

- Pre-commit errors
  ([`b98be52`](https://github.com/svange/augint-shell/commit/b98be52182d2966db4c4303904ef14501031a24c))

- **templates**: Close lock file handling gaps across scaffolded repos
  ([`5161c82`](https://github.com/svange/augint-shell/commit/5161c82ffbc38cd57731ba24ef494233f218f2f5))


## v0.22.4 (2026-04-04)

### Bug Fixes

- Narrow .env deny rules to allow reading .env.example
  ([`8ca3d93`](https://github.com/svange/augint-shell/commit/8ca3d939bbc6f0270cceddd785c5f544b80ae24e))

- Standards
  ([`bb12a50`](https://github.com/svange/augint-shell/commit/bb12a5085ebed14633ab0d4a76f47bf6f6d044fd))


## v0.22.3 (2026-04-04)

### Bug Fixes

- Refine prompt logic and remove unused code
  ([`869592d`](https://github.com/svange/augint-shell/commit/869592d2dd99c416adfea65f5ee9d268e6e370d5))

### Refactoring

- Reorganize Docker imports in `container.py`
  ([`1c933d2`](https://github.com/svange/augint-shell/commit/1c933d23a2866cf04852d7ddf384f5250b7c18f7))


## v0.22.2 (2026-04-04)

### Chores

- Update `INSTITUTIONAL_KNOWLEDGE.md` and standardization skills for enhanced clarity and validation
  ([`6068109`](https://github.com/svange/augint-shell/commit/60681097355bedbb8e681222a80a77d0d29b465c))


## v0.22.1 (2026-04-04)

### Bug Fixes

- Remove `INSTITUTIONAL_KNOWLEDGE.md` and enhance repository standardization scripts
  ([`43c9701`](https://github.com/svange/augint-shell/commit/43c97010fb86cbc8e0a6517f0cfa1509a5f1e965))


## v0.22.0 (2026-04-04)

### Features

- Add AI-assisted standardization skills for repository consistency
  ([#16](https://github.com/svange/augint-shell/pull/16),
  [`1059aa7`](https://github.com/svange/augint-shell/commit/1059aa72f3475aa81d17c28a0371ac5787da2b4f))

- **skills**: Automate workflow transitions and reduce approval gates
  ([#16](https://github.com/svange/augint-shell/pull/16),
  [`1059aa7`](https://github.com/svange/augint-shell/commit/1059aa72f3475aa81d17c28a0371ac5787da2b4f))


## v0.21.0 (2026-04-04)

### Features

- Add --no-merge flag, background merge, and workflow enforcement in skills
  ([#15](https://github.com/svange/augint-shell/pull/15),
  [`e5d3641`](https://github.com/svange/augint-shell/commit/e5d36412a6369aaf63fa5d3fd62091c258c62321))

- Add ai-setup-oidc skill for AWS OIDC trust policy management
  ([#15](https://github.com/svange/augint-shell/pull/15),
  [`e5d3641`](https://github.com/svange/augint-shell/commit/e5d36412a6369aaf63fa5d3fd62091c258c62321))

- **skills**: Automate workflow transitions and reduce approval gates
  ([#15](https://github.com/svange/augint-shell/pull/15),
  [`e5d3641`](https://github.com/svange/augint-shell/commit/e5d36412a6369aaf63fa5d3fd62091c258c62321))


## v0.20.0 (2026-04-04)

### Features

- Add --no-merge flag, background merge, and workflow enforcement in skills
  ([#14](https://github.com/svange/augint-shell/pull/14),
  [`cee0b0f`](https://github.com/svange/augint-shell/commit/cee0b0f06bcc32ed17b311d67f31d820b49cce43))

- Add ai-setup-oidc skill for AWS OIDC trust policy management
  ([#14](https://github.com/svange/augint-shell/pull/14),
  [`cee0b0f`](https://github.com/svange/augint-shell/commit/cee0b0f06bcc32ed17b311d67f31d820b49cce43))


## v0.19.0 (2026-04-04)

### Features

- Add ai-setup-oidc skill for AWS OIDC trust policy management
  ([#13](https://github.com/svange/augint-shell/pull/13),
  [`2806432`](https://github.com/svange/augint-shell/commit/280643219f6815616bdf13330b140b2f3c666891))


## v0.18.0 (2026-04-04)

### Bug Fixes

- **cli**: Auto-stop running container in manage clean
  ([#11](https://github.com/svange/augint-shell/pull/11),
  [`aa06556`](https://github.com/svange/augint-shell/commit/aa065567112d7ae34312eec862d05bbbd7a59cf1))

### Features

- Add AI-assisted standardization skills for repository consistency
  ([#11](https://github.com/svange/augint-shell/pull/11),
  [`aa06556`](https://github.com/svange/augint-shell/commit/aa065567112d7ae34312eec862d05bbbd7a59cf1))


## v0.17.0 (2026-04-04)

### Chores

- Simplify console print statement for missing binary warning
  ([`d3c0eae`](https://github.com/svange/augint-shell/commit/d3c0eaea82cf0e40dc43dd4f723c2be077495aea))

### Features

- Add `merge_notes_into_context` function for intelligent merging of `INSTITUTIONAL_KNOWLEDGE.md`
  ([`55ee3e6`](https://github.com/svange/augint-shell/commit/55ee3e6d6ffe238284124155712e4f9f06dc71de))


## v0.16.11 (2026-04-04)

### Chores

- Update permissions and environment defaults for npm and Husky
  ([`ae871b1`](https://github.com/svange/augint-shell/commit/ae871b16d99602fe63425c6caba1e0a7430f00d4))


## v0.16.10 (2026-04-03)

### Chores

- Add standardized templates for configs, workflows, and dotfiles
  ([`299442c`](https://github.com/svange/augint-shell/commit/299442c64c43a22abaf3bde2e86a3e4605557a78))


## v0.16.9 (2026-04-03)

### Bug Fixes

- Bump `augint-github` to version 1.3.3 in `uv.lock`
  ([`ca58e0a`](https://github.com/svange/augint-shell/commit/ca58e0a49d02988b81d76cee2c83334d407c85b9))

- Pass dynamically generated environment variables to CLI commands for consistency
  ([`87af2ab`](https://github.com/svange/augint-shell/commit/87af2ab25049a47efec09a0aedc821e089dde139))

### Chores

- Bump `augint-github` to version 1.3.2 in `uv.lock`
  ([`7427358`](https://github.com/svange/augint-shell/commit/742735867a69f912f9249f17db05f372b9238150))


## v0.16.8 (2026-04-03)

### Bug Fixes

- **docker**: Update dependency sync condition to check for `uv.lock` instead of `pyproject.toml`
  ([`00863dc`](https://github.com/svange/augint-shell/commit/00863dc3496b34b19ccb3e1613a630994f0757aa))


## v0.16.7 (2026-04-03)

### Chores

- Update Renovate config to use `ci` prefix for dependency updates
  ([`d09df67`](https://github.com/svange/augint-shell/commit/d09df67f26d743ae65a6e5f062f1b8a9ff9cb1ad))


## v0.16.6 (2026-04-03)

### Chores

- **deps**: Update dependency uv_build to >=0.11,<0.12
  ([#5](https://github.com/svange/augint-shell/pull/5),
  [`12ad81d`](https://github.com/svange/augint-shell/commit/12ad81d866b479db8101aa8004af52c277c7adcb))


## v0.16.5 (2026-04-03)

### Chores

- **deps**: Pin dependencies ([#4](https://github.com/svange/augint-shell/pull/4),
  [`23f39b9`](https://github.com/svange/augint-shell/commit/23f39b9d555d42b39e69438a7413f5deeccbbb7c))


## v0.16.4 (2026-04-03)

### Chores

- Adjust renovate config for refined dependency grouping and GitHub Actions update policies
  ([`815907c`](https://github.com/svange/augint-shell/commit/815907c71e492dc5b1769cd23487d8979b6bca1b))


## v0.16.3 (2026-04-03)

### Chores

- Update semantic release config to adjust commit parser options and simplify changelog exclusions
  ([`28fc84b`](https://github.com/svange/augint-shell/commit/28fc84b673f0bb1dd8b228b58e6717d355772580))


## v0.16.2 (2026-04-03)

### Bug Fixes

- Consolidate agent templates into `INSTITUTIONAL_KNOWLEDGE.md` and update scaffolding logic
  ([`be914d4`](https://github.com/svange/augint-shell/commit/be914d4d8c23244bb2a63a070b8f185e5a33e0b6))


## v0.16.1 (2026-04-03)

### Bug Fixes

- Update project title in README to reflect CLI focus
  ([`401ef13`](https://github.com/svange/augint-shell/commit/401ef13e19a8532e7def6890fcf069439bed30bb))


## v0.16.0 (2026-04-03)

### Features

- Enhance Codex tools with new skills and configs
  ([`071547a`](https://github.com/svange/augint-shell/commit/071547a4d8531b60f5dba86fcaed0a9693d21a3d))


## v0.15.0 (2026-04-03)

### Bug Fixes

- Resolve Codex skills/list TUI crash and validate tool configs
  ([#2](https://github.com/svange/augint-shell/pull/2),
  [`5d068db`](https://github.com/svange/augint-shell/commit/5d068db3a5974f4c3a597c78ce3ab272d693ab8d))

### Features

- Bring agent configs to parity with Claude and fix broken skills
  ([#2](https://github.com/svange/augint-shell/pull/2),
  [`5d068db`](https://github.com/svange/augint-shell/commit/5d068db3a5974f4c3a597c78ce3ab272d693ab8d))


## v0.14.0 (2026-04-03)

### Features

- Bring agent configs to parity with Claude and fix broken skills
  ([#1](https://github.com/svange/augint-shell/pull/1),
  [`e32077f`](https://github.com/svange/augint-shell/commit/e32077f076b53f6614fde3bd85261940025f1f7d))


## v0.13.0 (2026-04-03)

### Features

- Add `--clean` option to CLI scaffold commands for resetting configurations and templates
  ([`a4489e7`](https://github.com/svange/augint-shell/commit/a4489e7f15243e63c2f291314a776cb66d186c3c))


## v0.12.0 (2026-04-03)

### Features

- Add `ai-web-dev` skill, browser automation tools, and improve Git/CLI configurations in Docker
  setup
  ([`cff028f`](https://github.com/svange/augint-shell/commit/cff028ff5d60ab51a3aff4fa6a09525179fae371))


## v0.11.0 (2026-04-03)

### Features

- Add low memory warning for large model support and corresponding unit tests
  ([`66f38bd`](https://github.com/svange/augint-shell/commit/66f38bd3bcdd18ea7558657d6881962fd9fd1af6))


## v0.10.0 (2026-04-03)

### Features

- Add scaffolding for aider, codex, and opencode configurations; refactor tests and CLI commands to
  support new init/update options
  ([`6eb0077`](https://github.com/svange/augint-shell/commit/6eb00772856c954dec9ddf5b195ca1fa5b81a708))


## v0.9.0 (2026-04-03)

### Features

- Add new skill templates and configurations for Claude and codex integration
  ([`b6453f4`](https://github.com/svange/augint-shell/commit/b6453f490c20c659730cc68b5dc73587da859e8a))


## v0.8.0 (2026-04-02)

### Features

- Add Amazon Bedrock provider support, update AWS environment handling, and refactor related tests
  ([`5ddd9c2`](https://github.com/svange/augint-shell/commit/5ddd9c20670ccdd9055fde0062c04356fdc5d271))


## v0.7.0 (2026-04-02)


## v0.6.0 (2026-04-02)

### Features

- Add `init` command for project scaffolding, improve Claude configuration, and integrate templates
  with scaffold logic
  ([`863c61c`](https://github.com/svange/augint-shell/commit/863c61cb06688cd622cfe3fe6520df01ddd441a3))

- Replace `commands` with `skills`, migrate templates to skill-based structure, and add
  `ai-create-cmd` and `ai-monitor-pipeline` skills
  ([`2504ea1`](https://github.com/svange/augint-shell/commit/2504ea1c70b3b09eb09cde434b67958dab272d22))


## v0.5.0 (2026-04-02)

### Bug Fixes

- Changelog
  ([`efc15f5`](https://github.com/svange/augint-shell/commit/efc15f53af3ed336512a6d2c7d9f84f03ec846d4))

### Features

- Add support for dynamic dev container port configuration and enhance port mapping tests
  ([`32639da`](https://github.com/svange/augint-shell/commit/32639dae61b32c38e609534e9df1a1f39cc281d7))

- Integrate python-dotenv, enhance environment loading with .env support, and add unit tests
  ([`1ab02a0`](https://github.com/svange/augint-shell/commit/1ab02a0b75d92b24a48e536a49ca1f41cc839c39))
