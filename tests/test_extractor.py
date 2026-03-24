"""Tests for the extraction logic with mocked Claude API responses."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from invoice_ai.extractor import InvoiceExtractor
from invoice_ai.models import ConfidenceLevel, ExtractionResult


MOCK_CLAUDE_RESPONSE = json.dumps({
    "vendor_name": "Acme Corporation",
    "vendor_address": "456 Business Ave, Suite 200, San Francisco, CA 94102",
    "invoice_number": "INV-2025-0042",
    "invoice_date": "2025-01-15",
    "due_date": "2025-02-14",
    "line_items": [
        {
            "description": "Professional Consulting Services",
            "quantity": 40,
            "unit_price": 150.00,
            "amount": 6000.00,
        },
        {
            "description": "Travel Expenses",
            "quantity": 1,
            "unit_price": 350.00,
            "amount": 350.00,
        },
    ],
    "subtotal": 6350.00,
    "tax": 508.00,
    "total": 6858.00,
    "currency": "USD",
    "payment_terms": "Net 30",
    "confidence_scores": [
        {"field": "vendor_name", "confidence": "high", "reason": "Clearly printed"},
        {"field": "total", "confidence": "high", "reason": "Clearly stated"},
        {"field": "invoice_number", "confidence": "high", "reason": "Visible at top"},
        {"field": "invoice_date", "confidence": "medium", "reason": "Parsed from header"},
    ],
})


MOCK_CLAUDE_RESPONSE_FENCED = f"```json\n{MOCK_CLAUDE_RESPONSE}\n```"


def _make_mock_api_response(text: str) -> MagicMock:
    """Build a mock that mimics anthropic.types.Message."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


@pytest.fixture()
def extractor() -> InvoiceExtractor:
    """Create an extractor with a dummy API key (API calls are mocked)."""
    return InvoiceExtractor(api_key="test-key-not-real")


class TestParseResponse:
    """Test the _parse_response helper directly."""

    def test_valid_json(self, extractor: InvoiceExtractor):
        result = extractor._parse_response(
            MOCK_CLAUDE_RESPONSE, Path("invoice.pdf"), page_count=1, method="vision"
        )
        assert result.invoice.vendor_name == "Acme Corporation"
        assert result.invoice.total == 6858.00
        assert len(result.invoice.line_items) == 2
        assert result.invoice.currency == "USD"
        assert result.source_file == "invoice.pdf"
        assert result.extraction_method == "vision"

    def test_fenced_json(self, extractor: InvoiceExtractor):
        """Should strip markdown code fences."""
        result = extractor._parse_response(
            MOCK_CLAUDE_RESPONSE_FENCED, Path("invoice.pdf"), page_count=1, method="vision"
        )
        assert result.invoice.vendor_name == "Acme Corporation"

    def test_invalid_json_raises(self, extractor: InvoiceExtractor):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            extractor._parse_response(
                "this is not json", Path("test.pdf"), page_count=1, method="vision"
            )

    def test_missing_required_fields_raises(self, extractor: InvoiceExtractor):
        bad_data = json.dumps({"some_field": "value"})
        with pytest.raises(RuntimeError, match="schema"):
            extractor._parse_response(
                bad_data, Path("test.pdf"), page_count=1, method="vision"
            )

    def test_confidence_scores_parsed(self, extractor: InvoiceExtractor):
        result = extractor._parse_response(
            MOCK_CLAUDE_RESPONSE, Path("test.pdf"), page_count=1, method="vision"
        )
        assert len(result.confidence_scores) == 4
        assert result.confidence_scores[0].field == "vendor_name"
        assert result.confidence_scores[0].confidence == ConfidenceLevel.HIGH

    def test_bad_confidence_entries_skipped(self, extractor: InvoiceExtractor):
        data = json.loads(MOCK_CLAUDE_RESPONSE)
        data["confidence_scores"].append({"bad": "entry"})
        result = extractor._parse_response(
            json.dumps(data), Path("test.pdf"), page_count=1, method="vision"
        )
        # The 4 valid entries should still be parsed; the bad one is skipped
        assert len(result.confidence_scores) == 4


class TestExtractViaVision:
    """Test the vision extraction path with mocked dependencies."""

    @patch("invoice_ai.extractor.pdf_to_images")
    @patch("invoice_ai.extractor.image_to_base64")
    @patch("invoice_ai.extractor.get_pdf_page_count")
    def test_success(
        self,
        mock_page_count: MagicMock,
        mock_b64: MagicMock,
        mock_pdf_to_images: MagicMock,
        extractor: InvoiceExtractor,
    ):
        mock_page_count.return_value = 1
        mock_pdf_to_images.return_value = [MagicMock()]  # one fake image
        mock_b64.return_value = "base64data"
        extractor.client.messages.create = MagicMock(
            return_value=_make_mock_api_response(MOCK_CLAUDE_RESPONSE)
        )

        result = extractor.extract(Path("invoice.pdf"))
        assert result.invoice.vendor_name == "Acme Corporation"
        assert result.extraction_method == "vision"
        extractor.client.messages.create.assert_called_once()


class TestExtractViaTextFallback:
    """Test that text-based fallback is used when vision fails."""

    @patch("invoice_ai.extractor.extract_text_with_pdfplumber")
    @patch("invoice_ai.extractor.pdf_to_images", side_effect=RuntimeError("poppler missing"))
    @patch("invoice_ai.extractor.get_pdf_page_count")
    def test_fallback_to_text(
        self,
        mock_page_count: MagicMock,
        mock_pdf_to_images: MagicMock,
        mock_text: MagicMock,
        extractor: InvoiceExtractor,
    ):
        mock_page_count.return_value = 1
        mock_text.return_value = "Acme Corp\nInvoice #123\nTotal: $100"
        extractor.client.messages.create = MagicMock(
            return_value=_make_mock_api_response(MOCK_CLAUDE_RESPONSE)
        )

        result = extractor.extract(Path("invoice.pdf"))
        assert result.invoice.vendor_name == "Acme Corporation"
        assert result.extraction_method == "text"
        assert len(result.errors) == 1  # vision failure recorded


class TestExtractBatch:
    """Test batch processing."""

    @patch("invoice_ai.extractor.pdf_to_images")
    @patch("invoice_ai.extractor.image_to_base64")
    @patch("invoice_ai.extractor.get_pdf_page_count")
    def test_batch_mixed_results(
        self,
        mock_page_count: MagicMock,
        mock_b64: MagicMock,
        mock_pdf_to_images: MagicMock,
        extractor: InvoiceExtractor,
    ):
        mock_page_count.return_value = 1
        mock_pdf_to_images.return_value = [MagicMock()]
        mock_b64.return_value = "base64data"

        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("API error")
            return _make_mock_api_response(MOCK_CLAUDE_RESPONSE)

        extractor.client.messages.create = MagicMock(side_effect=side_effect)

        # Second call will fail both vision and text fallback
        with patch("invoice_ai.extractor.extract_text_with_pdfplumber", side_effect=RuntimeError("no text")):
            results = extractor.extract_batch([Path("a.pdf"), Path("b.pdf"), Path("c.pdf")])

        assert len(results) == 3
        assert results[0].invoice.vendor_name == "Acme Corporation"
        assert results[1].extraction_method == "failed"  # b.pdf failed
        assert results[2].invoice.vendor_name == "Acme Corporation"


class TestNoApiKey:
    def test_raises_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            # Also remove the key if set
            import os
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            with patch.dict("os.environ", env, clear=True):
                with pytest.raises(ValueError, match="No API key"):
                    InvoiceExtractor()
