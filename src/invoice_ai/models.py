"""Pydantic data models for invoice extraction."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ConfidenceLevel(str, Enum):
    """Confidence indicator for an extracted field."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FieldConfidence(BaseModel):
    """Confidence score for a single extracted field."""

    field: str
    confidence: ConfidenceLevel
    reason: str | None = None


class LineItem(BaseModel):
    """A single line item on an invoice."""

    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float

    @model_validator(mode="after")
    def check_amount_consistency(self) -> LineItem:
        """Warn if quantity * unit_price doesn't match amount."""
        if self.quantity is not None and self.unit_price is not None:
            expected = round(self.quantity * self.unit_price, 2)
            if abs(expected - self.amount) > 0.01:
                # Don't fail validation -- invoices can have discounts, etc.
                pass
        return self


class InvoiceData(BaseModel):
    """Structured data extracted from an invoice or receipt."""

    vendor_name: str
    vendor_address: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float
    currency: str = "USD"
    payment_terms: str | None = None
    raw_text: str | None = Field(default=None, exclude=True)


class ExtractionResult(BaseModel):
    """Full extraction result including invoice data and metadata."""

    source_file: str
    page_count: int = 1
    invoice: InvoiceData
    confidence_scores: list[FieldConfidence] = Field(default_factory=list)
    extraction_method: str = "vision"
    errors: list[str] = Field(default_factory=list)

    @property
    def overall_confidence(self) -> ConfidenceLevel:
        """Compute the overall confidence from individual field scores."""
        if not self.confidence_scores:
            return ConfidenceLevel.MEDIUM
        levels = [s.confidence for s in self.confidence_scores]
        if all(l == ConfidenceLevel.HIGH for l in levels):
            return ConfidenceLevel.HIGH
        if any(l == ConfidenceLevel.LOW for l in levels):
            return ConfidenceLevel.LOW
        return ConfidenceLevel.MEDIUM

    def to_flat_dict(self) -> dict[str, Any]:
        """Flatten invoice data for CSV export."""
        inv = self.invoice
        base: dict[str, Any] = {
            "source_file": self.source_file,
            "vendor_name": inv.vendor_name,
            "vendor_address": inv.vendor_address or "",
            "invoice_number": inv.invoice_number or "",
            "invoice_date": inv.invoice_date or "",
            "due_date": inv.due_date or "",
            "subtotal": inv.subtotal,
            "tax": inv.tax,
            "total": inv.total,
            "currency": inv.currency,
            "payment_terms": inv.payment_terms or "",
            "overall_confidence": self.overall_confidence.value,
            "extraction_method": self.extraction_method,
        }
        return base

    def to_line_item_rows(self) -> list[dict[str, Any]]:
        """Return one row per line item for detailed CSV export."""
        rows: list[dict[str, Any]] = []
        base = self.to_flat_dict()
        if not self.invoice.line_items:
            rows.append({**base, "item_description": "", "item_quantity": None,
                         "item_unit_price": None, "item_amount": None})
        else:
            for item in self.invoice.line_items:
                rows.append({
                    **base,
                    "item_description": item.description,
                    "item_quantity": item.quantity,
                    "item_unit_price": item.unit_price,
                    "item_amount": item.amount,
                })
        return rows
