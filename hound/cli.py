"""Command-line interface for Hound."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from hound.agent import HoundAgent
from hound.config import generate_default_config, load_config
from hound.diffing.spec_diff import SpecDiffEngine
from hound.fetchers.openapi_fetcher import OpenAPIFetcher
from hound.reporter.sarif import SARIFExporter
from hound.store.snapshot_store import LocalSnapshotStore
from hound.wizard import AutoDiscoveryWizard

console = Console()
err_console = Console(stderr=True)


GITHUB_ACTION_TEMPLATE = """# .github/workflows/hound.yml
name: Hound API Watch
on:
  schedule:
    - cron: '0 9 * * 1'   # every Monday, 9am UTC
  workflow_dispatch: {}

jobs:
  watch:
    runs-on: ubuntu-latest
    permissions:
      issues: write
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Hound
        run: pip install hound-watchdog
      - name: Run Hound Check
        run: hound check
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""


@click.group()
@click.version_option(version="0.1.0", prog_name="hound")
def main() -> None:
    """🐕 Hound: Continuous third-party API watchdog and blast-radius correlation engine."""


@main.command("init")
@click.option(
    "--with-action",
    is_flag=True,
    help="Also scaffold GitHub Action workflow (.github/workflows/hound.yml)",
)
@click.option(
    "--detect",
    is_flag=True,
    help="Auto-detect third-party API dependencies in the current codebase",
)
@click.option("--force", is_flag=True, help="Overwrite existing configuration file")
def cmd_init(with_action: bool, detect: bool, force: bool) -> None:
    """Scaffold hound.yaml in the current repository."""
    config_path = Path("hound.yaml")
    if config_path.exists() and not force:
        err_console.print("[yellow]hound.yaml already exists. Use --force to overwrite.[/yellow]")
        sys.exit(0)

    if detect:
        wizard = AutoDiscoveryWizard()
        config_content = wizard.generate_config()
        console.print(
            "[cyan]🔍 Auto-detected API dependencies and scaffolded tailored config.[/cyan]"
        )
    else:
        config_content = generate_default_config(with_action=with_action)

    config_path.write_text(config_content, encoding="utf-8")
    console.print("[green]✔ Created hound.yaml[/green]")

    if with_action:
        action_dir = Path(".github/workflows")
        action_dir.mkdir(parents=True, exist_ok=True)
        action_path = action_dir / "hound.yml"
        action_path.write_text(GITHUB_ACTION_TEMPLATE, encoding="utf-8")
        console.print("[green]✔ Created .github/workflows/hound.yml[/green]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]hound.yaml[/cyan] with your API spec URLs and code paths.")
    console.print("  2. Run [cyan]hound check[/cyan] to establish baseline snapshots.\n")


@main.command("add")
@click.argument("name")
@click.option("--spec-url", required=True, help="URL or local path to OpenAPI/Swagger spec")
@click.option(
    "--scan-path",
    required=True,
    multiple=True,
    help="Codebase directory or file to scan (can be repeated)",
)
@click.option(
    "--lang",
    default="python",
    type=click.Choice(["python", "typescript", "javascript"]),
    help="Codebase language",
)
@click.option("--config", default="hound.yaml", help="Path to hound.yaml")
def cmd_add(name: str, spec_url: str, scan_path: tuple[str, ...], lang: str, config: str) -> None:
    """Register a new API to watch in hound.yaml."""
    cfg_file = Path(config)
    if not cfg_file.is_file():
        # Initialize default config if not existing
        cfg_file.write_text(generate_default_config(), encoding="utf-8")

    with open(cfg_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    watch_list = raw.get("watch", [])
    # Update or append
    target_entry = {
        "name": name,
        "spec_url": spec_url,
        "scan_paths": list(scan_path),
        "language": lang,
        "ignore_fields": [],
    }

    updated = False
    for i, t in enumerate(watch_list):
        if t.get("name") == name:
            watch_list[i] = target_entry
            updated = True
            break
    if not updated:
        watch_list.append(target_entry)

    raw["watch"] = watch_list
    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False)

    console.print(
        f"[green]✔ Watch target '{name}' {'updated' if updated else 'added'} in {config}[/green]"
    )


