# invoice-ai

AI-powered invoice and receipt data extraction using Claude's vision capabilities. Feed it a PDF, get back clean, structured JSON.

**invoice-ai** converts messy invoice PDFs into structured data by sending each page to Claude as an image and parsing the response into validated Pydantic models. It handles scanned documents, multi-page invoices, and handwritten receipts. When image extraction fails (e.g., poppler isn't installed), it falls back to text-based extraction automatically.

## Installation

```bash
# Clone and install from source
git clone https://github.com/dom-ran/invoice-ai.git
cd invoice-ai
pip install -e .

# For development (includes pytest)
pip install -e ".[dev]"
```

### System dependencies

PDF-to-image conversion requires **poppler**:

```bash
# macOS
brew install poppler

# Ubuntu/Debian
sudo apt-get install poppler-utils

# Fedora
sudo dnf install poppler-utils
```

### API key

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Quick Start

```bash
# Extract data from a single invoice
invoice-ai extract invoice.pdf

# Process an entire directory
invoice-ai extract ./invoices/ --output results.json

# Export as CSV (one row per line item)
invoice-ai extract invoice.pdf --format csv --output data.csv

# Verbose mode for debugging
invoice-ai extract invoice.pdf --verbose
```

## CLI Reference

```
Usage: invoice-ai [OPTIONS] COMMAND [ARGS]...

  invoice-ai: Extract structured data from invoices using Claude.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  extract  Extract structured data from a PDF invoice or directory of PDFs.
```

### `extract`

```
Usage: invoice-ai extract [OPTIONS] PATH

  Extract structured data from a PDF invoice or a directory of PDFs.

Options:
  -o, --output TEXT         Write results to this file.
  -f, --format [json|csv]   Output format (default: json).
  -v, --verbose             Enable verbose logging.
  --model TEXT              Override the Claude model to use.
  --api-key TEXT            Anthropic API key (or set ANTHROPIC_API_KEY).
  --help                    Show this message and exit.
```

## Library Usage

You can also use invoice-ai as a Python library:

```python
from invoice_ai.extractor import InvoiceExtractor

extractor = InvoiceExtractor()  # uses ANTHROPIC_API_KEY env var

# Single file
result = extractor.extract("invoice.pdf")
print(result.invoice.vendor_name)
print(result.invoice.total)
print(result.overall_confidence)

# Access line items
for item in result.invoice.line_items:
    print(f"  {item.description}: {item.amount}")

# Batch processing
results = extractor.extract_batch(["inv1.pdf", "inv2.pdf", "inv3.pdf"])

# Export
from invoice_ai.exporters import results_to_json, results_to_csv
json_str = results_to_json(results)
csv_str = results_to_csv(results)
```

## Sample Output

```json
{
  "source_file": "invoices/acme-consulting-2025-01.pdf",
  "page_count": 1,
  "invoice": {
    "vendor_name": "Acme Consulting LLC",
    "vendor_address": "456 Business Ave, Suite 200, San Francisco, CA 94102",
    "invoice_number": "INV-2025-0042",
    "invoice_date": "2025-01-15",
    "due_date": "2025-02-14",
    "line_items": [
      {
        "description": "Professional Consulting Services - January 2025",
        "quantity": 40.0,
        "unit_price": 150.0,
        "amount": 6000.0
      },
      {
        "description": "Travel Expenses (Client Site Visit)",
        "quantity": 1.0,
        "unit_price": 350.0,
        "amount": 350.0
      }
    ],
    "subtotal": 6350.0,
    "tax": 508.0,
    "total": 6858.0,
    "currency": "USD",
    "payment_terms": "Net 30"
  },
  "confidence_scores": [
    {"field": "vendor_name", "confidence": "high", "reason": "Clearly printed in header"},
    {"field": "total", "confidence": "high", "reason": "Clearly stated with currency"}
  ],
  "extraction_method": "vision",
  "overall_confidence": "high"
}
```

## How It Works

1. **PDF to Images** -- Each page of the input PDF is rendered as a PNG using `pdf2image` (backed by poppler).
2. **Claude Vision** -- The page images are sent to Claude's API along with a structured extraction prompt that requests JSON output matching a strict schema.
3. **Validation** -- The JSON response is parsed and validated against Pydantic models (`InvoiceData`, `LineItem`).
4. **Fallback** -- If image conversion fails, the tool extracts raw text with `pdfplumber` and sends that to Claude instead.
5. **Export** -- Results are output as formatted JSON or flattened CSV.

## n8n Integration

This tool integrates with [n8n](https://n8n.io) for workflow automation. See the [`n8n/`](./n8n/) directory for importable workflow templates.

For a complete collection of n8n AI workflow templates, see [n8n-ai-workflows](https://github.com/dom-ran/n8n-ai-workflows).

## Contributing

Contributions are welcome.

```bash
# Setup
git clone https://github.com/dom-ran/invoice-ai.git
cd invoice-ai
pip install -e ".[dev]"

# Run tests
pytest -v

# Run a specific test
pytest tests/test_models.py -v
```

Please open an issue before submitting large changes.

## License

MIT
