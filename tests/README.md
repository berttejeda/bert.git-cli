# Running Tests

## Setup

Install the development dependencies:

```bash
pip install -e ".[dev]"
```

## Running Tests

Run all tests:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=ghsearch --cov=ghpr --cov-report=term
```

Run specific test file:

```bash
pytest tests/test_ghsearch.py
```

Run specific test:

```bash
pytest tests/test_ghsearch.py::TestResolveAuthToken::test_cli_token_takes_precedence
```

Run with verbose output:

```bash
pytest -v
```

## Test Structure

- `tests/test_ghsearch.py` - Tests for the `ghsearch` CLI
- `tests/test_ghpr.py` - Tests for the `ghpr` CLI
- `tests/conftest.py` - Shared fixtures and configuration

