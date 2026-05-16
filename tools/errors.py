"""Structured error handling — machine-readable error codes and format."""

import json
import sys
from typing import NoReturn

_EXIT_CODES = {
    "NEO4J_CONNECTION_FAILED": 2,
    "NEO4J_TIMEOUT": 3,
    "CONFIG_MISSING": 4,
    "INVALID_INPUT": 5,
    "GIT_UNAVAILABLE": 6,
    "UNKNOWN": 1,
}


def fail(code: str, detail: str, do_exit: bool = True) -> NoReturn | None:
    """Print structured JSON error to stderr and exit.

    Output: {"error": true, "code": "<CODE>", "detail": "<detail>"}
    """
    msg = json.dumps({"error": True, "code": code, "detail": detail})
    print(msg, file=sys.stderr)
    if do_exit:
        exit_code = _EXIT_CODES.get(code, 1)
        sys.exit(exit_code)
    return None
