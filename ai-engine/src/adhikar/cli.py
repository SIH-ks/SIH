"""Command-line entry point: ``adhikar extract <file>``.

Kept thin -- it is a Typer wrapper over :func:`adhikar.pipeline.process_document`,
so the same code path is exercised whether the engine is driven from the CLI or from
the FastAPI backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .exceptions import AdhikarError
from .pipeline import process_document
from .schemas.enums import RecordFormat
from .validation import registered_rules

app = typer.Typer(
    name="adhikar",
    help="OCR + Vision-LLM extraction and validation for Indian land records.",
    add_completion=False,
)
console = Console()


@app.command()
def extract(
    file: Path = typer.Argument(..., exists=True, readable=True, help="A scanned PDF or image."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write the artifact JSON here."),
    declared_format: str = typer.Option(
        "unknown", "--format", "-f", help="jamabandi | satbara_7_12 | khasra_girdawari | ror_generic | unknown"
    ),
    geometry: Path | None = typer.Option(
        None, "--geometry", "-g", help="GeoJSON FeatureCollection of cadastral polygons to cross-reference."
    ),
) -> None:
    """Extract, validate, and (optionally) discrepancy-check one document."""
    try:
        fmt = RecordFormat(declared_format)
    except ValueError:
        console.print(f"[red]Unknown format {declared_format!r}[/red]")
        raise typer.Exit(code=2) from None

    geometries = _load_geometries(geometry) if geometry else None

    settings = get_settings()
    if settings.llm_provider == "groq":
        model_desc = f"{settings.groq_model} (groq, json-mode)"
    else:
        model_desc = f"{settings.llm_model} (anthropic, effort={settings.llm_effort})"
    console.print(f"[bold]Processing[/bold] {file} with {model_desc}")

    try:
        artifact = process_document(
            file,
            declared_format=fmt,
            geometries_by_parcel_key=geometries,
        )
    except AdhikarError as exc:
        console.print(f"[red]Extraction failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    _print_summary(artifact)

    if output is not None:
        output.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"\nArtifact written to [bold]{output}[/bold]")
    else:
        console.print("\n[dim](pass --output to save the full JSON artifact)[/dim]")


@app.command("list-rules")
def list_rules() -> None:
    """List every registered validation rule."""
    table = Table(title="Registered validation rules")
    table.add_column("Rule code")
    table.add_column("Description")
    for code, description in sorted(registered_rules().items(), key=lambda kv: kv[0].value):
        table.add_row(code.value, description)
    console.print(table)


def _load_geometries(path: Path) -> dict:
    from .geo.discrepancy import build_parcel_geometry
    from .schemas.geo import GeometrySource

    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    result = {}
    for feature in features:
        key = feature.get("properties", {}).get("parcel_key")
        if not key:
            continue
        result[key] = build_parcel_geometry(key, feature["geometry"], source=GeometrySource.CADASTRAL_SHAPEFILE)
    return result


def _print_summary(artifact) -> None:  # noqa: ANN001
    console.print(f"\n[bold]Detected format:[/bold] {artifact.detected_record_format.value}")
    console.print(f"[bold]Parcels found:[/bold] {len(artifact.parcels)}")
    console.print(f"[bold]Mean OCR confidence:[/bold] {artifact.mean_ocr_confidence:.2f}")
    console.print(f"[bold]Requires human review:[/bold] {artifact.requires_human_review}")

    if artifact.validation is not None:
        table = Table(title="Validation findings")
        table.add_column("Severity")
        table.add_column("Rule")
        table.add_column("Message")
        for issue in artifact.validation.sorted_issues()[:25]:
            table.add_row(issue.severity.value, issue.rule_code.value, issue.message)
        console.print(table)

    for report in artifact.discrepancies:
        console.print(f"  {report.headline}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
