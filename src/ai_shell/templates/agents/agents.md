# AGENTS.md

## Project Overview

<!-- Describe your project here. This file is read automatically by Codex and opencode. -->

## Development Workflow

1. **Pick an issue**: Find or get assigned an issue to work on
2. **Create a branch**: `git checkout -b feat/issue-N-description`
3. **Develop**: Write code with tests, following project conventions
4. **Submit**: Run checks, commit with conventional messages, create PR
5. **Monitor**: Watch CI pipeline, fix any failures
6. **Merge**: PR auto-merges after checks pass

## Conventions

- **Commits**: Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- **Branches**: `{feat|fix|docs}/issue-N-description`
- **PRs**: Target the default development branch, enable automerge
- **Tests**: Write tests for all new functionality

## Key Commands

```bash
# Development
git status                    # Check working tree
gh issue list --state open    # View open issues
gh pr create                  # Create pull request
gh pr merge --auto --squash   # Enable automerge

# CI/CD
gh run list                   # List workflow runs
gh run view <id>              # View run details
gh run watch <id>             # Watch run in real-time
```
