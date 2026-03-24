"""Core extraction logic: send invoice images to Claude and parse structured data."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from invoice_ai.models import (
    ConfidenceLevel,
    ExtractionResult,
    FieldConfidence,
    InvoiceData,
)
from invoice_ai.pdf_utils import (
    extract_text_with_pdfplumber,
    get_pdf_page_count,
    image_to_base64,
    pdf_to_images,
)

logger = logging.getLogger(__name__)

VISION_EXTRACTION_PROMPT = """\
You are an expert invoice and receipt data extraction system. Analyze the provided \
invoice image(s) carefully and extract all structured data.

Return a JSON object with exactly this schema:
{
  "vendor_name": "string (required)",
  "vendor_address": "string or null",
  "invoice_number": "string or null",
  "invoice_date": "string in YYYY-MM-DD format or null",
  "due_date": "string in YYYY-MM-DD format or null",
  "line_items": [
    {
      "description": "string",
      "quantity": number or null,
      "unit_price": number or null,
      "amount": number
    }
  ],
  "subtotal": number or null,
  "tax": number or null,
  "total": number (required),
  "currency": "3-letter ISO code, default USD",
  "payment_terms": "string or null",
  "confidence_scores": [
    {
      "field": "field_name",
      "confidence": "high" | "medium" | "low",
      "reason": "brief explanation"
    }
  ]
}

Rules:
- Parse dates into YYYY-MM-DD format when possible.
- Monetary values should be plain numbers without currency symbols.
- If a field is not present or unreadable, set it to null.
- Include a confidence score for each non-null top-level field.
- For line items, extract as many as visible. If quantities or unit prices are unclear, set them to null but always include the amount.
- The "total" field is required — estimate it from line items if not explicitly stated.
- Return ONLY the JSON object, no markdown fencing or extra text.
"""

TEXT_EXTRACTION_PROMPT = """\
You are an expert invoice and receipt data extraction system. The following is raw text \
extracted from an invoice PDF. Parse it and extract all structured data.

--- BEGIN INVOICE TEXT ---
{text}
--- END INVOICE TEXT ---

Return a JSON object with exactly this schema:
{{
  "vendor_name": "string (required)",
  "vendor_address": "string or null",
  "invoice_number": "string or null",
  "invoice_date": "string in YYYY-MM-DD format or null",
  "due_date": "string in YYYY-MM-DD format or null",
  "line_items": [
    {{
      "description": "string",
      "quantity": number or null,
      "unit_price": number or null,
      "amount": number
    }}
  ],
  "subtotal": number or null,
  "tax": number or null,
  "total": number (required),
  "currency": "3-letter ISO code, default USD",
  "payment_terms": "string or null",
  "confidence_scores": [
    {{
      "field": "field_name",
      "confidence": "high" | "medium" | "low",
      "reason": "brief explanation"
    }}
  ]
}}

