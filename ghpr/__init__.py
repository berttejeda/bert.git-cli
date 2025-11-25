"""
ghpr provides a GitHub/GitHub Enterprise Pull Request management CLI.
"""
from .cli import app

__all__ = ["app", "__version__"]

try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:
    # Python < 3.8
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



