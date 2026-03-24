"""PDF handling utilities: page-to-image conversion and text extraction."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str | Path, dpi: int = 200) -> list[Image.Image]:
    """Convert each page of a PDF to a PIL Image.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for rendering. Higher = better quality but larger payload.

    Returns:
        List of PIL Images, one per page.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        RuntimeError: If pdf2image conversion fails.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not pdf_path.suffix.lower() == ".pdf":
        raise ValueError(f"Not a PDF file: {pdf_path}")

    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), dpi=dpi)
        logger.info("Converted %s to %d page image(s)", pdf_path.name, len(images))
        return images
    except Exception as exc:
        raise RuntimeError(
            f"Failed to convert PDF to images: {exc}. "
            "Make sure poppler is installed (brew install poppler / apt install poppler-utils)."
        ) from exc


def image_to_base64(image: Image.Image, format: str = "PNG", max_size: int = 4_000_000) -> str:
    """Encode a PIL Image as a base64 string, resizing if the payload is too large.

    Args:
        image: PIL Image to encode.
        format: Image format (PNG or JPEG).
        max_size: Maximum encoded size in bytes. Images exceeding this are scaled down.

    Returns:
        Base64-encoded string of the image.
    """
    buf = io.BytesIO()
    image.save(buf, format=format)
    encoded = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    # If the encoded image is too large, scale it down iteratively
    scale = 1.0
    while len(encoded) > max_size and scale > 0.2:
        scale *= 0.75
        new_size = (int(image.width * scale), int(image.height * scale))
        resized = image.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format=format)
        encoded = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        logger.debug("Resized image to %s (scale=%.2f), encoded size=%d", new_size, scale, len(encoded))

    return encoded


def extract_text_with_pdfplumber(pdf_path: str | Path) -> str:
    """Extract raw text from a PDF using pdfplumber (fallback method).

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Concatenated text from all pages.
    """
    import pdfplumber

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    pages_text: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages_text.append(text)
            logger.debug("Page %d: extracted %d characters", i + 1, len(text))

    return "\n\n--- Page Break ---\n\n".join(pages_text)


def get_pdf_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    import pdfplumber

    pdf_path = Path(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        return len(pdf.pages)


def find_pdfs(path: str | Path) -> list[Path]:
    """Find all PDF files at the given path.

    If *path* is a single PDF, returns a one-element list.
    If it's a directory, returns all ``*.pdf`` files within it (non-recursive).

    Args:
        path: File or directory path.

    Returns:
        Sorted list of Path objects.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the path is a file but not a PDF.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")
    if p.is_file():
        if p.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {p}")
        return [p]
    if p.is_dir():
        pdfs = sorted(p.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(f"No PDF files found in directory: {p}")
        return pdfs
    raise ValueError(f"Path is neither a file nor a directory: {p}")
