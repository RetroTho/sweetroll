"""Extension registry: fetch, list, and install extensions from a remote index.

The registry is a JSON file hosted on GitHub that lists available extensions,
their descriptions, download URLs, and dependencies. This module handles
fetching that registry, listing what's available, resolving dependencies,
and downloading/installing extensions into ~/.sweetroll/extensions/.
"""

import json
import sys
import urllib.request
import zipfile
from io import BytesIO

from sweetroll.loader import _USER_DIR, _DEPS_FILE

REGISTRY_URL = "https://raw.githubusercontent.com/RetroTho/sweetroll-registry/main/registry.json"


def _fetch_registry():
    """Download and parse the registry JSON from GitHub.

    Exits the program with an error message if the download fails.
    """
    try:
        with urllib.request.urlopen(REGISTRY_URL, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as err:
        print(f"sweetroll: error fetching registry: {err}", file=sys.stderr)
        sys.exit(1)


def _installed_names():
    """Return a set of extension names that are already installed locally.

    Checks ~/.sweetroll/extensions/ for directories and .py files.
    """
    if not _USER_DIR.is_dir():
        return set()

    names = set()
    for entry in _USER_DIR.iterdir():
        if entry.name.startswith((".", "__")):
            continue
        if entry.is_dir():
            names.add(entry.name)
        elif entry.suffix == ".py":
            names.add(entry.stem)
    return names


def cmd_list():
    """Print all extensions available in the registry, with install status."""
    registry = _fetch_registry()
    extensions = registry.get("extensions", {})
    if not extensions:
        print("No extensions listed in registry.")
        return

    installed = _installed_names()
    for name, info in sorted(extensions.items()):
        marker = " [installed]" if name in installed else ""
        print(f"  {name}{marker}")
        desc = info.get("description")
        if desc:
            print(f"    {desc}")
        depends = info.get("depends")
        if depends:
            print(f"    depends: {', '.join(depends)}")


def _resolve_deps(name, extensions, installed):
    """Figure out which extensions need to be installed (in order) for `name`.

    Walks the dependency tree starting from `name`. Skips anything already
    installed. Returns a list of extension names in the order they should
    be installed (dependencies first).

    Uses two sets to detect circular dependencies:
      - "in_progress" tracks the extensions we're currently walking through
        (if we see one again, it's a cycle)
      - "done" tracks extensions we've fully resolved
    """
    order = []
    in_progress = set()
    done = set()

    def collect_deps(ext):
        """Recursively collect all dependencies for `ext`."""
        # Already resolved or already installed — nothing to do
        if ext in done or ext in installed:
            return

        # If we're already in the middle of resolving this extension,
        # that means there's a circular dependency (A needs B needs A)
        if ext in in_progress:
            print(f"sweetroll: circular dependency detected involving '{ext}'",
                  file=sys.stderr)
            sys.exit(1)

        # Make sure this extension actually exists in the registry
        if ext not in extensions:
            print(f"sweetroll: unknown dependency '{ext}'", file=sys.stderr)
            sys.exit(1)

        in_progress.add(ext)

        # Resolve all of this extension's dependencies first
        for dep in extensions[ext].get("depends", []):
            collect_deps(dep)

        in_progress.discard(ext)
        done.add(ext)
        order.append(ext)

    collect_deps(name)
    return order


def _save_deps(name, depends):
    """Update ~/.sweetroll/deps.json after installing an extension.

    Records which extensions `name` depends on, so the loader can sort
    them correctly at startup.
    """
    deps = {}
    if _DEPS_FILE.exists():
        try:
            deps = json.loads(_DEPS_FILE.read_text())
        except Exception:
            pass

    if depends:
        deps[name] = depends
    elif name in deps:
        del deps[name]

    _DEPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DEPS_FILE.write_text(json.dumps(deps, indent=2) + "\n")


def cmd_install(name_or_url):
    """Install an extension by registry name or direct URL."""
    if name_or_url.startswith(("http://", "https://")):
        # Direct URL install (no dependency resolution)
        _install_from_url(name_or_url, name=None)
    else:
        # Registry install: look up the extension and resolve dependencies
        registry = _fetch_registry()
        extensions = registry.get("extensions", {})

        if name_or_url not in extensions:
            print(f"sweetroll: unknown extension '{name_or_url}'", file=sys.stderr)
            sys.exit(1)

        installed = _installed_names()
        to_install = _resolve_deps(name_or_url, extensions, installed)

        for ext_name in to_install:
            info = extensions[ext_name]
            if ext_name != name_or_url:
                print(f"sweetroll: installing dependency '{ext_name}'...")
            _install_from_url(info["url"], name=ext_name)
            _save_deps(ext_name, info.get("depends", []))


def _install_from_url(url, name):
    """Download an extension from `url` and install it.

    Figures out whether it's a single .py file or a zip archive, then
    delegates to the appropriate installer.
    """
    print(f"Downloading {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    except Exception as err:
        print(f"sweetroll: download failed: {err}", file=sys.stderr)
        sys.exit(1)

    if url.rstrip("/").endswith(".py"):
        _install_single_py(data, url, name)
    else:
        _install_zip(data, name)


def _install_single_py(data, url, name):
    """Install a single-file (.py) extension."""
    # Figure out the extension name from the URL filename if not provided
    if name:
        ext_name = name
    else:
        # e.g. "https://example.com/extensions/clipboard.py" -> "clipboard"
        filename = url.rstrip("/").rsplit("/", 1)[-1]
        ext_name = filename[:-3]  # remove ".py"

    dest = _USER_DIR / f"{ext_name}.py"

    if dest.exists():
        print(
            f"sweetroll: '{ext_name}' is already installed. Remove {dest} to reinstall.",
            file=sys.stderr,
        )
        sys.exit(1)

    _USER_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"sweetroll: installed '{ext_name}' -> {dest}")


def _install_zip(data, name):
    """Install a zip-based extension (a directory with __init__.py, etc.)."""
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        print("sweetroll: downloaded file is not a zip archive", file=sys.stderr)
        sys.exit(1)

    # The zip must contain exactly one top-level directory.
    # Find all top-level directory names by looking at file paths in the zip.
    top_dirs = set()
    for filepath in zf.namelist():
        if "/" in filepath:
            top_dir = filepath.split("/")[0]
            top_dirs.add(top_dir)

    if len(top_dirs) != 1:
        print(
            f"sweetroll: zip must contain exactly one top-level directory, "
            f"found: {sorted(top_dirs)}",
            file=sys.stderr,
        )
        sys.exit(1)

    zip_root = next(iter(top_dirs))
    ext_name = name if name else zip_root
    dest = _USER_DIR / ext_name

    if dest.exists():
        print(
            f"sweetroll: '{ext_name}' is already installed. Remove {dest} to reinstall.",
            file=sys.stderr,
        )
        sys.exit(1)

    _USER_DIR.mkdir(parents=True, exist_ok=True)
    dest.mkdir()

    # Extract files, stripping the top-level directory prefix from paths.
    # For example, if the zip contains "clipboard/main.py", we want to
    # extract it as "~/.sweetroll/extensions/clipboard/main.py".
    prefix = zip_root + "/"
    for member in zf.infolist():
        if not member.filename.startswith(prefix):
            continue

        # Get the path relative to the top-level directory
        relative_path = member.filename[len(prefix):]
        if not relative_path:
            continue

        target = dest / relative_path
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member.filename))

    print(f"sweetroll: installed '{ext_name}' -> {dest}")
