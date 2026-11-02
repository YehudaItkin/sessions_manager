"""Harmless executable used by launch contract tests."""

import json
import os
import sys
from pathlib import Path


def main():
    output = os.environ.get("SESSIONS_TEST_RECEIPT")
    if output:
        Path(output).write_text(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}))
    return int(os.environ.get("SESSIONS_TEST_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
