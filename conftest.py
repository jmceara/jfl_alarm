"""Put the repository root on `sys.path` so `custom_components.jfl_alarm` is importable.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>

`tests/integration/` imports the integration by its full dotted path — the same name Home Assistant
uses — and nothing else puts the root on the path. It worked everywhere it was ever run by hand,
because an interactive `python -m pytest` inserts the working directory; it failed on GitHub
Actions, where pytest's `rootdir` is not on `sys.path` and collection died with

    tests/integration/conftest.py:31: ModuleNotFoundError: No module named 'custom_components'

six seconds in, on three consecutive releases, with only `exit code 2` in the annotation.

A root `conftest.py` is the documented fix: pytest imports it before collecting anything, and its
directory is exactly the one that has to be importable. `pythonpath = ["."]` in `pyproject.toml`
would do the same, but only for pytest — `mypy` and any plain `python -c` would still be short a
path, and this file is honest about *why* the entry is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
