"""Extension registry: fetch, list, and install extensions from a remote index."""

import json
import sys
import urllib.request
import zipfile
from io import BytesIO

from sweetroll.loader import _USER_DIR

REGISTRY_URL = "https://raw.githubusercontent.com/sweetroll/registry/main/registry.json"


def _fetch_registry() -> dict:
    try:
        with urllib.request.urlopen(REGISTRY_URL, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"sweetroll: error fetching registry: {e}", file=sys.stderr)
        sys.exit(1)


def _installed_names() -> set[str]:
    if not _USER_DIR.is_dir():
        return set()
    names = set()
    for p in _USER_DIR.iterdir():
        if p.is_dir() and not p.name.startswith((".", "__")):
            names.add(p.name)
        elif p.suffix == ".py" and not p.name.startswith((".", "__")):
            names.add(p.stem)
    return names


def cmd_list():
    """Print extensions available in the registry."""
    registry = _fetch_registry()
    extensions = registry.get("extensions", {})
    if not extensions:
        print("No extensions listed in registry.")
        return
    installed = _installed_names()
    for name, info in sorted(extensions.items()):
        marker = " [installed]" if name in installed else ""
        print(f"  {name}{marker}")
        if desc := info.get("description"):
            print(f"    {desc}")


def cmd_install(name_or_url: str):
    """Install an extension by registry name or direct URL."""
    if name_or_url.startswith(("http://", "https://")):
        _install_from_url(name_or_url, name=None)
    else:
        registry = _fetch_registry()
        info = registry.get("extensions", {}).get(name_or_url)
        if info is None:
            print(f"sweetroll: unknown extension '{name_or_url}'", file=sys.stderr)
            sys.exit(1)
        _install_from_url(info["url"], name=name_or_url)


def _install_from_url(url: str, name: str | None):
    print(f"Downloading {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        print(f"sweetroll: download failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Single-file extension: URL ends with .py
    if url.rstrip("/").endswith(".py"):
        ext_name = name or url.rstrip("/").rsplit("/", 1)[-1][:-3]
        dest = _USER_DIR / f"{ext_name}.py"
        if dest.exists():
            print(
                f"sweetroll: '{ext_name}' is already installed. Remove {dest} to reinstall.",
                file=sys.stderr,
            )
            sys.exit(1)
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"sweetroll: installed '{ext_name}' → {dest}")
        return

    # Zip-based extension
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        print("sweetroll: downloaded file is not a zip archive", file=sys.stderr)
        sys.exit(1)

    top_dirs = {p.split("/")[0] for p in zf.namelist() if "/" in p}
    if len(top_dirs) != 1:
        print(
            f"sweetroll: zip must contain exactly one top-level directory, found: {sorted(top_dirs)}",
            file=sys.stderr,
        )
        sys.exit(1)

    zip_root = next(iter(top_dirs))
    ext_name = name or zip_root
    dest = _USER_DIR / ext_name

    if dest.exists():
        print(
            f"sweetroll: '{ext_name}' is already installed. Remove {dest} to reinstall.",
            file=sys.stderr,
        )
        sys.exit(1)

    _USER_DIR.mkdir(parents=True, exist_ok=True)
    dest.mkdir()

    prefix = zip_root + "/"
    for member in zf.infolist():
        if not member.filename.startswith(prefix):
            continue
        rel = member.filename[len(prefix):]
        if not rel:
            continue
        target = dest / rel
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member.filename))

    print(f"sweetroll: installed '{ext_name}' → {dest}")
