# CHANGELOG

<!-- version list -->

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

- Update `NOTES.md` and standardization skills for enhanced clarity and validation
  ([`6068109`](https://github.com/svange/augint-shell/commit/60681097355bedbb8e681222a80a77d0d29b465c))


## v0.22.1 (2026-04-04)

### Bug Fixes

- Remove `NOTES.md` and enhance repository standardization scripts
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

- Add `merge_notes_into_context` function for intelligent merging of `NOTES.md`
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

- Consolidate agent templates into `NOTES.md` and update scaffolding logic
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
