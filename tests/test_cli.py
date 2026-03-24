"""Tests for CLI argument parsing and basic behavior."""

from __future__ import annotations

from click.testing import CliRunner

from invoice_ai.cli import cli


class TestCliBasics:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "invoice-ai" in result.output

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Extract structured data from invoices" in result.output

    def test_extract_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "--format" in result.output
        assert "--verbose" in result.output

    def test_extract_nonexistent_path(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "/nonexistent/file.pdf"])
        assert result.exit_code != 0

    def test_extract_format_choices(self):
        runner = CliRunner()
        # Invalid format should fail
        result = runner.invoke(cli, ["extract", "--format", "xml", "/tmp/dummy.pdf"])
        assert result.exit_code != 0
        assert "xml" in result.output.lower() or "invalid" in result.output.lower()
