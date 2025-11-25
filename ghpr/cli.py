from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
import typer

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

app = typer.Typer(help="GitHub / GitHub Enterprise Pull Request management CLI tool")


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
    env_token = os.environ.get("GHPR_TOKEN")
    if env_token:
        return env_token
    env_token = os.environ.get("GHE_TOKEN")
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
    env_base = os.environ.get("GHPR_API_BASE")
    if env_base:
        return env_base
    env_base = os.environ.get("GHE_URL")
    if env_base:
        # Convert GHE_URL format to API base if needed
        if not env_base.endswith("/api/v3"):
            if env_base.endswith("/"):
                env_base = env_base.rstrip("/")
            env_base = f"{env_base}/api/v3"
        return env_base
    return "https://api.github.com"


def build_headers(token: Optional[str]) -> Dict[str, str]:
    """
    Build GitHub API headers with optional Bearer token.
    """
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ghpr-cli",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def load_config(path: Optional[str]) -> Dict[str, Any]:
    """
    Load CLI configuration from YAML or JSON. Returns an empty dict on failure.
    """
    config_path = Path(path).expanduser() if path else Path.home() / ".ghpr.yml"
    if not config_path.exists():
        if path:
            print(f"[ghpr] Config file not found: {config_path}", file=sys.stderr)
        return {}
    data = config_path.read_text(encoding="utf-8")
    if not data.strip():
        return {}
    try:
        import yaml
        parsed = yaml.safe_load(data)
    except Exception:
        try:
            parsed = json.loads(data)
        except Exception:
            print(f"[ghpr] Failed to parse config file: {config_path}", file=sys.stderr)
            return {}
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def merge_config_cli(
    config: Dict[str, Any],
    *,
    cli_api_base: Optional[str],
    cli_token: Optional[str],
    cli_owner: Optional[str],
    cli_repo: Optional[str],
    cli_proxy: Optional[str],
    cli_verify_tls: Optional[bool],
) -> Dict[str, Any]:
    """
    Merge CLI options with config file values.
    """
    subcfg = config.get("ghpr", {}) if isinstance(config.get("ghpr"), dict) else {}
    merged: Dict[str, Any] = {}
    merged["api_base"] = resolve_api_base(cli_api_base, subcfg.get("api_base"))
    merged["token"] = resolve_auth_token(cli_token, subcfg.get("token"))
    merged["owner"] = cli_owner or subcfg.get("owner") or os.environ.get("GHE_PROJECT")
    merged["repo"] = cli_repo or subcfg.get("repo") or os.environ.get("GHE_REPO_NAME")
    merged["proxy"] = cli_proxy or subcfg.get("proxy")
    merged["verify_tls"] = cli_verify_tls if cli_verify_tls is not None else subcfg.get("verify_tls", True)
    return merged


