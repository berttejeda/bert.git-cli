"""Tests for ghpr CLI."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ghpr.cli import (
    resolve_auth_token,
    resolve_api_base,
    build_headers,
    load_config,
    merge_config_cli,
    get_proxies,
)


class TestResolveAuthToken:
    """Tests for resolve_auth_token function."""
    
    def test_cli_token_takes_precedence(self):
        """CLI token should take highest precedence."""
        assert resolve_auth_token("cli_token", "config_token") == "cli_token"
    
    def test_config_token_used_when_no_cli(self):
        """Config token should be used when CLI token is None."""
        assert resolve_auth_token(None, "config_token") == "config_token"
    
    def test_env_token_used(self, env_vars):
        """Environment variable token should be used."""
        env_vars(GHPR_TOKEN="env_token")
        assert resolve_auth_token(None, None) == "env_token"
    
    def test_ghe_token_fallback(self, env_vars):
        """GHE_TOKEN should be used as fallback."""
        env_vars(GHE_TOKEN="ghe_token")
        assert resolve_auth_token(None, None) == "ghe_token"
    
    def test_github_token_fallback(self, env_vars):
        """GITHUB_TOKEN should be used as final fallback."""
        env_vars(GITHUB_TOKEN="github_token")
        assert resolve_auth_token(None, None) == "github_token"


class TestResolveApiBase:
    """Tests for resolve_api_base function."""
    
    def test_cli_api_base_takes_precedence(self):
        """CLI API base should take highest precedence."""
        assert resolve_api_base("cli_base", "config_base") == "cli_base"
    
    def test_config_api_base_used_when_no_cli(self):
        """Config API base should be used when CLI is None."""
        assert resolve_api_base(None, "config_base") == "config_base"
    
    def test_env_api_base_used(self, env_vars):
        """Environment variable API base should be used."""
        env_vars(GHPR_API_BASE="env_base")
        assert resolve_api_base(None, None) == "env_base"
    
    def test_ghe_url_conversion(self, env_vars):
        """GHE_URL should be converted to API base."""
        env_vars(GHE_URL="https://github.company.com")
        result = resolve_api_base(None, None)
        assert result == "https://github.company.com/api/v3"
    
    def test_ghe_url_with_trailing_slash(self, env_vars):
        """GHE_URL with trailing slash should be handled correctly."""
        env_vars(GHE_URL="https://github.company.com/")
        result = resolve_api_base(None, None)
        assert result == "https://github.company.com/api/v3"
    
    def test_default_api_base(self, env_vars, monkeypatch):
        """Should default to GitHub API base."""
        # Clear all env vars that could provide an API base
        for key in ["GHPR_API_BASE", "GHE_URL"]:
            monkeypatch.delenv(key, raising=False)
        assert resolve_api_base(None, None) == "https://api.github.com"


class TestBuildHeaders:
    """Tests for build_headers function."""
    
    def test_headers_with_token(self):
        """Headers should include Authorization when token is provided."""
        headers = build_headers("test_token")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_token"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert headers["User-Agent"] == "ghpr-cli"
    
    def test_headers_without_token(self):
        """Headers should not include Authorization when token is None."""
        headers = build_headers(None)
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github+json"


class TestLoadConfig:
    """Tests for load_config function."""
    
    def test_load_yaml_config(self, temp_config_file, sample_config):
        """Should load YAML config file."""
        with open(temp_config_file, 'w') as f:
            yaml.dump(sample_config, f)
        
        config = load_config(temp_config_file)
        assert config["ghpr"]["api_base"] == "https://api.github.com"
    
    def test_load_json_config(self, temp_config_file, sample_config):
        """Should load JSON config file."""
        with open(temp_config_file, 'w') as f:
            json.dump(sample_config, f)
        
        config = load_config(temp_config_file)
        assert config["ghpr"]["api_base"] == "https://api.github.com"
    
    def test_nonexistent_file_returns_empty_dict(self):
        """Should return empty dict for nonexistent file."""
        config = load_config("/nonexistent/path.yml")
        assert config == {}


class TestGetProxies:
    """Tests for get_proxies function."""
    
    def test_get_proxies_with_proxy(self):
        """Should return proxy dict when proxy is provided."""
        proxies = get_proxies("socks5://127.0.0.1:2180")
        assert proxies["http"] == "socks5://127.0.0.1:2180"
        assert proxies["https"] == "socks5://127.0.0.1:2180"
    
    def test_get_proxies_without_proxy(self):
        """Should return empty dict when proxy is None."""
        proxies = get_proxies(None)
        assert proxies == {}


class TestMergeConfigCli:
    """Tests for merge_config_cli function."""
    
    def test_merge_config_cli(self, sample_config):
        """Should merge config correctly."""
        merged = merge_config_cli(
            sample_config,
            cli_api_base=None,
            cli_token=None,
            cli_owner=None,
            cli_repo=None,
            cli_proxy=None,
            cli_verify_tls=None,
        )
        
        assert merged["api_base"] == "https://api.github.com"
        assert merged["token"] == "test_token"
        assert merged["owner"] == "testowner"
        assert merged["repo"] == "testrepo"
    
    def test_merge_config_cli_with_cli_overrides(self, sample_config):
        """CLI values should override config values."""
        merged = merge_config_cli(
            sample_config,
            cli_api_base="https://custom.api.com",
            cli_token="cli_token",
            cli_owner="cli_owner",
            cli_repo="cli_repo",
            cli_proxy=None,
            cli_verify_tls=None,
        )
        
        assert merged["api_base"] == "https://custom.api.com"
        assert merged["token"] == "cli_token"
        assert merged["owner"] == "cli_owner"
        assert merged["repo"] == "cli_repo"