Rules:
- Parse dates into YYYY-MM-DD format when possible.
- Monetary values should be plain numbers without currency symbols.
- If a field is not present or unreadable, set it to null.
- Include a confidence score for each non-null top-level field.
- The "total" field is required — estimate it from line items if not explicitly stated.
- Return ONLY the JSON object, no markdown fencing or extra text.
"""

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class InvoiceExtractor:
    """Extract structured invoice data from PDFs using Claude's vision capabilities.

    Args:
        api_key: Anthropic API key. Falls back to the ``ANTHROPIC_API_KEY`` env var.
        model: Claude model to use.
        max_tokens: Maximum response tokens.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "No API key provided. Set ANTHROPIC_API_KEY or pass api_key to InvoiceExtractor."
            )
        self.client = anthropic.Anthropic(api_key=resolved_key)
        self.model = model
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, pdf_path: str | Path) -> ExtractionResult:
        """Extract invoice data from a PDF file.

        Tries vision-based extraction first. Falls back to text-based extraction
        if image conversion or the vision API call fails.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            An ``ExtractionResult`` with the extracted data.
        """
        pdf_path = Path(pdf_path)
        errors: list[str] = []
        page_count = 1

        try:
            page_count = get_pdf_page_count(pdf_path)
        except Exception:
            pass

        # --- Attempt 1: vision-based extraction ---
        try:
            logger.info("Attempting vision-based extraction for %s", pdf_path.name)
            return self._extract_via_vision(pdf_path, page_count)
        except Exception as exc:
            msg = f"Vision extraction failed: {exc}"
            logger.warning(msg)
            errors.append(msg)

        # --- Attempt 2: text-based fallback ---
        try:
            logger.info("Falling back to text-based extraction for %s", pdf_path.name)
            result = self._extract_via_text(pdf_path, page_count)
            result.errors = errors
            return result
        except Exception as exc:
            msg = f"Text extraction also failed: {exc}"
            logger.error(msg)
            errors.append(msg)
            raise RuntimeError(
                f"All extraction methods failed for {pdf_path.name}. Errors: {'; '.join(errors)}"
            ) from exc

    def extract_batch(self, pdf_paths: list[str | Path]) -> list[ExtractionResult]:
        """Extract invoice data from multiple PDFs.

        Processes files sequentially and collects results. Failures for individual
        files are captured as errors and do not halt the batch.

        Args:
            pdf_paths: List of PDF file paths.

        Returns:
            List of ``ExtractionResult`` objects (one per input file).
        """
        results: list[ExtractionResult] = []
        for path in pdf_paths:
            try:
                results.append(self.extract(path))
            except Exception as exc:
                logger.error("Failed to extract %s: %s", path, exc)
                # Create a minimal error result so the batch output stays aligned
                results.append(
                    ExtractionResult(
                        source_file=str(path),
                        page_count=0,
                        invoice=InvoiceData(vendor_name="EXTRACTION_FAILED", total=0.0),
                        errors=[str(exc)],
                        extraction_method="failed",
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_via_vision(self, pdf_path: Path, page_count: int) -> ExtractionResult:
        """Send PDF pages as images to Claude for extraction."""
        images = pdf_to_images(pdf_path)

        # Build the content blocks: one image per page, then the prompt
        content: list[dict[str, Any]] = []
        for img in images:
            b64 = image_to_base64(img)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        content.append({"type": "text", "text": VISION_EXTRACTION_PROMPT})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )

        raw_text = response.content[0].text  # type: ignore[union-attr]
        return self._parse_response(raw_text, pdf_path, page_count, method="vision")

    def _extract_via_text(self, pdf_path: Path, page_count: int) -> ExtractionResult:
        """Extract text with pdfplumber and send to Claude for parsing."""
        text = extract_text_with_pdfplumber(pdf_path)
        if not text.strip():
            raise RuntimeError("pdfplumber extracted no text from the PDF")

        prompt = TEXT_EXTRACTION_PROMPT.format(text=text)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text  # type: ignore[union-attr]
        result = self._parse_response(raw_text, pdf_path, page_count, method="text")
        result.invoice.raw_text = text
        return result

    def _parse_response(
        self, raw: str, pdf_path: Path, page_count: int, method: str
    ) -> ExtractionResult:
        """Parse Claude's JSON response into an ExtractionResult."""
        # Strip markdown code fencing if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening ```json or ``` line
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude returned invalid JSON: {exc}\nRaw: {raw[:500]}") from exc

        # Separate confidence scores from invoice data
        confidence_raw = data.pop("confidence_scores", [])
        confidence_scores = self._parse_confidence(confidence_raw)

        try:
            invoice = InvoiceData.model_validate(data)
        except ValidationError as exc:
            raise RuntimeError(f"Response doesn't match InvoiceData schema: {exc}") from exc

        return ExtractionResult(
            source_file=str(pdf_path),
            page_count=page_count,
            invoice=invoice,
            confidence_scores=confidence_scores,
            extraction_method=method,
        )

    @staticmethod
    def _parse_confidence(raw: list[dict[str, Any]]) -> list[FieldConfidence]:
        """Parse confidence score dicts, tolerating bad entries."""
        scores: list[FieldConfidence] = []
        for entry in raw:
            try:
                scores.append(FieldConfidence(
                    field=entry["field"],
                    confidence=ConfidenceLevel(entry["confidence"]),
                    reason=entry.get("reason"),
                ))
            except (KeyError, ValueError):
                continue
        return scores
