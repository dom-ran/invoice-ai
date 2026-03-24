"""Tests for Pydantic data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from invoice_ai.models import (
    ConfidenceLevel,
    ExtractionResult,
    FieldConfidence,
    InvoiceData,
    LineItem,
)


# ---------------------------------------------------------------------------
# LineItem
# ---------------------------------------------------------------------------

class TestLineItem:
    def test_minimal(self):
        item = LineItem(description="Widget", amount=10.0)
        assert item.description == "Widget"
        assert item.amount == 10.0
        assert item.quantity is None
        assert item.unit_price is None

    def test_full(self):
        item = LineItem(description="Widget", quantity=2, unit_price=5.0, amount=10.0)
        assert item.quantity == 2.0
        assert item.unit_price == 5.0

    def test_missing_description_fails(self):
        with pytest.raises(ValidationError):
            LineItem(amount=10.0)  # type: ignore[call-arg]

    def test_missing_amount_fails(self):
        with pytest.raises(ValidationError):
            LineItem(description="Widget")  # type: ignore[call-arg]

    def test_amount_mismatch_does_not_raise(self):
        """Mismatched qty*price vs amount is allowed (discounts, etc.)."""
        item = LineItem(description="Widget", quantity=2, unit_price=5.0, amount=9.0)
        assert item.amount == 9.0


# ---------------------------------------------------------------------------
# InvoiceData
# ---------------------------------------------------------------------------

class TestInvoiceData:
    def test_minimal(self):
        inv = InvoiceData(vendor_name="Acme Corp", total=100.0)
        assert inv.vendor_name == "Acme Corp"
        assert inv.total == 100.0
        assert inv.currency == "USD"
        assert inv.line_items == []

    def test_full_invoice(self):
        inv = InvoiceData(
            vendor_name="Acme Corp",
            vendor_address="123 Main St",
            invoice_number="INV-001",
            invoice_date="2025-01-15",
            due_date="2025-02-15",
            line_items=[
                LineItem(description="Widget A", quantity=2, unit_price=25.0, amount=50.0),
                LineItem(description="Widget B", quantity=1, unit_price=50.0, amount=50.0),
            ],
            subtotal=100.0,
            tax=8.0,
            total=108.0,
            currency="EUR",
            payment_terms="Net 30",
        )
        assert len(inv.line_items) == 2
        assert inv.currency == "EUR"

    def test_missing_vendor_name_fails(self):
        with pytest.raises(ValidationError):
            InvoiceData(total=100.0)  # type: ignore[call-arg]

    def test_missing_total_fails(self):
        with pytest.raises(ValidationError):
            InvoiceData(vendor_name="Acme")  # type: ignore[call-arg]

    def test_raw_text_excluded_from_dict(self):
        inv = InvoiceData(vendor_name="Acme", total=100.0, raw_text="hello world")
        d = inv.model_dump()
        assert "raw_text" not in d

    def test_default_currency(self):
        inv = InvoiceData(vendor_name="Acme", total=50.0)
        assert inv.currency == "USD"


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------

class TestExtractionResult:
    @pytest.fixture()
    def sample_invoice(self) -> InvoiceData:
        return InvoiceData(
            vendor_name="Test Vendor",
            invoice_number="INV-100",
            total=250.0,
            line_items=[
                LineItem(description="Service A", amount=150.0),
                LineItem(description="Service B", amount=100.0),
            ],
        )

    def test_overall_confidence_all_high(self, sample_invoice: InvoiceData):
        result = ExtractionResult(
            source_file="test.pdf",
            invoice=sample_invoice,
            confidence_scores=[
                FieldConfidence(field="vendor_name", confidence=ConfidenceLevel.HIGH),
                FieldConfidence(field="total", confidence=ConfidenceLevel.HIGH),
            ],
        )
        assert result.overall_confidence == ConfidenceLevel.HIGH

    def test_overall_confidence_any_low(self, sample_invoice: InvoiceData):
        result = ExtractionResult(
            source_file="test.pdf",
            invoice=sample_invoice,
            confidence_scores=[
                FieldConfidence(field="vendor_name", confidence=ConfidenceLevel.HIGH),
                FieldConfidence(field="total", confidence=ConfidenceLevel.LOW),
            ],
        )
        assert result.overall_confidence == ConfidenceLevel.LOW

    def test_overall_confidence_mixed_medium(self, sample_invoice: InvoiceData):
        result = ExtractionResult(
            source_file="test.pdf",
            invoice=sample_invoice,
            confidence_scores=[
                FieldConfidence(field="vendor_name", confidence=ConfidenceLevel.HIGH),
                FieldConfidence(field="total", confidence=ConfidenceLevel.MEDIUM),
            ],
        )
        assert result.overall_confidence == ConfidenceLevel.MEDIUM

    def test_overall_confidence_empty_scores(self, sample_invoice: InvoiceData):
        result = ExtractionResult(source_file="test.pdf", invoice=sample_invoice)
        assert result.overall_confidence == ConfidenceLevel.MEDIUM

    def test_to_flat_dict(self, sample_invoice: InvoiceData):
        result = ExtractionResult(source_file="test.pdf", invoice=sample_invoice)
        flat = result.to_flat_dict()
        assert flat["source_file"] == "test.pdf"
        assert flat["vendor_name"] == "Test Vendor"
        assert flat["total"] == 250.0
        assert "item_description" not in flat

    def test_to_line_item_rows(self, sample_invoice: InvoiceData):
        result = ExtractionResult(source_file="test.pdf", invoice=sample_invoice)
        rows = result.to_line_item_rows()
        assert len(rows) == 2
        assert rows[0]["item_description"] == "Service A"
        assert rows[1]["item_amount"] == 100.0

    def test_to_line_item_rows_no_items(self):
        inv = InvoiceData(vendor_name="Acme", total=50.0)
        result = ExtractionResult(source_file="test.pdf", invoice=inv)
        rows = result.to_line_item_rows()
        assert len(rows) == 1
        assert rows[0]["item_description"] == ""
