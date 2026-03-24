"""Click CLI for invoice-ai."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from invoice_ai.exporters import write_output
from invoice_ai.extractor import InvoiceExtractor
from invoice_ai.models import ConfidenceLevel, ExtractionResult
from invoice_ai.pdf_utils import find_pdfs

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False)],
    )


def _print_result(result: ExtractionResult) -> None:
    """Pretty-print a single extraction result."""
    inv = result.invoice

    if result.errors:
        for err in result.errors:
            console.print(f"  [yellow]Warning:[/yellow] {err}")

    table = Table(title=f"Invoice: {result.source_file}", show_header=False, expand=True)
    table.add_column("Field", style="bold cyan", width=20)
    table.add_column("Value")

    table.add_row("Vendor", inv.vendor_name)
    if inv.vendor_address:
        table.add_row("Address", inv.vendor_address)
    if inv.invoice_number:
        table.add_row("Invoice #", inv.invoice_number)
    if inv.invoice_date:
        table.add_row("Date", inv.invoice_date)
    if inv.due_date:
        table.add_row("Due Date", inv.due_date)
    if inv.payment_terms:
        table.add_row("Payment Terms", inv.payment_terms)

    table.add_row("Currency", inv.currency)
    if inv.subtotal is not None:
        table.add_row("Subtotal", f"{inv.subtotal:,.2f}")
    if inv.tax is not None:
        table.add_row("Tax", f"{inv.tax:,.2f}")
    table.add_row("Total", f"[bold green]{inv.total:,.2f}[/bold green]")

    confidence = result.overall_confidence
    style_map = {
        ConfidenceLevel.HIGH: "green",
        ConfidenceLevel.MEDIUM: "yellow",
        ConfidenceLevel.LOW: "red",
    }
    table.add_row(
        "Confidence", f"[{style_map[confidence]}]{confidence.value}[/{style_map[confidence]}]"
    )
    table.add_row("Method", result.extraction_method)
    table.add_row("Pages", str(result.page_count))

    console.print(table)

    if inv.line_items:
        items_table = Table(title="Line Items")
        items_table.add_column("#", justify="right", width=4)
        items_table.add_column("Description")
        items_table.add_column("Qty", justify="right", width=8)
        items_table.add_column("Unit Price", justify="right", width=12)
        items_table.add_column("Amount", justify="right", width=12)

        for i, item in enumerate(inv.line_items, 1):
            items_table.add_row(
                str(i),
                item.description,
                f"{item.quantity}" if item.quantity is not None else "-",
                f"{item.unit_price:,.2f}" if item.unit_price is not None else "-",
                f"{item.amount:,.2f}",
            )

        console.print(items_table)


@click.group()
@click.version_option(package_name="invoice-ai", prog_name="invoice-ai")
def cli() -> None:
    """invoice-ai: Extract structured data from invoices using Claude."""


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("-o", "--output", "output_path", type=click.Path(), default=None,
              help="Write results to this file.")
@click.option("-f", "--format", "fmt", type=click.Choice(["json", "csv"]), default="json",
              help="Output format (default: json).")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
@click.option("--model", default=None, help="Override the Claude model to use.")
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY",
              help="Anthropic API key (or set ANTHROPIC_API_KEY).")
def extract(
    path: str,
    output_path: str | None,
    fmt: str,
    verbose: bool,
    model: str | None,
    api_key: str | None,
) -> None:
    """Extract structured data from a PDF invoice or a directory of PDFs."""
    _setup_logging(verbose)

    # Resolve input files
    try:
        pdf_files = find_pdfs(path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    console.print(f"Found [bold]{len(pdf_files)}[/bold] PDF(s) to process.\n")

    # Build extractor
    kwargs: dict = {}
    if model:
        kwargs["model"] = model
    try:
        extractor = InvoiceExtractor(api_key=api_key, **kwargs)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # Process
    results: list[ExtractionResult] = []
    with console.status("[bold green]Extracting invoice data...") as status:
        for i, pdf in enumerate(pdf_files, 1):
            status.update(f"[bold green]Processing {pdf.name} ({i}/{len(pdf_files)})...")
            try:
                result = extractor.extract(pdf)
                results.append(result)
            except Exception as exc:
                console.print(f"[red]Failed to process {pdf.name}:[/red] {exc}")
                results.append(
                    ExtractionResult(
                        source_file=str(pdf),
                        page_count=0,
                        invoice=InvoiceData(vendor_name="EXTRACTION_FAILED", total=0.0),
                        errors=[str(exc)],
                        extraction_method="failed",
                    )
                )

    # Display results
    for result in results:
        _print_result(result)
        console.print()

    # Write output
    if output_path or fmt == "csv":
        effective_path = output_path or f"output.{fmt}"
        content = write_output(results, effective_path, fmt=fmt)
        console.print(f"\n[green]Results written to {effective_path}[/green]")
    elif not output_path:
        # Print JSON to stdout when no output file specified
        content = write_output(results, output_path=None, fmt="json")
        # Already printed the rich table above; JSON goes to file only when requested

    success_count = sum(1 for r in results if r.extraction_method != "failed")
    console.print(
        Panel(
            f"[bold green]{success_count}[/bold green] of {len(results)} invoice(s) processed successfully.",
            title="Summary",
        )
    )


# Need to import InvoiceData for the error-result fallback used in extract()
from invoice_ai.models import InvoiceData as InvoiceData  # noqa: E402