@main.command("validate")
@click.option("--config", default="hound.yaml", help="Path to hound.yaml")
def cmd_validate(config: str) -> None:
    """Validate hound.yaml against the configuration schema."""
    cfg_file = Path(config)
    if not cfg_file.is_file():
        err_console.print(f"[red]Error: {config} not found[/red]")
        sys.exit(2)

    try:
        load_config(cfg_file)
        console.print(f"[green]✔ {config} is valid.[/green]")
    except Exception as e:
        err_console.print(f"[red]Validation failed:[/red] {e}")
        sys.exit(2)


@main.command("check")
@click.option("--config", default="hound.yaml", help="Path to hound.yaml")
@click.option("--target", default=None, help="Check only specific target name")
@click.option("--dry-run", is_flag=True, help="Run without writing reports or advancing snapshot")
@click.option(
    "--verbose", is_flag=True, help="Show all changes including non-breaking and unaffected"
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "sarif"]),
    default="text",
    help="Output format (text, json, sarif)",
)
@click.option(
    "--output", "output_file", default=None, help="File path to write json or sarif output"
)
def cmd_check(
    config: str,
    target: str | None,
    dry_run: bool,
    verbose: bool,
    output_format: str,
    output_file: str | None,
) -> None:
    """Run full check cycle: fetch, diff, scan, correlate, report."""
    try:
        agent = HoundAgent.from_config_path(config)
    except Exception as e:
        err_console.print(f"[red]Configuration error:[/red] {e}")
        sys.exit(2)

    try:
        summary = agent.run_check(target_filter=target, dry_run=dry_run, verbose=verbose)
    except Exception as e:
        err_console.print(f"[red]Check failed:[/red] {e}")
        sys.exit(2)

    # Collect all findings across targets
    all_findings = []
    for res in summary.results:
        all_findings.extend(res.findings)

    if output_format == "sarif":
        exporter = SARIFExporter()
        sarif_json = exporter.export_json(all_findings)
        if output_file:
            Path(output_file).write_text(sarif_json, encoding="utf-8")
            console.print(f"[green]✔ Exported SARIF results to {output_file}[/green]")
        else:
            click.echo(sarif_json)
    elif output_format == "json":
        json_output = json.dumps([f.model_dump() for f in all_findings], indent=2)
        if output_file:
            Path(output_file).write_text(json_output, encoding="utf-8")
            console.print(f"[green]✔ Exported JSON results to {output_file}[/green]")
        else:
            click.echo(json_output)
    else:
        # Render results with rich CLI formatting
        _render_check_output(summary, verbose=verbose, dry_run=dry_run)

    sys.exit(summary.exit_code)


