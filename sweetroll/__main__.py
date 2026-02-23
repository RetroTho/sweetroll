"""Entry point: sweetroll [file] | sweetroll ext <subcommand>"""

import sys

from sweetroll.loader import load_extensions
from sweetroll import run

_EXT_USAGE = """\
Usage:
  sweetroll ext list                   List extensions available in the registry
  sweetroll ext install [name]         Install an extension by registry name
  sweetroll ext install [url]          Install an extension from a direct zip URL
"""


def _cmd_ext(args: list[str]):
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

    if args and args[0] == "ext":
        _cmd_ext(args[1:])
        return

    load_extensions()
    path = args[0] if args else None
    run(path)


if __name__ == "__main__":
    main()
