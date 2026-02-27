"""Command-line entry point for sweetroll.

Usage:
  sweetroll                     Open the editor with an empty buffer
  sweetroll FILE                Open FILE for editing
  sweetroll ext list            List extensions available in the registry
  sweetroll ext install NAME    Install an extension by registry name
  sweetroll ext install URL     Install an extension from a direct URL
"""

import sys

from sweetroll.loader import load_extensions
from sweetroll import run

_EXT_USAGE = """\
Usage:
  sweetroll ext list                   List extensions available in the registry
  sweetroll ext install [name]         Install an extension by registry name
  sweetroll ext install [url]          Install an extension from a direct zip URL
"""


def _cmd_ext(args):
    """Handle the 'sweetroll ext' subcommands (list, install)."""
    if not args:
        print(_EXT_USAGE, end="")
        sys.exit(0)

    sub = args[0]

    if sub == "list":
        from sweetroll.registry import cmd_list
        cmd_list()
    elif sub == "install":
        if len(args) < 2:
            print("sweetroll ext install: missing [name] or [url]", file=sys.stderr)
            sys.exit(1)
        from sweetroll.registry import cmd_install
        cmd_install(args[1])
    else:
        print(f"sweetroll ext: unknown subcommand '{sub}'\n", file=sys.stderr)
        print(_EXT_USAGE, end="", file=sys.stderr)
        sys.exit(1)


def main():
    args = sys.argv[1:]

    # If the first argument is "ext", handle extension management commands
    if args and args[0] == "ext":
        _cmd_ext(args[1:])
        return

    # Otherwise, load extensions and open the editor
    load_extensions()

    if args:
        path = args[0]
    else:
        path = None

    run(path)


if __name__ == "__main__":
    main()
