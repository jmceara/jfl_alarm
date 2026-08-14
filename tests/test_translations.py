"""Guard the pt-BR translation against drift, on the tracks that carry it.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

AGENTS.md §1 makes Brazilian Portuguese a first-class deliverable on the HACS track: every key in
`en.json` must exist in `pt-BR.json`. That rule is easy to state and easy to forget halfway through
a sprint, so it is enforced here rather than left to review.

**This checkout can be one of two tracks**, and `pt-BR.json`'s presence tells them apart:
`scripts/publish.py`'s `core` target deliberately excludes it — `home-assistant/core` accepts
non-English translations only via Lokalise, after acceptance, never as a hand-written file in a PR
(`docs/development/ha-core-submission-gap-analysis.md` §3.2). A checkout without the file is
therefore a supported state, not a broken one, and every pt-BR-specific assertion here skips rather
than fails when it is absent — the same reasoning `test_backup_image_2026_08_09.py` uses for the raw
capture under ADR-0014. `en.json` has no such exemption: it ships on every track.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).parents[1] / "custom_components" / "jfl_alarm" / "translations"
PT_BR_PATH = TRANSLATIONS / "pt-BR.json"


def _flatten(node: object, prefix: str = "") -> set[str]:
    """Return the set of dotted paths to every leaf string in a translation file."""
    if isinstance(node, dict):
        return {
            key
            for name, child in node.items()
            for key in _flatten(child, f"{prefix}.{name}" if prefix else name)
        }
    return {prefix}


def _load(name: str) -> dict[str, object]:
    return json.loads((TRANSLATIONS / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def require_pt_br() -> None:
    """Skip a pt-BR-specific test on a checkout that legitimately has no pt-BR.json.

    `scripts/publish.py core` excludes it (see the module docstring); publishing en-only there is
    correct, not a regression this suite should catch.
    """
    if not PT_BR_PATH.exists():
        pytest.skip("pt-BR.json absent — looks like a core-track checkout, see module docstring")


def test_pt_br_has_every_english_key(require_pt_br: None) -> None:
    """pt-BR must cover en.json completely — a missing key shows up as a raw key in the UI."""
    missing = _flatten(_load("en")) - _flatten(_load("pt-BR"))
    assert not missing, f"missing from pt-BR.json: {sorted(missing)}"


def test_pt_br_has_no_extra_keys(require_pt_br: None) -> None:
    """en.json is the source of truth, so pt-BR must not carry keys English has dropped."""
    extra = _flatten(_load("pt-BR")) - _flatten(_load("en"))
    assert not extra, f"present in pt-BR.json but not en.json: {sorted(extra)}"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_no_key_references(language: str) -> None:
    """Custom integrations cannot use `[%key:...%]` — it does not resolve outside HA core.

    See AGENTS.md §1. A reference that fails to resolve renders literally in the user interface.
    """
    path = TRANSLATIONS / f"{language}.json"
    if not path.exists():
        pytest.skip(f"{language}.json absent — this looks like a core-track checkout")
    assert "[%key:" not in path.read_text(encoding="utf-8")


def test_strings_json_is_absent() -> None:
    """This project ships translations only — `strings.json` is a core-only convention.

    Applies to the HACS/private track, where this checkout's `manifest.json` still carries
    `version` (see `test_manifest.py`). The `core` submission is the one place `strings.json` is
    required instead (gap analysis §3.1); that file is generated separately for that PR, not by
    this checkout, so the assertion here is unconditional — a `core`-track checkout should never be
    this working tree with `strings.json` added by hand.
    """
    assert not (TRANSLATIONS.parent / "strings.json").exists()


def test_a_named_zone_device_keeps_its_name_translatable() -> None:
    """The device name is composed by a **translation key**, never by an f-string.

    Composing `f"Zone {number} {name}"` in Python is how an English word ended up on a Portuguese
    device page: only `async_get_or_create` resolves a translation key, and only a key can render
    "Zona 3 Cozinha" for a Brazilian installation. An English-language test run cannot see the
    difference, so it is caught here instead.
    """
    languages = ["en", "pt-BR"] if PT_BR_PATH.exists() else ["en"]
    for language in languages:
        devices = _load(language)["device"]
        assert "zone_named" in devices, f"{language} lost the named-zone device key"
        template = devices["zone_named"]["name"]
        assert "{number}" in template, f"{language} named-zone template lost the number"
        assert "{name}" in template, f"{language} named-zone template lost the name"
        assert "{number}" in devices["zone"]["name"]
