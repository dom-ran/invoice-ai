"""Tests for JSON and CSV exporters."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from invoice_ai.exporters import results_to_csv, results_to_json, write_output
from invoice_ai.models import (
    ConfidenceLevel,
    ExtractionResult,
    FieldConfidence,
    InvoiceData,
    LineItem,
)


@pytest.fixture()
def sample_results() -> list[ExtractionResult]:
    return [
        ExtractionResult(
            source_file="invoice_a.pdf",
            page_count=1,
            invoice=InvoiceData(
                vendor_name="Acme Corp",
                invoice_number="INV-001",
                invoice_date="2025-01-15",
                total=150.00,
                tax=12.00,
                subtotal=138.00,
                line_items=[
                    LineItem(description="Widget", quantity=3, unit_price=46.00, amount=138.00),
                ],
            ),
            confidence_scores=[
                FieldConfidence(field="vendor_name", confidence=ConfidenceLevel.HIGH),
                FieldConfidence(field="total", confidence=ConfidenceLevel.HIGH),
            ],
        ),
        ExtractionResult(
            source_file="invoice_b.pdf",
            page_count=2,
            invoice=InvoiceData(
                vendor_name="Globex Inc",
                total=500.00,
                currency="EUR",
                line_items=[
                    LineItem(description="Service A", amount=300.00),
                    LineItem(description="Service B", amount=200.00),
                ],
            ),
        ),
    ]


class TestResultsToJson:
    def test_valid_json(self, sample_results: list[ExtractionResult]):
        output = results_to_json(sample_results)
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_contains_expected_fields(self, sample_results: list[ExtractionResult]):
        output = results_to_json(sample_results)
        data = json.loads(output)
        first = data[0]
        assert first["source_file"] == "invoice_a.pdf"
        assert first["invoice"]["vendor_name"] == "Acme Corp"
        assert first["invoice"]["total"] == 150.00
        assert first["overall_confidence"] == "high"

    def test_compact_json(self, sample_results: list[ExtractionResult]):
        output = results_to_json(sample_results, pretty=False)
        assert "\n" not in output


class TestResultsToCsv:
    def test_correct_row_count(self, sample_results: list[ExtractionResult]):
        output = results_to_csv(sample_results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        # 1 line item from invoice_a + 2 from invoice_b = 3 rows
        assert len(rows) == 3

    def test_csv_headers_present(self, sample_results: list[ExtractionResult]):
        output = results_to_csv(sample_results)
        reader = csv.DictReader(io.StringIO(output))
        headers = reader.fieldnames
        assert headers is not None
        assert "source_file" in headers
        assert "vendor_name" in headers
        assert "item_description" in headers
        assert "item_amount" in headers

    def test_csv_values(self, sample_results: list[ExtractionResult]):
        output = results_to_csv(sample_results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["vendor_name"] == "Acme Corp"
        assert rows[0]["item_description"] == "Widget"
        assert float(rows[0]["item_amount"]) == 138.00

    def test_empty_results(self):
        output = results_to_csv([])
        assert output == ""


class TestWriteOutput:
    def test_write_json_file(self, tmp_path: Path, sample_results: list[ExtractionResult]):
        out = tmp_path / "output.json"
        content = write_output(sample_results, out, fmt="json")
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 2
        assert content == out.read_text()

    def test_write_csv_file(self, tmp_path: Path, sample_results: list[ExtractionResult]):
        out = tmp_path / "output.csv"
        write_output(sample_results, out, fmt="csv")
        assert out.exists()
        reader = csv.DictReader(io.StringIO(out.read_text()))
        rows = list(reader)
        assert len(rows) == 3

    def test_return_string_without_file(self, sample_results: list[ExtractionResult]):
        content = write_output(sample_results, output_path=None, fmt="json")
        data = json.loads(content)
        assert len(data) == 2

    def test_unsupported_format_raises(self, sample_results: list[ExtractionResult]):
        with pytest.raises(ValueError, match="Unsupported"):
            write_output(sample_results, output_path=None, fmt="xml")

    def test_creates_parent_dirs(self, tmp_path: Path, sample_results: list[ExtractionResult]):
        out = tmp_path / "deep" / "nested" / "output.json"
        write_output(sample_results, out, fmt="json")
        assert out.exists()
