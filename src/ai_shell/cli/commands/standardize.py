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
from ai_shell.standardize.detection import Language, RepoType
from ai_shell.standardize.detection import detect as _detect
from ai_shell.standardize.lint import scan
from ai_shell.standardize.pipeline import canonical_jobs, validate
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


@standardize_group.group("pipeline", invoke_without_command=True)
@click.option(
    "--validate",
    "action",
    flag_value="validate",
    help="Read-only drift report against the canonical pipeline contract.",
)
@click.option(
    "--print-template",
    "print_template",
    default=None,
    metavar="GATE",
    help="Dump the canonical inline job snippet for one gate to stdout.",
)
@click.option(
    "--print-spec",
    "print_spec",
    default=None,
    metavar="GATE",
    help="Dump the minimum spec for one gate to stdout.",
)
@click.option(
    "--language",
    "language_override",
    type=click.Choice(["python", "node"]),
    default=None,
    help="Override detected language (used with --print-template / --print-spec).",
)
@click.option(
    "--type",
    "type_override",
    type=click.Choice(["library", "iac"]),
    default=None,
    help="Override detected repo type (used with --print-template / --print-spec).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON (only with --validate).",
)
@click.argument(
    "path",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd(),
    required=False,
)
@click.pass_context
def standardize_pipeline(
    ctx: click.Context,
    action: str | None,
    print_template: str | None,
    print_spec: str | None,
    language_override: str | None,
    type_override: str | None,
    as_json: bool,
    path: Path,
) -> None:
    """Read-only pipeline drift validator + canonical job reference store.

    Pipeline standardization is AI-mediated: this command does NOT write
    `pipeline.yaml`. Run `--validate` to get a structured drift report,
    or `--print-template <Gate>` / `--print-spec <Gate>` to dump the
    canonical inline job snippet / minimum spec the AI uses as reference
    when merging the file.
    """
    if ctx.invoked_subcommand is not None:
        return

    # --print-template / --print-spec take precedence over --validate.
    if print_template or print_spec:
        gate = print_template or print_spec
        assert gate is not None
        language, repo_type = _resolve_language_type(path, language_override, type_override)
        refs = canonical_jobs(language, repo_type)
        if gate not in refs:
            console.print(
                f"[red]unknown gate '{gate}'[/red] for "
                f"{language.value}/{repo_type.value}; "
                f"valid: {', '.join(refs.keys())}"
            )
            raise click.exceptions.Exit(code=2)
        ref = refs[gate]
        if print_template:
            click.echo(ref.template_text(), nl=False)
        else:
            click.echo(
                _job_spec_text(language, repo_type, gate),
                nl=False,
            )
        return

    # Default: --validate (also the only behavior the command supports).
    report = validate(path)
    if as_json:
        click.echo(_json.dumps(report.to_dict(), indent=2))
        if not report.is_clean():
            raise click.exceptions.Exit(code=1)
        return

    if not report.pipeline_present:
        console.print(f"[red]pipeline.yaml missing at {report.pipeline_path}[/red]")
        raise click.exceptions.Exit(code=1)

    if report.present:
        console.print(f"[green]canonical present:[/green] {', '.join(report.present)}")
    if report.missing:
        console.print(f"[yellow]canonical missing:[/yellow] {', '.join(report.missing)}")
    if report.legacy_candidates:
        console.print("[yellow]legacy candidates:[/yellow]")
        for job_id, current, guess in report.legacy_candidates:
            console.print(f"  {job_id}: '{current}' -> {guess}")
    if report.spec_failures:
        console.print("[yellow]spec failures:[/yellow]")
        for gate, reason in report.spec_failures:
            console.print(f"  {gate}: {reason}")
    if report.custom_jobs:
        console.print(f"[blue]custom jobs (preserve):[/blue] {', '.join(report.custom_jobs)}")

    if report.is_clean():
        console.print("[green]pipeline: clean[/green]")
        return
    raise click.exceptions.Exit(code=1)


def _resolve_language_type(
    path: Path,
    language_override: str | None,
    type_override: str | None,
) -> tuple[Language, RepoType]:
    """Pick language + repo_type for --print-* commands.

    Uses explicit overrides if given, otherwise falls back to detection
    against *path* (or cwd).
    """
    if language_override and type_override:
        return Language(language_override), RepoType(type_override)
    detection = _detect(path)
    language = Language(language_override) if language_override else detection.language
    repo_type = RepoType(type_override) if type_override else detection.repo_type
    if language in (Language.AMBIGUOUS, Language.UNKNOWN):
        console.print("[red]language is ambiguous; pass --language python|node[/red]")
        raise click.exceptions.Exit(code=2)
    return language, repo_type


def _job_spec_text(language: Language, repo_type: RepoType, gate: str) -> str:
    """Read the spec yaml file for *gate* directly from the package data."""
    from ai_shell.standardize.pipeline import _job_spec_resource

    return _job_spec_resource(language, repo_type, gate).read_text(encoding="utf-8")


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