def get_proxies(proxy: Optional[str]) -> Dict[str, str]:
    """
    Build proxies dict for requests.
    """
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def make_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    json_data: Optional[Dict[str, Any]] = None,
    proxies: Optional[Dict[str, str]] = None,
    verify: bool = True,
    debug: bool = False,
) -> requests.Response:
    """
    Make an HTTP request with error handling.
    """
    proxies = proxies or {}
    if debug:
        print_debug_info(method, url, headers, json_data=json_data, debug=debug)
    response = None
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            proxies=proxies,
            verify=verify,
        )
        response.raise_for_status()
        return response
    except requests.exceptions.ProxyError as e:
        print(f"[ghpr] Error: Could not connect to proxy. Ensure PySocks is installed and the proxy is running.", file=sys.stderr)
        print(f"[ghpr] Details: {e}", file=sys.stderr)
        raise typer.Exit(code=1)
    except requests.exceptions.ConnectionError as e:
        print(f"[ghpr] Error: Could not connect to the GitHub API at {url}.", file=sys.stderr)
        print(f"[ghpr] Details: {e}", file=sys.stderr)
        raise typer.Exit(code=1)
    except requests.exceptions.HTTPError as e:
        if response is not None:
            print(f"[ghpr] Error: HTTP request failed with status code {response.status_code}.", file=sys.stderr)
            print(f"[ghpr] Response: {response.text[:500]}", file=sys.stderr)
        else:
            print(f"[ghpr] Error: HTTP request failed.", file=sys.stderr)
        print(f"[ghpr] Details: {e}", file=sys.stderr)
        raise typer.Exit(code=1)
    except requests.exceptions.RequestException as e:
        print(f"[ghpr] An unexpected error occurred during the request: {e}", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command(
    "create",
    help="Create a new Pull Request. Examples:\n\n"
    "  # Create a PR with title and body\n"
    "  ghpr create --title 'Fix bug' --body 'This fixes the issue' --head feature-branch --base main\n\n"
    "  # Create a draft PR\n"
    "  ghpr create --title 'WIP: Feature' --head feature --base main --draft\n\n"
    "  # Create PR with labels\n"
    "  ghpr create --title 'Feature' --head feature --base main --label bug --label enhancement",
)
def create_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GitHub token for authentication"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Repository owner/organization"),
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Repository name"),
    title: str = typer.Option(..., "--title", help="PR title"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="PR body/description"),
    head: str = typer.Option(..., "--head", help="Branch to merge from"),
    base: str = typer.Option("main", "--base", help="Branch to merge into"),
    draft: bool = typer.Option(False, "--draft", help="Create as draft PR"),
    label: Optional[List[str]] = typer.Option(None, "--label", help="Labels to add (can be used multiple times)"),
    proxy: Optional[str] = typer.Option(None, "--proxy", "-x", help="SOCKS5h proxy address"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
) -> None:
    cfg = load_config(config)
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        cli_owner=owner,
        cli_repo=repo,
        cli_proxy=proxy,
        cli_verify_tls=final_verify_tls,
    )
    
    if not merged["owner"] or not merged["repo"]:
        typer.echo("[ghpr] Error: --owner and --repo are required", err=True)
        raise typer.Exit(code=1)
    
    if not merged["token"]:
        typer.echo("[ghpr] Error: --token is required", err=True)
        raise typer.Exit(code=1)
    
    api_url = f"{merged['api_base'].rstrip('/')}/repos/{merged['owner']}/{merged['repo']}/pulls"
    headers = build_headers(merged["token"])
    proxies = get_proxies(merged["proxy"])
    
    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
    }
    if body:
        payload["body"] = body
    if draft:
        payload["draft"] = True
    if label:
        payload["labels"] = label
    
    typer.echo(f"Creating PR: {title} ({head} -> {base})")
    response = make_request("POST", api_url, headers, json_data=payload, proxies=proxies, verify=merged["verify_tls"], debug=debug)
    
    result = response.json()
    typer.echo(f"✓ Pull Request created successfully!")
    typer.echo(f"  PR #{result.get('number')}: {result.get('html_url')}")
    typer.echo(f"  State: {result.get('state')}")
    if result.get("draft"):
        typer.echo(f"  Draft: Yes")


@app.command(
    "approve",
    help="Approve a Pull Request. Examples:\n\n"
    "  # Approve a PR\n"
    "  ghpr approve --pr-number 123\n\n"
    "  # Approve with a comment\n"
    "  ghpr approve --pr-number 123 --comment 'Looks good!'",
)
def approve_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GitHub token for authentication"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Repository owner/organization"),
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Repository name"),
    pr_number: int = typer.Option(..., "--pr-number", "-pr", help="Pull Request number"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Optional approval comment"),
    proxy: Optional[str] = typer.Option(None, "--proxy", "-x", help="SOCKS5h proxy address"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
) -> None:
    cfg = load_config(config)
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        cli_owner=owner,
        cli_repo=repo,
        cli_proxy=proxy,
        cli_verify_tls=final_verify_tls,
    )
    
    if not merged["owner"] or not merged["repo"]:
        typer.echo("[ghpr] Error: --owner and --repo are required", err=True)
        raise typer.Exit(code=1)
    
    if not merged["token"]:
        typer.echo("[ghpr] Error: --token is required", err=True)
        raise typer.Exit(code=1)
    
    api_url = f"{merged['api_base'].rstrip('/')}/repos/{merged['owner']}/{merged['repo']}/pulls/{pr_number}/reviews"
    headers = build_headers(merged["token"])
    proxies = get_proxies(merged["proxy"])
    
    payload: Dict[str, Any] = {"event": "APPROVE"}
    if comment:
        payload["body"] = comment
    
    typer.echo(f"Approving PR #{pr_number} in {merged['owner']}/{merged['repo']}...")
    response = make_request("POST", api_url, headers, json_data=payload, proxies=proxies, verify=merged["verify_tls"], debug=debug)
    
    result = response.json()
    typer.echo(f"✓ Pull Request approved successfully!")
    typer.echo(f"  Review ID: {result.get('id')}")
    typer.echo(f"  Review URL: {result.get('html_url')}")
    typer.echo(f"  State: {result.get('state')}")


