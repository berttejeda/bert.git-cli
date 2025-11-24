"""Pytest configuration and shared fixtures."""
import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        yield f.name
    # Cleanup
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture
def sample_config():
    """Sample config dictionary."""
    return {
        "repos": {
            "api_base": "https://api.github.com",
            "token": "test_token",
            "query": "test query",
            "per_page": 30,
        },
        "code": {
            "api_base": "https://api.github.com",
            "token": "test_token",
        },
        "commits": {
            "api_base": "https://api.github.com",
            "token": "test_token",
        },
        "ghpr": {
            "api_base": "https://api.github.com",
            "token": "test_token",
            "owner": "testowner",
            "repo": "testrepo",
        },
    }


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for testing."""
    with patch('requests.Session.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 0,
            "incomplete_results": False,
            "items": [],
        }
        mock_response.links = {}
        mock_response.text = ""
        mock_get.return_value = mock_response
        yield mock_get


@pytest.fixture
def mock_httpx_get():
    """Mock httpx.AsyncClient.get for testing."""
    with patch('httpx.AsyncClient.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 0,
            "incomplete_results": False,
            "items": [],
        }
        mock_response.links = {}
        mock_response.text = ""
        mock_get.return_value = mock_response
        yield mock_get


@pytest.fixture
def mock_requests_post():
    """Mock requests.post for testing."""
    with patch('requests.request') as mock_request:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "html_url": "https://github.com/test"}
        mock_response.text = ""
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        yield mock_request


@pytest.fixture
def env_vars(monkeypatch):
    """Fixture to set environment variables."""
    def _set_env(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setenv(key, value)
    return _set_env

