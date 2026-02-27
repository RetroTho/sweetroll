"""Extension discovery and loading from ~/.sweetroll/extensions/."""

import importlib.util
import json
import sys
from pathlib import Path

from sweetroll.editor import register_hook

_USER_DIR = Path.home() / ".sweetroll" / "extensions"
_DEPS_FILE = Path.home() / ".sweetroll" / "deps.json"


def _load_extension(ext_dir: Path):
    """Load a single extension from a directory, calling its setup(register_hook)."""
    init_file = ext_dir / "__init__.py"
    if not init_file.exists():
        print(f"sweetroll: warning: {ext_dir.name}/ has no __init__.py, skipping", file=sys.stderr)
        return
    module_name = f"sweetroll_ext_{ext_dir.name}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, init_file)
        if spec is None or spec.loader is None:
            raise ImportError("could not create module spec")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        sys.modules.pop(module_name, None)
        print(f"sweetroll: warning: error loading {ext_dir.name}: {e}", file=sys.stderr)
        return
    setup = getattr(mod, "setup", None)
    if not callable(setup):
        print(f"sweetroll: warning: {ext_dir.name} has no setup() function, skipping", file=sys.stderr)
        return
    try:
        setup(register_hook)
    except Exception as e:
        print(f"sweetroll: warning: {ext_dir.name}.setup() failed: {e}", file=sys.stderr)


def _load_single_file(py_file: Path):
    """Load a single-file extension (.py) from the user extensions dir."""
    module_name = f"sweetroll_ext_{py_file.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError("could not create module spec")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        sys.modules.pop(module_name, None)
        print(f"sweetroll: warning: error loading {py_file.name}: {e}", file=sys.stderr)
        return
    setup = getattr(mod, "setup", None)
    if not callable(setup):
        print(f"sweetroll: warning: {py_file.name} has no setup() function, skipping", file=sys.stderr)
        return
    try:
        setup(register_hook)
    except Exception as e:
        print(f"sweetroll: warning: {py_file.stem}.setup() failed: {e}", file=sys.stderr)


def _read_deps() -> dict[str, list[str]]:
    """Read the local dependency manifest (~/.sweetroll/deps.json)."""
    if not _DEPS_FILE.exists():
        return {}
    try:
        return json.loads(_DEPS_FILE.read_text())
    except Exception:
        return {}


def _sort_by_deps(names: list[str], deps: dict[str, list[str]]) -> list[str]:
    """Sort extension names so dependencies come before dependents.

    Extensions not mentioned in *deps* keep their original (alphabetical) order
    and are placed after all dependency-tracked extensions.
    """
    order: list[str] = []
    visited: set[str] = set()

    def walk(name: str):
        if name in visited:
            return
        visited.add(name)
        for dep in deps.get(name, []):
            if dep in names:
                walk(dep)
        order.append(name)

    # First, resolve all extensions that appear in the dependency graph.
    for name in names:
        if name in deps:
            walk(name)

    # Then, append the rest in their original (sorted) order.
    for name in names:
        if name not in visited:
            order.append(name)

    return order


def load_extensions():
    """Load all extensions from ~/.sweetroll/extensions/ in dependency order."""
    if not _USER_DIR.is_dir():
        return

    # Discover installed extensions.
    entries: dict[str, Path] = {}
    for entry in sorted(_USER_DIR.iterdir()):
        if entry.name.startswith((".", "__")):
            continue
        if entry.is_dir():
            entries[entry.name] = entry
        elif entry.suffix == ".py":
            entries[entry.stem] = entry

    # Sort so dependencies load first.
    deps = _read_deps()
    load_order = _sort_by_deps(list(entries.keys()), deps)

    for name in load_order:
        path = entries[name]
        if path.is_dir():
            _load_extension(path)
        else:
            _load_single_file(path)