@app.command(
    "comment",
    help="Add a comment to a Pull Request. Examples:\n\n"
    "  # Add a review comment\n"
    "  ghpr comment --pr-number 123 --comment 'Great work!' --type review\n\n"
    "  # Add a conversational comment\n"
    "  ghpr comment --pr-number 123 --comment 'Thanks for the PR!' --type issue",
)
def comment_command(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Override API base URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GitHub token for authentication"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Repository owner/organization"),
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Repository name"),
    pr_number: int = typer.Option(..., "--pr-number", "-pr", help="Pull Request number"),
    comment: str = typer.Option(..., "--comment", help="Comment text"),
    comment_type: str = typer.Option("review", "--type", help="Comment type: 'review' or 'issue'"),
    proxy: Optional[str] = typer.Option(None, "--proxy", "-x", help="SOCKS5h proxy address"),
    verify_tls: bool = typer.Option(True, "--verify-tls", help="Enable TLS verification (default: True)"),
    no_verify_tls: bool = typer.Option(False, "--no-verify-tls", help="Disable TLS verification"),
    debug: bool = typer.Option(False, "--debug", help="Show API request details and equivalent curl command"),
) -> None:
    cfg = load_config(config)
    # If --no-verify-tls is set, override verify_tls to False
    final_verify_tls = False if no_verify_tls else verify_tls
    merged = merge_config_cli(
        cfg,
        cli_api_base=api_base,
        cli_token=token,
        cli_owner=owner,
        cli_repo=repo,
        cli_proxy=proxy,
        cli_verify_tls=final_verify_tls,
    )
    
    if not merged["owner"] or not merged["repo"]:
        typer.echo("[ghpr] Error: --owner and --repo are required", err=True)
        raise typer.Exit(code=1)
    
    if not merged["token"]:
        typer.echo("[ghpr] Error: --token is required", err=True)
        raise typer.Exit(code=1)
    
    if comment_type not in ["review", "issue"]:
        typer.echo("[ghpr] Error: --type must be 'review' or 'issue'", err=True)
        raise typer.Exit(code=1)
    
    headers = build_headers(merged["token"])
    proxies = get_proxies(merged["proxy"])
    
    if comment_type == "review":
        api_url = f"{merged['api_base'].rstrip('/')}/repos/{merged['owner']}/{merged['repo']}/pulls/{pr_number}/reviews"
        payload = {"body": comment, "event": "COMMENT"}
        comment_label = "review comment"
    else:
        api_url = f"{merged['api_base'].rstrip('/')}/repos/{merged['owner']}/{merged['repo']}/issues/{pr_number}/comments"
        payload = {"body": comment}
        comment_label = "comment"
    
    typer.echo(f"Adding {comment_label} to PR #{pr_number} in {merged['owner']}/{merged['repo']}...")
    response = make_request("POST", api_url, headers, json_data=payload, proxies=proxies, verify=merged["verify_tls"], debug=debug)
    
    result = response.json()
    typer.echo(f"✓ {comment_label.capitalize()} added successfully!")
    typer.echo(f"  ID: {result.get('id')}")
    typer.echo(f"  URL: {result.get('html_url')}")


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
) -> None:
    """GitHub / GitHub Enterprise Pull Request management CLI tool."""
    if version:
        typer.echo(f"ghpr version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    """Entry point for ghpr CLI."""
    app()

