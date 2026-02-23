"""Extension discovery and loading from ~/.sweetroll/extensions/."""

import importlib.util
import sys
from pathlib import Path

from sweetroll.editor import register_hook

_USER_DIR = Path.home() / ".sweetroll" / "extensions"


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


def load_extensions():
    """Load all extensions from ~/.sweetroll/extensions/."""
    if not _USER_DIR.is_dir():
        return
    for entry in sorted(_USER_DIR.iterdir()):
        if entry.name.startswith((".", "__")):
            continue
        if entry.is_dir():
            _load_extension(entry)
        elif entry.suffix == ".py":
            _load_single_file(entry)
