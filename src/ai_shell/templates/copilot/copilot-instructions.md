# GitHub Copilot Instructions

This file provides project-level custom instructions for GitHub Copilot.

## Project Context

Refer to `INSTITUTIONAL_KNOWLEDGE.md` at the project root for the full project
conventions, architecture, and development workflow.

## Conventions

- Follow existing code style and patterns already present in the codebase.
- Write tests for all new functionality using the project's existing test framework.
- Use conventional commit messages: `fix:`, `feat:`, `chore:`, `docs:`, etc.
- Do not manually edit version numbers or lock files.

## Workflow

- Branch naming: `{type}/issue-N-description`
- PRs target the default development branch.
- Run linting and tests before submitting: follow instructions in `INSTITUTIONAL_KNOWLEDGE.md`.
