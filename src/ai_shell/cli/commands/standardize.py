"""`ai-shell standardize` command group.

Subcommands are thin CLI wrappers around `ai_shell.standardize.*` modules.
Skill prose (`.claude/skills/ai-standardize-*/SKILL.md`) invokes these so the
logic stays testable and the skill stays short.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.standardize.detection import detect as _detect
from ai_shell.standardize.gates import load_gates
from ai_shell.standardize.lint import scan
from ai_shell.standardize.pipeline import PipelineDriftError
from ai_shell.standardize.pipeline import apply as _pipeline_apply
from ai_shell.standardize.precommit import apply as _precommit_apply
from ai_shell.standardize.release import ReleaseAlignmentError
from ai_shell.standardize.release import apply as _release_apply
from ai_shell.standardize.renovate import RenovateAlignmentError
from ai_shell.standardize.renovate import apply as _renovate_apply
from ai_shell.standardize.umbrella import StepStatus, run_all
from ai_shell.standardize.verify import VerifyStatus
from ai_shell.standardize.verify import run as _verify_run

console = Console(stderr=True)


@click.group("standardize", context_settings=CONTEXT_SETTINGS)
def standardize_group() -> None:
    """Repo standardization: generate and verify canonical quality gates."""


@standardize_group.command("lint")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
def standardize_lint(path: Path) -> None:
    """Scan *path* for stale gate-name variants and drift markers.

    Exits non-zero on any match so it can be wired into pre-commit and CI.
    """
    root = path.resolve()
    hits = scan(root)
    if not hits:
        console.print(f"[green]lint: clean[/green] ({root})")
        return

    console.print(f"[red]lint: {len(hits)} drift hit(s) found[/red]")
    for hit in hits:
        console.print(f"  {hit.format(root)}")
    raise click.exceptions.Exit(code=1)


@standardize_group.command("detect")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def standardize_detect(path: Path, as_json: bool) -> None:
    """Detect repo language and type at *path*."""
    detection = _detect(path)
    if as_json:
        click.echo(
            _json.dumps(
                {
                    "language": detection.language.value,
                    "repo_type": detection.repo_type.value,
                    "language_evidence": list(detection.language_evidence),
                    "repo_type_evidence": list(detection.repo_type_evidence),
                    "ambiguous": detection.is_ambiguous(),
                }
            )
        )
        return

    console.print(f"language:   [bold]{detection.language.value}[/bold]")
    console.print(f"repo_type:  [bold]{detection.repo_type.value}[/bold]")
    if detection.language_evidence:
        console.print(f"lang_from:  {', '.join(detection.language_evidence)}")
    if detection.repo_type_evidence:
        console.print(f"type_from:  {', '.join(detection.repo_type_evidence)}")
    if detection.is_ambiguous():
        console.print("[yellow]ambiguous -- resolve interactively[/yellow]")


@standardize_group.command("pipeline")
@click.option(
    "--write",
    "action",
    flag_value="write",
    default="write",
    help="Write the canonical pipeline.yaml (default).",
)
@click.option(
    "--verify",
    "action",
    flag_value="verify",
    help="Diff the existing pipeline.yaml against the template; non-zero on drift.",
)
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
def standardize_pipeline(action: str, path: Path) -> None:
    """Generate or verify `.github/workflows/pipeline.yaml`."""
    root = path.resolve()
    detection = _detect(root)
    if detection.is_ambiguous():
        console.print(
            "[red]cannot render pipeline: language is ambiguous[/red] "
            f"({', '.join(detection.language_evidence)})"
        )
        console.print(
            'Set `[standardize] language = "python"` (or "node") in `ai-shell.toml`, then retry.'
        )
        raise click.exceptions.Exit(code=2)

    try:
        result = _pipeline_apply(detection, root, dry_run=(action == "verify"))
    except PipelineDriftError as exc:
        console.print(f"[red]pipeline drift:[/red] {exc}")
        raise click.exceptions.Exit(code=1) from exc

    if action == "verify":
        # Diff would-be content against the on-disk file.
        expected = result.path.read_text(encoding="utf-8") if result.path.is_file() else ""
        # Re-render to compare, bypassing the dry_run (we need the content).
        from importlib import resources as _resources

        expected_rendered = (
            _resources.files("ai_shell.templates")
            .joinpath("claude", "skills", "ai-standardize-pipeline", result.template)
            .read_text(encoding="utf-8")
        )
        if expected != expected_rendered:
            console.print(f"[red]drift:[/red] {result.path} differs from template")
            raise click.exceptions.Exit(code=1)
        console.print(f"[green]verify: clean[/green] ({result.path})")
        return

    console.print(f"[green]wrote[/green] {result.path} ({result.template})")
    if result.nightly_path and result.nightly_path.is_file():
        console.print(f"[green]wrote[/green] {result.nightly_path}")
    gates = load_gates()
    console.print(f"expected gates: {', '.join(result.expected_gates)}")
    _ = gates  # keep loader warm for the CLI run (caches across subcommands)


@standardize_group.command("precommit")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
def standardize_precommit(path: Path) -> None:
    """Generate canonical pre-commit config for the detected language."""
    root = path.resolve()
    detection = _detect(root)
    if detection.is_ambiguous():
        console.print("[red]cannot render precommit: ambiguous language[/red]")
        raise click.exceptions.Exit(code=2)
    result = _precommit_apply(detection, root)
    for f in result.files:
        console.print(f"[green]wrote[/green] {f}")


@standardize_group.command("renovate")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
def standardize_renovate(path: Path) -> None:
    """Generate canonical renovate.json5 for the detected combination."""
    root = path.resolve()
    detection = _detect(root)
    if detection.is_ambiguous():
        console.print("[red]cannot render renovate: ambiguous language[/red]")
        raise click.exceptions.Exit(code=2)
    try:
        result = _renovate_apply(detection, root)
    except RenovateAlignmentError as exc:
        console.print(f"[red]renovate drift:[/red] {exc}")
        raise click.exceptions.Exit(code=1) from exc
    console.print(f"[green]wrote[/green] {result.path} ({result.template})")
    if result.substitutions_applied:
        console.print(f"applied {result.substitutions_applied} node substitutions")


@standardize_group.command("release")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
@click.option(
    "--project-name",
    default=None,
    help="Override the project name used in tag_format (required for node if no package.json name).",
)
def standardize_release(path: Path, project_name: str | None) -> None:
    """Generate canonical semantic-release config for the detected combination."""
    root = path.resolve()
    detection = _detect(root)
    if detection.is_ambiguous():
        console.print("[red]cannot render release: ambiguous language[/red]")
        raise click.exceptions.Exit(code=2)
    try:
        result = _release_apply(detection, root, project_name=project_name)
    except ReleaseAlignmentError as exc:
        console.print(f"[red]release drift:[/red] {exc}")
        raise click.exceptions.Exit(code=1) from exc
    console.print(f"[green]wrote[/green] {result.path} ({result.template})")
    console.print(f"plugins: {', '.join(result.plugins)}")


@standardize_group.command("repo")
@click.option(
    "--all",
    "mode",
    flag_value="all",
    help="Run the full 10-step standardization sequence.",
)
@click.option(
    "--verify",
    "mode",
    flag_value="verify",
    help="Read-only verify; exits non-zero on drift.",
)
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    required=False,
)
def standardize_repo(mode: str | None, path: Path) -> None:
    """Umbrella: run or verify the full repo standardization sequence."""
    root = path.resolve()

    if mode == "verify":
        findings = _verify_run(root)
        any_drift = False
        for f in findings:
            color = {
                VerifyStatus.PASS: "green",
                VerifyStatus.DRIFT: "yellow",
                VerifyStatus.FAIL: "red",
            }[f.status]
            console.print(f"[{color}][{f.status.value}][/{color}] {f.section}: {f.message}")
            if f.diff:
                console.print(f.diff)
            if not f.is_clean():
                any_drift = True
        if any_drift:
            raise click.exceptions.Exit(code=1)
        return

    if mode == "all":
        results = run_all(root)
        any_failed = False
        for r in results:
            color = {
                StepStatus.OK: "green",
                StepStatus.SKIPPED: "yellow",
                StepStatus.FAILED: "red",
            }[r.status]
            console.print(f"[{color}][{r.status.value}][/{color}] {r.step}: {r.message}")
            if r.status == StepStatus.FAILED:
                any_failed = True
        if any_failed:
            raise click.exceptions.Exit(code=1)
        return

    # Default: show detection + current verify status
    findings = _verify_run(root)
    for f in findings:
        console.print(f"[{f.status.value}] {f.section}: {f.message}")
