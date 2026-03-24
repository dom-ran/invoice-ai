# n8n Integration

## Using invoice-ai with n8n

This directory contains an n8n workflow template that integrates invoice-ai into an automated invoice processing pipeline.

### Workflow: Gmail → invoice-ai → Google Sheets

**What it does:**
1. Watches Gmail for emails with PDF attachments
2. Downloads the PDF
3. Calls invoice-ai (running as a local API or via Execute Command node)
4. Writes extracted invoice data to Google Sheets
5. Sends a Slack summary

### Setup
1. Install invoice-ai: `pip install -e .`
2. Start the API server: `invoice-ai serve` (or use Execute Command node in n8n)
3. Import `workflow.json` into your n8n instance
4. Configure credentials (Gmail, Google Sheets, Slack)

### Alternative: Direct Claude API
If you prefer not to run the Python tool, the workflow in `../../../n8n-ai-workflows/workflows/01-ai-invoice-processor/` does the same thing using n8n's HTTP Request node to call Claude API directly.