def _render_check_output(summary: Any, verbose: bool, dry_run: bool) -> None:
    """Format and print check results matching the Hound CLI ergonomics."""
    console.print()

    for res in summary.results:
        if res.is_baseline:
            console.print(
                f"[green]✔ Established baseline snapshot for '{res.target_name}' (hash: {res.spec_hash[:8]})[/green]"
            )
            continue

        if res.is_unchanged and not res.findings:
            console.print(
                f"[dim]• {res.target_name}: No spec changes detected (hash: {res.spec_hash[:8]})[/dim]"
            )
            continue

        for w in res.warnings:
            console.print(f"[yellow]⚠ Warning ({res.target_name}): {w}[/yellow]")

        if res.findings:
            breaking_in_target = sum(1 for f in res.findings if f.is_breaking)
            if breaking_in_target > 0:
                console.print(
                    f"[bold red]🐕 Hound found {breaking_in_target} breaking change{'s' if breaking_in_target != 1 else ''}[/bold red]\n"
                )
            else:
                console.print(
                    f"[bold yellow]🐕 Hound found {len(res.findings)} API update notice(s)[/bold yellow]\n"
                )

            for f in res.findings:
                sev_tag = (
                    "[bold red]⚠ BREAKING[/bold red]"
                    if f.is_breaking
                    else f"[yellow]ℹ {f.severity.upper()}[/yellow]"
                )
                endpoint_line = (
                    f"  [bold cyan]{res.target_name}[/bold cyan] · [bold]{f.change.endpoint}[/bold]"
                )
                console.print(endpoint_line)
                console.print(f"  {sev_tag}: {f.change.description}")
                for site in f.usage_sites:
                    console.print(
                        f"  [dim]→ used in [underline]{site.file}:{site.line}[/underline][/dim]"
                    )
                console.print()

            if res.suppressed_count > 0 and not verbose:
                console.print(
                    f"  [dim]{res.suppressed_count} non-breaking change{'s' if res.suppressed_count != 1 else ''} suppressed (run with --verbose to see all)[/dim]\n"
                )
        elif res.changes and not res.findings:
            if verbose:
                console.print(
                    f"[dim]• {res.target_name}: {len(res.changes)} spec change(s) detected, 0 intersect codebase.[/dim]"
                )
            else:
                console.print(
                    f"[green]✔ {res.target_name}: {len(res.changes)} spec change(s) detected, 0 affect your code.[/green]"
                )

    if dry_run:
        console.print("[dim](Dry-run mode: snapshots not advanced, no remote issues posted)[/dim]")


@main.command("diff")
@click.argument("name")
@click.option("--config", default="hound.yaml", help="Path to hound.yaml")
def cmd_diff(name: str, config: str) -> None:
    """Show raw structural diff for a target without running correlator."""
    try:
        cfg = load_config(config)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(2)

    target = next((t for t in cfg.watch if t.name == name), None)
    if not target:
        err_console.print(f"[red]Target '{name}' not found in {config}[/red]")
        sys.exit(2)

    store = LocalSnapshotStore()
    old_spec = store.get_snapshot(name)
    if old_spec is None:
        console.print(
            f"[yellow]No baseline snapshot found for '{name}'. Run 'hound check' to establish one.[/yellow]"
        )
        sys.exit(0)

    fetcher = OpenAPIFetcher()
    try:
        fetched = fetcher.fetch(target.spec_url)
    except Exception as e:
        err_console.print(f"[red]Failed to fetch current spec:[/red] {e}")
        sys.exit(2)

    diff_engine = SpecDiffEngine()
    changes = diff_engine.diff(old_spec, fetched.spec)

    if not changes:
        console.print(
            f"[green]No structural changes between baseline and current spec for '{name}'.[/green]"
        )
        return

    table = Table(title=f"Structural Diff for '{name}'")
    table.add_column("Severity", style="bold")
    table.add_column("Method")
    table.add_column("Endpoint")
    table.add_column("Field")
    table.add_column("Type")
    table.add_column("Description")

    for c in changes:
        sev = "[red]BREAKING[/red]" if c.breaking else "[green]NON-BREAKING[/green]"
        table.add_row(sev, c.method, c.endpoint, c.field or "-", c.change_type, c.description)

    console.print(table)


@main.command("baseline")
@click.argument("action", type=click.Choice(["reset"]))
@click.argument("name")
def cmd_baseline(action: str, name: str) -> None:
    """Manage baseline snapshots (e.g. hound baseline reset <name>)."""
    if action == "reset":
        store = LocalSnapshotStore()
        removed = store.reset_snapshot(name)
        if removed:
            console.print(
                f"[green]✔ Baseline snapshot for '{name}' was reset. Next check will re-baseline.[/green]"
            )
        else:
            console.print(f"[yellow]No snapshot found for '{name}'.[/yellow]")


if __name__ == "__main__":
    main()
