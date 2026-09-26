#!/usr/bin/env python3
"""Run the test suite and fail if it shrank or skipped anything.

`make test` only asks "did anything fail", which a shrunken suite answers happily: when
reportlab was missing from the `dev` extra, the parser-robustness module collapsed into a
single module-level skip and the run reported "353 passed, 1 skipped" — 14 tests gone, exit
code 0, and nothing on screen that reads as a problem.

This check treats a skip as a failure and a count below the expected total as a failure, so
a dependency gap or a deleted test file cannot pass as green.

Usage:
    python scripts/check_no_pytest_skips.py [extra pytest args...]

Extra arguments are appended to the pytest command, which is what makes the two failure
paths testable (point it at a subset, or at a directory containing a skipped test).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The suite size. Raise this whenever tests are added; never lower it to make a run pass —
# a drop means tests disappeared, which is the thing this script exists to catch.
EXPECTED_MIN_TESTS = 417

# Failures are reported with the skip reasons so the cause is on screen, not in a log file.
MAX_SKIP_REASONS = 40

# `368 passed, 1 skipped, 4 warnings in 7.2s` — and the looser `= 1 failed, 2 errors` forms.
_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|error|errors|deselected|xfailed|xpassed)\b"
)
_COUNTED: tuple[str, ...] = (
    "passed",
    "failed",
    "skipped",
    "error",
    "deselected",
    "xfailed",
    "xpassed",
)


def _parse_counts(output: str) -> dict[str, int]:
    """Highest count seen per category; pytest repeats the summary on some paths."""
    counts: dict[str, int] = {label: 0 for label in _COUNTED}
    for match in _COUNT_RE.finditer(output):
        number, label = int(match.group(1)), match.group(2)
        key = "error" if label == "errors" else label
        counts[key] = max(counts[key], number)
    return counts


def _skip_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("SKIPPED")]


def main(argv: list[str]) -> int:
    command = [sys.executable, "-m", "pytest", "-q", "-rs", *argv]
    print(f"$ {' '.join(command)}", flush=True)
    proc = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    print(output, flush=True)

    counts = _parse_counts(output)
    passed, skipped = counts["passed"], counts["skipped"]

    failures: list[str] = []

    if skipped:
        reasons = "\n".join(_skip_lines(output)[:MAX_SKIP_REASONS])
        failures.append(
            f"{skipped} test(s) were skipped. A skipped test is not a passing test: in CI it "
            f"means the suite is smaller than it looks.\n{reasons}"
        )

    if counts["failed"] or counts["error"]:
        failures.append(f"{counts['failed']} failed, {counts['error']} error(s)")

    if proc.returncode != 0 and not failures:
        failures.append(f"pytest exited {proc.returncode}")

    if passed < EXPECTED_MIN_TESTS:
        failures.append(
            f"only {passed} tests passed, expected at least {EXPECTED_MIN_TESTS}. Either "
            f"tests were deleted, deselected or silently skipped — or the suite legitimately "
            f"grew and EXPECTED_MIN_TESTS in this script needs raising."
        )

    print("-" * 72)
    print(
        f"passed={passed}  skipped={skipped}  failed={counts['failed']}  "
        f"errors={counts['error']}  deselected={counts['deselected']}  "
        f"minimum={EXPECTED_MIN_TESTS}"
    )

    if failures:
        print("\nTEST-CI FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"TEST-CI OK: {passed} passed, 0 skipped, nothing deselected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
