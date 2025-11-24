"""Tests for ghsearch CLI."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

import pytest
import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ghsearch.cli import (
    resolve_auth_token,
    resolve_api_base,
    build_headers,
    load_config,
    merge_repos_config_cli,
    merge_code_config_cli,
    merge_commits_config_cli,
    simplify_repos,
    simplify_code_results,
    simplify_commits_results,
    aggregate_commits_by_repo,
    apply_filters,
    apply_sorting,
    group_by_language,
)


class TestResolveAuthToken:
    """Tests for resolve_auth_token function."""
    
    def test_cli_token_takes_precedence(self):
        """CLI token should take highest precedence."""
        assert resolve_auth_token("cli_token", "config_token") == "cli_token"
    
    def test_config_token_used_when_no_cli(self):
        """Config token should be used when CLI token is None."""
        assert resolve_auth_token(None, "config_token") == "config_token"
    
    def test_env_token_used_when_no_cli_or_config(self, env_vars):
        """Environment variable token should be used when CLI/config are None."""
        env_vars(GHSEARCH_TOKEN="env_token")
        assert resolve_auth_token(None, None) == "env_token"
    
    def test_github_token_fallback(self, env_vars):
        """GITHUB_TOKEN should be used as fallback."""
        env_vars(GITHUB_TOKEN="github_token")
        assert resolve_auth_token(None, None) == "github_token"
    
    def test_returns_none_when_no_token(self, env_vars):
        """Should return None when no token is available."""
        # Clear all env vars
        for key in ["GHSEARCH_TOKEN", "GITHUB_TOKEN"]:
            env_vars(**{key: None})
        assert resolve_auth_token(None, None) is None


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
        env_vars(GHSEARCH_API_BASE="env_base")
        assert resolve_api_base(None, None) == "env_base"
    
    def test_default_api_base(self, env_vars):
        """Should default to GitHub API base."""
        for key in ["GHSEARCH_API_BASE"]:
            env_vars(**{key: None})
        assert resolve_api_base(None, None) == "https://api.github.com"


class TestBuildHeaders:
    """Tests for build_headers function."""
    
    def test_headers_with_token(self):
        """Headers should include Authorization when token is provided."""
        headers = build_headers("test_token")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_token"
        assert headers["Accept"] == "application/vnd.github.mercy-preview+json, application/vnd.github.cloak-preview+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert headers["User-Agent"] == "ghsearch-cli"
    
    def test_headers_without_token(self):
        """Headers should not include Authorization when token is None."""
        headers = build_headers(None)
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github.mercy-preview+json, application/vnd.github.cloak-preview+json"


class TestLoadConfig:
    """Tests for load_config function."""
    
    def test_load_yaml_config(self, temp_config_file, sample_config):
        """Should load YAML config file."""
        with open(temp_config_file, 'w') as f:
            yaml.dump(sample_config, f)
        
        config = load_config(temp_config_file)
        assert config["repos"]["api_base"] == "https://api.github.com"
    
    def test_load_json_config(self, temp_config_file, sample_config):
        """Should load JSON config file."""
        with open(temp_config_file, 'w') as f:
            json.dump(sample_config, f)
        
        config = load_config(temp_config_file)
        assert config["repos"]["api_base"] == "https://api.github.com"
    
    def test_nonexistent_file_returns_empty_dict(self):
        """Should return empty dict for nonexistent file."""
        config = load_config("/nonexistent/path.yml")
        assert config == {}
    
    def test_default_config_path(self, monkeypatch, sample_config):
        """Should load from default config path if no path provided."""
        home = Path.home()
        config_path = home / ".ghsearch.yml"
        
        with open(config_path, 'w') as f:
            yaml.dump(sample_config, f)
        
        try:
            config = load_config(None)
            assert config["repos"]["api_base"] == "https://api.github.com"
        finally:
            if config_path.exists():
                config_path.unlink()


class TestSimplifyRepos:
    """Tests for simplify_repos function."""
    
    def test_simplify_repos(self):
        """Should simplify repository items."""
        items = [{
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "description": "Test repo",
            "stargazers_count": 100,
            "watchers_count": 50,
            "forks_count": 25,
            "language": "Python",
            "archived": False,
            "fork": False,
            "topics": ["test"],
            "license": {"key": "mit", "name": "MIT", "spdx_id": "MIT"},
            "default_branch": "main",
            "pushed_at": "2023-01-01T00:00:00Z",
            "updated_at": "2023-01-01T00:00:00Z",
            "created_at": "2023-01-01T00:00:00Z",
            "score": 1.0,
        }]
        
        simplified = simplify_repos(items)
        assert len(simplified) == 1
        assert simplified[0]["full_name"] == "owner/repo"
        assert simplified[0]["stars"] == 100
        assert simplified[0]["language"] == "Python"
    
    def test_simplify_repos_no_license(self):
        """Should handle repos without license."""
        items = [{
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "description": "Test repo",
            "stargazers_count": 0,
            "watchers_count": 0,
            "forks_count": 0,
            "language": None,
            "archived": False,
            "fork": False,
            "topics": [],
            "license": None,
            "default_branch": "main",
            "pushed_at": None,
            "updated_at": None,
            "created_at": None,
            "score": 1.0,
        }]
        
        simplified = simplify_repos(items)
        assert simplified[0]["license"] is None


class TestApplyFilters:
    """Tests for apply_filters function."""
    
    def test_filter_by_min_stars(self):
        """Should filter repositories by minimum stars."""
        repos = [
            {"full_name": "repo1", "stars": 100},
            {"full_name": "repo2", "stars": 50},
            {"full_name": "repo3", "stars": 200},
        ]
        
        filtered = apply_filters(repos, min_stars=100)
        assert len(filtered) == 2
        assert all(r["stars"] >= 100 for r in filtered)
    
    def test_filter_by_language(self):
        """Should filter repositories by language."""
        repos = [
            {"full_name": "repo1", "language": "Python"},
            {"full_name": "repo2", "language": "JavaScript"},
            {"full_name": "repo3", "language": "Python"},
        ]
        
        filtered = apply_filters(repos, language="Python")
        assert len(filtered) == 2
        assert all(r["language"] == "Python" for r in filtered)
    
    def test_filter_case_insensitive(self):
        """Language filter should be case-insensitive."""
        repos = [
            {"full_name": "repo1", "language": "Python"},
            {"full_name": "repo2", "language": "python"},
        ]
        
        filtered = apply_filters(repos, language="PYTHON")
        assert len(filtered) == 2


class TestApplySorting:
    """Tests for apply_sorting function."""
    
    def test_sort_by_stars_desc(self):
        """Should sort by stars in descending order."""
        repos = [
            {"full_name": "repo1", "stars": 50},
            {"full_name": "repo2", "stars": 100},
            {"full_name": "repo3", "stars": 25},
        ]
        
        sorted_repos = apply_sorting(repos, sort_by="stars", sort_direction="desc")
        assert sorted_repos[0]["stars"] == 100
        assert sorted_repos[-1]["stars"] == 25
    
    def test_sort_by_stars_asc(self):
        """Should sort by stars in ascending order."""
        repos = [
            {"full_name": "repo1", "stars": 50},
            {"full_name": "repo2", "stars": 100},
            {"full_name": "repo3", "stars": 25},
        ]
        
        sorted_repos = apply_sorting(repos, sort_by="stars", sort_direction="asc")
        assert sorted_repos[0]["stars"] == 25
        assert sorted_repos[-1]["stars"] == 100


class TestGroupByLanguage:
    """Tests for group_by_language function."""
    
    def test_group_repos_by_language(self):
        """Should group repositories by language."""
        repos = [
            {"full_name": "repo1", "language": "Python"},
            {"full_name": "repo2", "language": "JavaScript"},
            {"full_name": "repo3", "language": "Python"},
            {"full_name": "repo4", "language": None},
        ]
        
        groups = group_by_language(repos)
        assert len(groups["Python"]) == 2
        assert len(groups["JavaScript"]) == 1
        assert len(groups[None]) == 1


class TestAggregateCommitsByRepo:
    """Tests for aggregate_commits_by_repo function."""
    
    def test_aggregate_commits(self):
        """Should aggregate commits by repository."""
        items = [
            {"repository_full_name": "owner/repo1", "repository_html_url": "https://github.com/owner/repo1"},
            {"repository_full_name": "owner/repo1", "repository_html_url": "https://github.com/owner/repo1"},
            {"repository_full_name": "owner/repo2", "repository_html_url": "https://github.com/owner/repo2"},
        ]
        
        aggregated = aggregate_commits_by_repo(items)
        assert len(aggregated) == 2
        repo1 = next(r for r in aggregated if r["repository_full_name"] == "owner/repo1")
        assert repo1["total_number_of_commits"] == 2
        repo2 = next(r for r in aggregated if r["repository_full_name"] == "owner/repo2")
        assert repo2["total_number_of_commits"] == 1


class TestMergeConfigCli:
    """Tests for merge config functions."""
    
    def test_merge_repos_config_cli(self, sample_config):
        """Should merge repos config correctly."""
        merged = merge_repos_config_cli(
            sample_config,
            cli_api_base=None,
            cli_token=None,
            query=None,
            per_page=None,
            max_pages=None,
            min_stars=None,
            language=None,
            sort_by=None,
            sort_direction=None,
            group_by_language=None,
            top_n=None,
            cli_verify_tls=None,
        )
        
        assert merged["api_base"] == "https://api.github.com"
        assert merged["token"] == "test_token"
        assert merged["query"] == "test query"
        assert merged["per_page"] == 30
    
    def test_merge_code_config_cli(self, sample_config):
        """Should merge code config correctly."""
        merged = merge_code_config_cli(
            sample_config,
            cli_api_base=None,
            cli_token=None,
            query=None,
            per_page=None,
            max_pages=None,
            repo=None,
            language=None,
            path=None,
            cli_verify_tls=None,
        )
        
        assert merged["api_base"] == "https://api.github.com"
        assert merged["token"] == "test_token"
    
    def test_merge_commits_config_cli(self, sample_config):
        """Should merge commits config correctly."""
        merged = merge_commits_config_cli(
            sample_config,
            cli_api_base=None,
            cli_token=None,
            query=None,
            per_page=None,
            max_pages=None,
            repo=None,
            author=None,
            committer=None,
            stats=None,
            cli_verify_tls=None,
        )
        
        assert merged["api_base"] == "https://api.github.com"
        assert merged["token"] == "test_token"

