"""Enforce the logging-level rule from AGENTS.md §4.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

The integration this project is based on logs its frame and event traffic at `info`, which floods
the Home Assistant log. That is the behaviour `jfl_alarm` exists partly to avoid, so the rule is
enforced mechanically instead of being left to review: everything about the conversation with the
panel goes to `debug`, and anything louder has to be added to the allowlist below with a reason.

Adding an entry to `ALLOWED_LOUD_CALLS` is a deliberate, reviewable act. Growing it silently is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "custom_components" / "jfl_alarm"

LOUD = {"info", "warning", "error", "exception", "critical", "fatal", "warn"}

# module name -> set of allowed loud levels, each justified here in prose. Adding an entry is a
# deliberate, reviewable act; growing this table silently is not.
ALLOWED_LOUD_CALLS: dict[str, set[str]] = {
    # One line when a panel the user has never seen dials in and is added automatically. It fires
    # once per panel per Home Assistant restart, and it is the answer to "where did that device
    # come from?" — exactly what AGENTS.md §4 reserves `info` for.
    "__init__": {"info"},
    # `warning` once when a panel stops reporting, `info` once when it comes back. Guarded by a
    # flag so a panel that redials every ninety seconds still produces one line per transition and
    # not one per attempt; `test_availability_is_logged_once_per_transition` enforces that.
    "coordinator": {"warning", "info"},
    # `warning` when no panel has connected at all. It accompanies a repair issue, fires at most
    # once per entry setup, and is the single most likely thing a user needs to be told.
    "repairs": {"warning"},
    # `exception` for an unhandled error inside a connection handler. That is a bug in this code,
    # and the alternative — swallowing it silently — is how one panel takes down a listener that is
    # serving every other panel.
    "server": {"exception"},
    # `warning` when the PGM the user identified as the electric fence's power is switched
    # directly. It is rare, it is deliberate, and it is the one action in the integration that can
    # turn the fence off without anything in the fence's own history showing why.
    "switch": {"warning"},
}


def _python_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _log_calls(tree: ast.AST) -> list[tuple[str, int]]:
    """Return every `<something>.<level>(...)` call that looks like a logger call."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        name = getattr(target, "id", None) or getattr(target, "attr", None) or ""
        if "LOGGER" in name.upper() or name in {"logger", "_log"}:
            found.append((node.func.attr, node.lineno))
    return found


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_unapproved_loud_logging(path: Path) -> None:
    """Panel traffic, events and polling must be logged at debug, never at info or above."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = ALLOWED_LOUD_CALLS.get(path.stem, set())
    offenders = [
        f"{path.name}:{line} uses LOGGER.{level}"
        for level, line in _log_calls(tree)
        if level in LOUD and level not in allowed
    ]
    assert not offenders, (
        "AGENTS.md §4: everything about the conversation with the panel is logged at debug.\n"
        + "\n".join(offenders)
        + "\nIf a message genuinely belongs at info or above, add it to ALLOWED_LOUD_CALLS."
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_deprecated_warn_alias(path: Path) -> None:
    """`logging.warn` is a deprecated alias for `logging.warning`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not [line for level, line in _log_calls(tree) if level == "warn"]
