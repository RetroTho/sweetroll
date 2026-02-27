"""Extension discovery and loading.

Scans ~/.sweetroll/extensions/ for installed extensions, sorts them so that
dependencies load before the extensions that need them, then dynamically
imports each one and calls its setup() function.

Extensions can be either:
  - A directory with an __init__.py  (package extension)
  - A single .py file               (single-file extension)
"""

# importlib.util lets us import Python files by file path at runtime,
# which is how we load extensions that aren't part of the sweetroll package.
import importlib.util
import json
import sys
from pathlib import Path

from sweetroll.editor import register_hook

# Where user-installed extensions live on disk
_USER_DIR = Path.home() / ".sweetroll" / "extensions"

# Dependency manifest written by "sweetroll ext install"
_DEPS_FILE = Path.home() / ".sweetroll" / "deps.json"


def _import_and_setup(module_name, file_path, display_name):
    """Import a Python file as a module and call its setup(register_hook).

    This is the shared logic used for both directory-based and single-file
    extensions.  If anything goes wrong (bad import, missing setup function,
    setup error), a warning is printed to stderr and the extension is skipped.
    """
    # Step 1: dynamically import the file as a Python module.
    # This is like writing "import some_extension" but for a file path
    # that we only know at runtime.
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError("could not create module spec")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    except Exception as err:
        sys.modules.pop(module_name, None)
        print(f"sweetroll: warning: error loading {display_name}: {err}",
              file=sys.stderr)
        return

    # Step 2: look for a setup() function in the extension
    setup = getattr(mod, "setup", None)
    if not callable(setup):
        print(f"sweetroll: warning: {display_name} has no setup() function, skipping",
              file=sys.stderr)
        return

    # Step 3: call setup so the extension can register its hooks
    try:
        setup(register_hook)
    except Exception as err:
        print(f"sweetroll: warning: {display_name}.setup() failed: {err}",
              file=sys.stderr)


def _load_extension(ext_dir):
    """Load a directory-based extension (one with an __init__.py)."""
    init_file = ext_dir / "__init__.py"
    if not init_file.exists():
        print(f"sweetroll: warning: {ext_dir.name}/ has no __init__.py, skipping",
              file=sys.stderr)
        return
    _import_and_setup(f"sweetroll_ext_{ext_dir.name}", init_file, ext_dir.name)


def _load_single_file(py_file):
    """Load a single-file extension (.py file)."""
    _import_and_setup(f"sweetroll_ext_{py_file.stem}", py_file, py_file.name)


def _read_deps():
    """Read the dependency manifest (~/.sweetroll/deps.json).

    Returns a dict mapping extension names to their list of dependencies,
    or an empty dict if the file doesn't exist or can't be parsed.
    """
    if not _DEPS_FILE.exists():
        return {}
    try:
        return json.loads(_DEPS_FILE.read_text())
    except Exception:
        return {}


def _sort_by_deps(names, deps):
    """Sort extension names so dependencies come before the extensions that need them.

    For example, if "clipboard" depends on "selection", then "selection" must
    appear before "clipboard" in the result.

    Uses a depth-first walk through the dependency graph.  Extensions that
    aren't mentioned in the deps manifest keep their original (alphabetical)
    order and are placed after all dependency-tracked extensions.
    """
    order = []
    visited = set()

    def add_with_deps(name):
        """Add *name* to the order list, but first add all of its dependencies."""
        if name in visited:
            return
        visited.add(name)

        # Recursively add this extension's dependencies first
        for dep in deps.get(name, []):
            if dep in names:
                add_with_deps(dep)

        order.append(name)

    # Phase 1: process extensions that have dependency info
    for name in names:
        if name in deps:
            add_with_deps(name)

    # Phase 2: append the rest in alphabetical order
    for name in names:
        if name not in visited:
            order.append(name)

    return order


def load_extensions():
    """Discover and load all extensions from ~/.sweetroll/extensions/.

    Extensions are loaded in dependency order so that if extension A depends
    on extension B, B is loaded first.
    """
    if not _USER_DIR.is_dir():
        return

    # Step 1: scan the extensions directory to find installed extensions
    entries = {}
    for entry in sorted(_USER_DIR.iterdir()):
        # Skip hidden files and __pycache__ etc.
        if entry.name.startswith((".", "__")):
            continue

        if entry.is_dir():
            entries[entry.name] = entry
        elif entry.suffix == ".py":
            entries[entry.stem] = entry

    # Step 2: sort so dependencies load first
    deps = _read_deps()
    load_order = _sort_by_deps(list(entries.keys()), deps)

    # Step 3: load each extension
    for name in load_order:
        path = entries[name]
        if path.is_dir():
            _load_extension(path)
        else:
            _load_single_file(path)
