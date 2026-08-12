"""Shared pytest fixtures.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _ha_harness_usable() -> bool:
    """Return whether the Home Assistant test harness can actually run here.

    Being *installed* is not enough, and neither is importing the plugin package — its top-level
    module imports cleanly even where it cannot work. What decides it is whether **Home Assistant
    itself** imports on this platform, so that is what gets tested.

    **The harness does not work on Windows.** `homeassistant.runner` imports `fcntl`, which is
    POSIX-only, so on Windows every test in the suite errors during collection with a
    `ModuleNotFoundError` that names neither Home Assistant nor the plugin.

    The repository-hygiene tests need none of it, so they run anywhere — a fast local loop.
    Tests that genuinely need `hass` must run on Linux: WSL2, a container, or CI. See
    `docs/development/README.md`.
    """
    try:
        import homeassistant.runner  # noqa: F401
        import pytest_homeassistant_custom_component  # noqa: F401
    except ImportError:
        return False
    return True


HA_TEST_HARNESS = _ha_harness_usable()

# There used to be a `_stub_integration_package()` here, registering `jfl_alarm` as a bare module so
# that `jfl_alarm.protocol` could be imported without executing the integration's Home
# Assistant-importing `__init__`. The codec moved to the `pyjfl` package on PyPI (ADR-0019), so the
# problem it solved no longer exists: `import pyjfl` is an ordinary import of an installed
# distribution, with no relationship to `custom_components/` at all.

if HA_TEST_HARNESS:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
        """Load `custom_components/` in every test.

        Home Assistant does not look at custom integrations in the test harness unless this fixture
        is requested. Making it autouse means no test can silently pass by testing nothing.
        """
        yield


def load_frame_bytes(name: str) -> bytes:
    """Return the bytes of the captured frame stored in `tests/fixtures/<name>`.

    The fixtures are real bytes observed on the wire against a live Active 32 Duo, stored as hex.
    Whitespace and `#` comments are stripped, so a fixture may be written either as one continuous
    string or spaced out and annotated. They are the project's ground truth: a parser that disagrees
    with a fixture is wrong, the fixture is not.
    """
    text = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    stripped = "".join(
        token for line in text.splitlines() for token in line.split("#", 1)[0].split()
    )
    return bytes.fromhex(stripped)


@pytest.fixture
def load_frame() -> Callable[[str], bytes]:
    """Return a loader for the captured frames in `tests/fixtures/`."""
    return load_frame_bytes


# The Home Assistant harness cannot even be imported on Windows, so the tests that need it are kept
# in their own directory and skipped at collection time rather than at run time. See
# `_ha_harness_usable` above and `docs/development/README.md`.
collect_ignore = [] if HA_TEST_HARNESS else ["integration"]
