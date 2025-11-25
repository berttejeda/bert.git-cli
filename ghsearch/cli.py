from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
import requests
import typer
import yaml

# Import version - avoid circular import by importing directly
try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:
    try:
        from importlib_metadata import version, PackageNotFoundError
    except ImportError:
        PackageNotFoundError = Exception
        def version(package_name):
            raise PackageNotFoundError

try:
    __version__ = version("bt-ghcli")
except (PackageNotFoundError, Exception):
    # Package not installed, fall back to reading from pyproject.toml
    import re
    from pathlib import Path
    
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            __version__ = match.group(1)
        else:
            __version__ = "0.0.0"
    else:
        __version__ = "0.0.0"

app = typer.Typer(help="GitHub / GitHub Enterprise search CLI tool")


def print_debug_info(
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    debug: bool = False,
) -> None:
    """
    Print debug information about the API request and generate equivalent curl command.
    """
    if not debug:
        return
    
    print("\n" + "=" * 80, file=sys.stderr)
    print("DEBUG: API Request Details", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Method: {method}", file=sys.stderr)
    print(f"URL: {url}", file=sys.stderr)
    
    if params:
        full_url = f"{url}?{urlencode(params)}"
        print(f"Full URL: {full_url}", file=sys.stderr)
    else:
        full_url = url
    
    print("\nHeaders:", file=sys.stderr)
    sanitized_headers = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            # Show only first few chars of token for security
            if value.startswith("Bearer "):
                token = value[7:]
                sanitized_value = f"Bearer {token[:8]}..." if len(token) > 8 else value
            else:
                sanitized_value = value[:20] + "..." if len(value) > 20 else value
            print(f"  {key}: {sanitized_value}", file=sys.stderr)
            sanitized_headers[key] = sanitized_value
        else:
            print(f"  {key}: {value}", file=sys.stderr)
            sanitized_headers[key] = value
    
    if json_data:
        print("\nRequest Body (JSON):", file=sys.stderr)
        print(json.dumps(json_data, indent=2), file=sys.stderr)
    
    if params:
        print("\nQuery Parameters:", file=sys.stderr)
        for key, value in params.items():
            print(f"  {key}: {value}", file=sys.stderr)
    
    # Generate curl command
    print("\n" + "-" * 80, file=sys.stderr)
    print("Equivalent curl command:", file=sys.stderr)
    print("-" * 80, file=sys.stderr)
    
    curl_parts = ["curl", "-X", method]
    
    # Add headers
    for key, value in headers.items():
        curl_parts.extend(["-H", f"{key}: {value}"])
    
    # Add JSON data
    if json_data:
        json_str = json.dumps(json_data)
        curl_parts.extend(["-d", json_str])
        curl_parts.append("-H")
        curl_parts.append("Content-Type: application/json")
    
    # Add URL with params
    curl_parts.append(shlex.quote(full_url))
    
    curl_cmd = " \\\n  ".join(curl_parts)
    print(curl_cmd, file=sys.stderr)
    print("=" * 80 + "\n", file=sys.stderr)


def resolve_auth_token(cli_token: Optional[str], config_token: Optional[str]) -> Optional[str]:
    """
    Determine which auth token to use based on CLI, config, or environment.
    """
    if cli_token:
        return cli_token
    if config_token:
        return config_token
    env_token = os.environ.get("GHSEARCH_TOKEN")
    if env_token:
        return env_token
    return os.environ.get("GITHUB_TOKEN")


def resolve_api_base(cli_api_base: Optional[str], config_api_base: Optional[str]) -> str:
    """
    Determine the API base URL using precedence: CLI > config > env > default.
    """
    if cli_api_base:
        return cli_api_base
    if config_api_base:
        return config_api_base
    env_base = os.environ.get("GHSEARCH_API_BASE")
    if env_base:
        return env_base
    return "https://api.github.com"


def build_headers(token: Optional[str]) -> Dict[str, str]:
    """
    Build GitHub API headers with optional Bearer token.
    Includes media types for topics (mercy-preview) and commits (cloak-preview).
    """
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github.mercy-preview+json, application/vnd.github.cloak-preview+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ghsearch-cli",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def load_config(path: Optional[str]) -> Dict[str, Any]:
    """
    Load CLI configuration from YAML or JSON. Returns an empty dict on failure.
    """
    config_path = Path(path).expanduser() if path else Path.home() / ".ghsearch.yml"
    if not config_path.exists():
        if path:
            print(f"[ghsearch] Config file not found: {config_path}", file=sys.stderr)
        return {}
    data = config_path.read_text(encoding="utf-8")
    if not data.strip():
        return {}
    for loader in (yaml.safe_load, json.loads):
        try:
            parsed = loader(data)
        except Exception:
            continue
        if parsed is None:
            return {}
        if isinstance(parsed, dict):
            return parsed
        break
    print(f"[ghsearch] Failed to parse config file: {config_path}", file=sys.stderr)
    return {}


def merge_repos_config_cli(
    config: Dict[str, Any],
    *,
    cli_api_base: Optional[str],
    cli_token: Optional[str],
    query: Optional[str],
    per_page: Optional[int],
    max_pages: Optional[int],
    min_stars: Optional[int],
    language: Optional[str],
    sort_by: Optional[str],
    sort_direction: Optional[str],
    group_by_language: Optional[bool],
    top_n: Optional[int],
    cli_verify_tls: Optional[bool],
) -> Dict[str, Any]:
    subcfg = config.get("repos", {}) if isinstance(config.get("repos"), dict) else {}
    merged: Dict[str, Any] = {}
    merged["api_base"] = resolve_api_base(cli_api_base, subcfg.get("api_base"))
    merged["token"] = resolve_auth_token(cli_token, subcfg.get("token"))
    merged["query"] = query or subcfg.get("query") or "topic:astro topic:template"
    merged["per_page"] = per_page or subcfg.get("per_page") or 50
    merged["max_pages"] = max_pages or subcfg.get("max_pages") or 3
    merged["min_stars"] = min_stars if min_stars is not None else subcfg.get("min_stars")
    merged["language"] = language or subcfg.get("language")
    merged["sort_by"] = sort_by or subcfg.get("sort_by")
    merged["sort_direction"] = sort_direction or subcfg.get("sort_direction") or "desc"
    merged["group_by_language"] = (
        group_by_language if group_by_language is not None else subcfg.get("group_by_language", False)
    )
    merged["top_n"] = top_n if top_n is not None else subcfg.get("top_n")
    merged["verify_tls"] = cli_verify_tls if cli_verify_tls is not None else subcfg.get("verify_tls", True)
    return merged


def merge_code_config_cli(
    config: Dict[str, Any],
    *,
    cli_api_base: Optional[str],
    cli_token: Optional[str],
    query: Optional[str],
    per_page: Optional[int],
    max_pages: Optional[int],
    repo: Optional[str],
    language: Optional[str],
    path: Optional[str],
    cli_verify_tls: Optional[bool],
) -> Dict[str, Any]:
    subcfg = config.get("code", {}) if isinstance(config.get("code"), dict) else {}
    merged: Dict[str, Any] = {}
    merged["api_base"] = resolve_api_base(cli_api_base, subcfg.get("api_base"))
    merged["token"] = resolve_auth_token(cli_token, subcfg.get("token"))
    merged["query"] = query or subcfg.get("query") or "test"
    merged["per_page"] = per_page or subcfg.get("per_page") or 50
    merged["max_pages"] = max_pages or subcfg.get("max_pages") or 3
    merged["repo"] = repo or subcfg.get("repo")
    merged["language"] = language or subcfg.get("language")
    merged["path"] = path or subcfg.get("path")
    merged["verify_tls"] = cli_verify_tls if cli_verify_tls is not None else subcfg.get("verify_tls", True)
    return merged


def merge_commits_config_cli(
    config: Dict[str, Any],
    *,
    cli_api_base: Optional[str],
    cli_token: Optional[str],
    query: Optional[str],
    per_page: Optional[int],
    max_pages: Optional[int],
    repo: Optional[str],
    author: Optional[str],
    committer: Optional[str],
    stats: Optional[bool],
    cli_verify_tls: Optional[bool],
) -> Dict[str, Any]:
    subcfg = config.get("commits", {}) if isinstance(config.get("commits"), dict) else {}
    merged: Dict[str, Any] = {}
    merged["api_base"] = resolve_api_base(cli_api_base, subcfg.get("api_base"))
    merged["token"] = resolve_auth_token(cli_token, subcfg.get("token"))
    merged["query"] = query or subcfg.get("query") or "fix"
    merged["per_page"] = per_page or subcfg.get("per_page") or 50
    merged["max_pages"] = max_pages or subcfg.get("max_pages") or 3
    merged["repo"] = repo or subcfg.get("repo")
    merged["author"] = author or subcfg.get("author")
    merged["committer"] = committer or subcfg.get("committer")
    merged["stats"] = stats if stats is not None else subcfg.get("stats", False)
    merged["verify_tls"] = cli_verify_tls if cli_verify_tls is not None else subcfg.get("verify_tls", True)
    return merged


def search_repositories(
    api_base: str,
    headers: Dict[str, str],
    query: str,
    per_page: int = 50,
    max_pages: int = 3,
    timeout: int = 10,
    debug: bool = False,
    verify: bool = True,
) -> Dict[str, Any]:
    url = api_base.rstrip("/") + "/search/repositories"
    items: List[Dict[str, Any]] = []
    total_count = None
    incomplete_results = False
    session = requests.Session()
    for page in range(1, max_pages + 1):
        params = {"q": query, "per_page": per_page, "page": page}
        if debug and page == 1:
            print_debug_info("GET", url, headers, params=params, debug=debug)
        try:
            resp = session.get(url, headers=headers, params=params, timeout=timeout, verify=verify)
        except requests.RequestException as exc:
            print(f"[ghsearch] Request error: {exc}", file=sys.stderr)
            break
        if resp.status_code >= 400:
            body = resp.text[:500]
            print(f"[ghsearch] HTTP {resp.status_code} error: {body}", file=sys.stderr)
            break
        payload = resp.json()
        if total_count is None:
            total_count = payload.get("total_count")
            incomplete_results = bool(payload.get("incomplete_results"))
        page_items = payload.get("items") or []
        if not page_items:
            break
        items.extend(page_items)
        if len(items) >= 1000 or "next" not in resp.links:
            break
    session.close()
    return {
        "query": query,
        "total_count": total_count if total_count is not None else len(items),
        "incomplete_results": incomplete_results,
        "items": items[:1000],
    }


def simplify_repos(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    simplified: List[Dict[str, Any]] = []
    for item in items:
        license_info = item.get("license")
        if isinstance(license_info, dict):
            license_entry = {
                "key": license_info.get("key"),
                "name": license_info.get("name"),
                "spdx_id": license_info.get("spdx_id"),
            }
        else:
            license_entry = None
        simplified.append(
            {
                "full_name": item.get("full_name"),
                "html_url": item.get("html_url"),
                "description": item.get("description"),
                "stars": item.get("stargazers_count", 0),
                "watchers": item.get("watchers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language"),
                "archived": item.get("archived", False),
                "fork": item.get("fork", False),
                "topics": item.get("topics") or [],
                "license": license_entry,
                "default_branch": item.get("default_branch"),
                "pushed_at": item.get("pushed_at"),
                "updated_at": item.get("updated_at"),
                "created_at": item.get("created_at"),
                "score": item.get("score"),
            }
        )
    return simplified


def apply_filters(
    repos: List[Dict[str, Any]],
    min_stars: Optional[int] = None,
    language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filtered = repos
    if min_stars is not None:
        filtered = [r for r in filtered if (r.get("stars") or 0) >= min_stars]
    if language:
        lang_lower = language.lower()
        filtered = [r for r in filtered if (r.get("language") or "").lower() == lang_lower]
    return filtered


def apply_sorting(
    repos: List[Dict[str, Any]],
    sort_by: Optional[str] = None,
    sort_direction: str = "desc",
) -> List[Dict[str, Any]]:
    reverse = sort_direction.lower() != "asc"
    if sort_by not in {None, "stars", "forks", "updated", "created"}:
        return repos
    if sort_by == "stars":
        key_fn = lambda r: r.get("stars") or 0
    elif sort_by == "forks":
        key_fn = lambda r: r.get("forks") or 0
    elif sort_by == "updated":
        key_fn = lambda r: r.get("updated_at") or ""
    elif sort_by == "created":
        key_fn = lambda r: r.get("created_at") or ""
    else:
        return repos if not reverse else list(reversed(repos))
    return sorted(repos, key=key_fn, reverse=reverse)


def group_by_language(repos: List[Dict[str, Any]]) -> Dict[Optional[str], List[Dict[str, Any]]]:
    groups: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for repo in repos:
        lang = repo.get("language")
        groups.setdefault(lang, []).append(repo)
    return groups


async def search_code_async(
    api_base: str,
    headers: Dict[str, str],
    query: str,
    per_page: int = 50,
    max_pages: int = 3,
    timeout: int = 10,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    path: Optional[str] = None,
    debug: bool = False,
    verify: bool = True,
) -> Dict[str, Any]:
    url = api_base.rstrip("/") + "/search/code"
    final_query = query
    if repo:
        final_query += f" repo:{repo}"
    if language:
        final_query += f" language:{language}"
    if path:
        final_query += f" path:{path}"
    items: List[Dict[str, Any]] = []
    total_count = None
    incomplete_results = False
    async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
        for page in range(1, max_pages + 1):
            params = {"q": final_query, "per_page": per_page, "page": page}
            if debug and page == 1:
                print_debug_info("GET", url, headers, params=params, debug=debug)
            try:
                resp = await client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                print(f"[ghsearch] HTTPX error: {exc}", file=sys.stderr)
                break
            if resp.status_code >= 400:
                body = resp.text[:500]
                print(f"[ghsearch] HTTP {resp.status_code} error: {body}", file=sys.stderr)
                break
            payload = resp.json()
            if total_count is None:
                total_count = payload.get("total_count")
                incomplete_results = bool(payload.get("incomplete_results"))
            page_items = payload.get("items") or []
            if not page_items:
                break
            items.extend(page_items)
            if len(items) >= 1000 or "next" not in resp.links:
                break
    return {
        "query": final_query,
        "total_count": total_count if total_count is not None else len(items),
        "incomplete_results": incomplete_results,
        "items": items[:1000],
    }


async def search_commits_async(
    api_base: str,
    headers: Dict[str, str],
    query: str,
    per_page: int = 50,
    max_pages: int = 3,
    timeout: int = 10,
    repo: Optional[str] = None,
    author: Optional[str] = None,
    committer: Optional[str] = None,
    debug: bool = False,
    verify: bool = True,
) -> Dict[str, Any]:
    url = api_base.rstrip("/") + "/search/commits"
    final_query = query
    if repo:
        final_query += f" repo:{repo}"
    if author:
        final_query += f" author:{author}"
    if committer:
        final_query += f" committer:{committer}"
    items: List[Dict[str, Any]] = []
    total_count = None
    incomplete_results = False
    async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
        for page in range(1, max_pages + 1):
            params = {"q": final_query, "per_page": per_page, "page": page}
            if debug and page == 1:
                print_debug_info("GET", url, headers, params=params, debug=debug)
            try:
                resp = await client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                print(f"[ghsearch] HTTPX error: {exc}", file=sys.stderr)
                break
            if resp.status_code >= 400:
                body = resp.text[:500]
                print(f"[ghsearch] HTTP {resp.status_code} error: {body}", file=sys.stderr)
                break
            payload = resp.json()
            if total_count is None:
                total_count = payload.get("total_count")
                incomplete_results = bool(payload.get("incomplete_results"))
            page_items = payload.get("items") or []
            if not page_items:
                break
            items.extend(page_items)
            if len(items) >= 1000 or "next" not in resp.links:
                break
    return {
        "query": final_query,
        "total_count": total_count if total_count is not None else len(items),
        "incomplete_results": incomplete_results,
        "items": items[:1000],
    }


def simplify_code_results(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    simplified: List[Dict[str, Any]] = []
    for item in items:
        repo = item.get("repository") or {}
        simplified.append(
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "sha": item.get("sha"),
                "html_url": item.get("html_url"),
                "repository_full_name": repo.get("full_name"),
                "repository_html_url": repo.get("html_url"),
            }
        )
    return simplified


def simplify_commits_results(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    simplified: List[Dict[str, Any]] = []
    for item in items:
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        committer = commit.get("committer") or {}
        repo = item.get("repository") or {}
        simplified.append(
            {
                "sha": item.get("sha"),
                "html_url": item.get("html_url"),
                "url": item.get("url"),
                "message": commit.get("message", "").split("\n")[0] if commit.get("message") else None,
                "author_name": author.get("name"),
                "author_email": author.get("email"),
                "author_date": author.get("date"),
                "committer_name": committer.get("name"),
                "committer_email": committer.get("email"),
                "committer_date": committer.get("date"),
                "repository_full_name": repo.get("full_name"),
                "repository_html_url": repo.get("html_url"),
                "score": item.get("score"),
            }
        )
    return simplified


def build_repos_report(
    raw: Dict[str, Any],
    repos: List[Dict[str, Any]],
    group_by_lang: bool,
    top_n: Optional[int],
    min_stars: Optional[int],
    language: Optional[str],
    sort_by: Optional[str],
    sort_direction: str,
    api_base: str,
) -> Dict[str, Any]:
    processed = repos
    if top_n and top_n > 0:
        processed = processed[:top_n]
    report: Dict[str, Any] = {
        "query": raw["query"],
        "api_base": api_base,
        "total_count": raw.get("total_count"),
        "incomplete_results": raw.get("incomplete_results"),
        "returned": len(processed),
        "filters": {"min_stars": min_stars, "language": language},
        "sorting": {"sort_by": sort_by, "sort_direction": sort_direction},
    }
    if group_by_lang:
        report["group_by"] = "language"
        report["groups"] = group_by_language(processed)
    else:
        report["repositories"] = processed
    return report


def build_code_report(
    raw: Dict[str, Any],
    items: List[Dict[str, Any]],
    api_base: str,
    repo: Optional[str],
    language: Optional[str],
    path: Optional[str],
) -> Dict[str, Any]:
    return {
        "query": raw["query"],
        "api_base": api_base,
        "total_count": raw.get("total_count"),
        "incomplete_results": raw.get("incomplete_results"),
        "returned": len(items),
        "filters": {"repo": repo, "language": language, "path": path},
        "results": items,
    }


def aggregate_commits_by_repo(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregate commits by repository and calculate statistics.
    """
    repo_stats: Dict[str, Dict[str, Any]] = {}
    for item in items:
        repo_name = item.get("repository_full_name")
        repo_url = item.get("repository_html_url")
        if not repo_name:
            continue
        if repo_name not in repo_stats:
            repo_stats[repo_name] = {
                "repository_full_name": repo_name,
                "repository_html_url": repo_url,
                "total_number_of_commits": 0,
            }
        repo_stats[repo_name]["total_number_of_commits"] += 1
    return list(repo_stats.values())


def build_commits_report(
    raw: Dict[str, Any],
    items: List[Dict[str, Any]],
    api_base: str,
    repo: Optional[str],
    author: Optional[str],
    committer: Optional[str],
    stats: bool = False,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "query": raw["query"],
        "api_base": api_base,
        "total_count": raw.get("total_count"),
        "incomplete_results": raw.get("incomplete_results"),
        "returned": len(items),
        "filters": {"repo": repo, "author": author, "committer": committer},
    }
    if stats:
        report["repositories"] = aggregate_commits_by_repo(items)
    else:
        report["commits"] = items
    return report


def validate_sort_options(sort_by: Optional[str], sort_direction: str) -> Tuple[bool, str]:
    valid_sort_by = {None, "stars", "forks", "updated", "created"}
    if sort_by not in valid_sort_by:
        return False, "sort-by must be one of: stars, forks, updated, created"
    if sort_direction.lower() not in {"asc", "desc"}:
        return False, "sort-direction must be 'asc' or 'desc'"
    return True, ""


@app.command(
    "repos",
    help="Search GitHub repositories. Examples:\n\n"
    "  # Search for repositories with topics\n"
    "  ghsearch repos --query 'topic:astro topic:template'\n\n"
    "  # Find Python repos with minimum stars\n"
    "  ghsearch repos --query 'language:python' --min-stars 100 --sort-by stars\n\n"
    "  # Search with grouping by language\n"
    "  ghsearch repos --query 'topic:cli' --group-by-language --top-n 20\n\n"
    "  # Use GitHub Enterprise\n"
    "  ghsearch repos --api-base 'https://github.company.com/api/v3' --query 'org:myorg'\n\n"
    "  # Search with config file\n"
    "  ghsearch repos --config ~/.ghsearch.yml",
)
def repos_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", help="GitHub token for authentication"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query"),
    per_page: Optional[int] = typer.Option(None, "--per-page", help="Results per page (max 100)"),
    max_pages: Optional[int] = typer.Option(None, "--max-pages", help="Maximum pages to fetch"),
    min_stars: Optional[int] = typer.Option(None, "--min-stars", help="Minimum stars filter"),
    language: Optional[str] = typer.Option(None, "--language", help="Language filter"),
    sort_by: Optional[str] = typer.Option(None, "--sort-by", help="Sort by field"),
    sort_direction: str = typer.Option("desc", "--sort-direction", help="Sort direction"),
    group_by_language: bool = typer.Option(False, "--group-by-language", help="Group results by language"),
    no_group_by_language: bool = typer.Option(False, "--no-group-by-language", help="Do not group results by language"),
    top_n: Optional[int] = typer.Option(None, "--top-n", help="Limit results to top N"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
) -> None:
    cfg = load_config(config)
    # Determine group_by_language value: --no-group-by-language takes precedence
    if no_group_by_language:
        group_by_language_value: Optional[bool] = False
    elif group_by_language:
        group_by_language_value = True
    else:
        group_by_language_value = None
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_repos_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        query=query,
        per_page=per_page,
        max_pages=max_pages,
        min_stars=min_stars,
        language=language,
        sort_by=sort_by,
        sort_direction=sort_direction,
        group_by_language=group_by_language_value,
        top_n=top_n,
        cli_verify_tls=final_verify_tls,
    )
    valid, message = validate_sort_options(merged["sort_by"], merged["sort_direction"])
    if not valid:
        typer.echo(f"[ghsearch] {message}", err=True)
        raise typer.Exit(code=1)
    headers = build_headers(merged["token"])
    raw = search_repositories(
        merged["api_base"],
        headers,
        merged["query"],
        merged["per_page"],
        merged["max_pages"],
        debug=debug,
        verify=merged["verify_tls"],
    )
    simplified = simplify_repos(raw["items"])
    filtered = apply_filters(simplified, merged["min_stars"], merged["language"])
    sorted_repos = apply_sorting(filtered, merged["sort_by"], merged["sort_direction"])
    report = build_repos_report(
        raw,
        sorted_repos,
        merged["group_by_language"],
        merged["top_n"],
        merged["min_stars"],
        merged["language"],
        merged["sort_by"],
        merged["sort_direction"],
        merged["api_base"],
    )
    yaml.safe_dump(report, stream=sys.stdout, sort_keys=False, default_flow_style=False, allow_unicode=True)


@app.command("code")
def code_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", help="GitHub token for authentication"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query"),
    per_page: Optional[int] = typer.Option(None, "--per-page", help="Results per page (max 100)"),
    max_pages: Optional[int] = typer.Option(None, "--max-pages", help="Maximum pages to fetch"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Repository filter"),
    language: Optional[str] = typer.Option(None, "--language", help="Language filter"),
    path: Optional[str] = typer.Option(None, "--path", help="Path filter"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
) -> None:
    cfg = load_config(config)
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_code_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        query=query,
        per_page=per_page,
        max_pages=max_pages,
        repo=repo,
        language=language,
        path=path,
        cli_verify_tls=final_verify_tls,
    )
    headers = build_headers(merged["token"])
    raw = asyncio.run(
        search_code_async(
            merged["api_base"],
            headers,
            merged["query"],
            merged["per_page"],
            merged["max_pages"],
            repo=merged["repo"],
            language=merged["language"],
            path=merged["path"],
            debug=debug,
            verify=merged["verify_tls"],
        )
    )
    simplified = simplify_code_results(raw["items"])
    report = build_code_report(
        raw,
        simplified,
        merged["api_base"],
        merged["repo"],
        merged["language"],
        merged["path"],
    )
    yaml.safe_dump(report, stream=sys.stdout, sort_keys=False, default_flow_style=False, allow_unicode=True)


@app.command(
    "commits",
    help="Search GitHub commits. Examples:\n\n"
    "  # Search for commits with a query\n"
    "  ghsearch commits --query 'fix bug'\n\n"
    "  # Search commits in a specific repository\n"
    "  ghsearch commits --query 'performance' --repo 'owner/repo'\n\n"
    "  # Search commits by author\n"
    "  ghsearch commits --query 'refactor' --author 'username'\n\n"
    "  # Search commits by committer\n"
    "  ghsearch commits --query 'merge' --committer 'username'\n\n"
    "  # Output repository statistics\n"
    "  ghsearch commits --query 'fix' --stats\n\n"
    "  # Use GitHub Enterprise\n"
    "  ghsearch commits --api-base 'https://github.company.com/api/v3' --query 'security'\n\n"
    "  # Search with config file\n"
    "  ghsearch commits --config ~/.ghsearch.yml",
)
def commits_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", help="GitHub token for authentication"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query"),
    per_page: Optional[int] = typer.Option(None, "--per-page", help="Results per page (max 100)"),
    max_pages: Optional[int] = typer.Option(None, "--max-pages", help="Maximum pages to fetch"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Repository filter (owner/repo)"),
    author: Optional[str] = typer.Option(None, "--author", help="Author filter (username or email)"),
    committer: Optional[str] = typer.Option(None, "--committer", help="Committer filter (username or email)"),
    stats: bool = typer.Option(False, "--stats", help="Output repository statistics instead of individual commits"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
) -> None:
    cfg = load_config(config)
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_commits_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        query=query,
        per_page=per_page,
        max_pages=max_pages,
        repo=repo,
        author=author,
        committer=committer,
        stats=stats,
        cli_verify_tls=final_verify_tls,
    )
    headers = build_headers(merged["token"])
    raw = asyncio.run(
        search_commits_async(
            merged["api_base"],
            headers,
            merged["query"],
            merged["per_page"],
            merged["max_pages"],
            repo=merged["repo"],
            author=merged["author"],
            committer=merged["committer"],
            debug=debug,
            verify=merged["verify_tls"],
        )
    )
    simplified = simplify_commits_results(raw["items"])
    report = build_commits_report(
        raw,
        simplified,
        merged["api_base"],
        merged["repo"],
        merged["author"],
        merged["committer"],
        stats=merged["stats"],
    )
    yaml.safe_dump(report, stream=sys.stdout, sort_keys=False, default_flow_style=False, allow_unicode=True)


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
) -> None:
    """GitHub / GitHub Enterprise search CLI tool."""
    if version:
        typer.echo(f"ghsearch version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    """Entry point for ghsearch CLI."""
    app()

