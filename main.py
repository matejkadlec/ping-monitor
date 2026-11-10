#!/usr/bin/env python3
"""
Ping Monitor entry point.
"""

import sys


def main() -> int:
    try:
        from src.app import run
    except ImportError as error:
        from src.ui.win32 import message_box

        message_box(
            "Ping Monitor",
            "Ping Monitor could not start because a dependency is missing:\n\n"
            f"{error}\n\nPlease run setup.bat and try again.",
        )
        return 1
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
