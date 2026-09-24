"""Ensure the project root is importable when pytest is invoked directly.

`python -m pytest` puts the CWD on sys.path automatically, but a bare `pytest`
call does not — this keeps `pytest` and `make test` equivalent.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
