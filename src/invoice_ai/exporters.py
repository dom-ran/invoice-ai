"""Export extraction results to JSON and CSV formats."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from invoice_ai.models import ExtractionResult


def results_to_json(results: list[ExtractionResult], pretty: bool = True) -> str:
    """Serialize a list of extraction results to a JSON string.

    Args:
        results: Extraction results to serialize.
        pretty: Whether to indent the output.

    Returns:
        JSON string.
    """
    data: list[dict[str, Any]] = []
    for r in results:
        entry = r.model_dump(mode="json")
        entry["overall_confidence"] = r.overall_confidence.value
        data.append(entry)

    return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)


def results_to_csv(results: list[ExtractionResult]) -> str:
    """Serialize extraction results to CSV (one row per line item).

    Args:
        results: Extraction results to serialize.

    Returns:
        CSV string.
    """
    all_rows: list[dict[str, Any]] = []
    for r in results:
        all_rows.extend(r.to_line_item_rows())

    if not all_rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(all_rows[0].keys()))
    writer.writeheader()
    writer.writerows(all_rows)
    return output.getvalue()


def write_output(
    results: list[ExtractionResult],
    output_path: str | Path | None,
    fmt: str = "json",
) -> str:
    """Write results to a file or return as a string.

    Args:
        results: Extraction results.
        output_path: File path to write. If ``None``, the formatted string is returned.
        fmt: Output format — ``"json"`` or ``"csv"``.

    Returns:
        The formatted output string.

    Raises:
        ValueError: For unsupported formats.
    """
    if fmt == "json":
        content = results_to_json(results)
    elif fmt == "csv":
        content = results_to_csv(results)
    else:
        raise ValueError(f"Unsupported output format: {fmt!r}. Use 'json' or 'csv'.")

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    return content
