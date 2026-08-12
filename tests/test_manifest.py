"""Smoke tests for the integration skeleton.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

These assert the things Sprint 0 actually delivers: that the package imports, that the manifest says
what AGENTS.md and the sprint require, and that the pure protocol package stayed pure.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "custom_components" / "jfl_alarm"
MANIFEST = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

# The pin the integration currently declares. Read from the manifest rather than written out, so a
# library bump is one edit instead of two — `tests/test_library_boundary.py` is what asserts the pin
# is exact and that something imports it, which is the part that actually matters. Hard-coding the
# version here only ever produced a second place to forget.
PYJFL_VERSION = next(r.split("==")[1] for r in MANIFEST["requirements"] if r.startswith("pyjfl=="))


def test_the_library_imports_without_home_assistant() -> None:
    """`pyjfl` must import with no Home Assistant present. AGENTS.md §4, ADR-0019.

    **This is narrower than it was, twice over.** Sprint 0 asserted that the *whole* package
    imported without Home Assistant, which stopped being true the moment Sprint 2 gave
    `__init__.py` an `async_setup_entry` — an integration's entry module importing Home Assistant is
    not a defect, it is the definition of an integration. It then covered the in-tree `protocol/`,
    which no longer exists here at all.

    What is left is the invariant that earns something: the published library is standard library
    only, so it can be fuzzed and type-checked without Home Assistant's stubs, and Home Assistant
    can `pip install` it into a bare environment during setup. `pyjfl`'s own suite guards its
    internals; this checks the property the *integration* depends on, against the version actually
    installed here.
    """
    import pyjfl

    assert pyjfl.JflServer is not None
    assert pyjfl.__doc__

    # Checked against the parsed imports, not against the text: the docstring in `const.py`
    # explains *why* it holds no Home Assistant import, and a substring search would trip over its
    # own explanation.
    assert not _home_assistant_imports(PACKAGE / "const.py"), (
        "const.py must stay importable without Home Assistant"
    )


def _home_assistant_imports(path: Path) -> list[str]:
    """Return the Home Assistant modules *path* imports, if any."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name.startswith("homeassistant")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("homeassistant"):
            found.append(node.module or "")
    return found


def test_read_only_defaults_on() -> None:
    """AGENTS.md §6: this controls a real alarm on an occupied house.

    Read from the source rather than by importing `const`. It re-exports three names from `pyjfl`,
    so importing it now means importing the library too — fine here, but it would make this safety
    assertion depend on the package being installed, when what it actually guards is a literal in a
    file. The AST keeps it true on any machine.
    """
    tree = ast.parse((PACKAGE / "const.py").read_text(encoding="utf-8"))
    defaults = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign | ast.Assign)
        for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        if isinstance(target, ast.Name)
    }
    value = defaults.get("DEFAULT_READ_ONLY")
    assert isinstance(value, ast.Constant) and value.value is True, (
        "DEFAULT_READ_ONLY must be True: the integration must not be able to command a real alarm "
        "until the user turns that on deliberately."
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("domain", "jfl_alarm"),
        ("integration_type", "hub"),
        ("iot_class", "local_push"),
        ("config_flow", True),
        # The codec moved to `pyjfl` on PyPI (ADR-0019) — `home-assistant/core` will not accept an
        # integration that speaks a device protocol itself. Exactly one requirement, pinned exactly;
        # `tests/test_library_boundary.py` asserts the shape of the pin and that something imports
        # it. This is still nothing like the old integration's adext/alarmdecoder/bitarray/fcntl
        # situation: `pyjfl` is this project's own package and declares no dependencies of its own.
        ("requirements", [f"pyjfl=={PYJFL_VERSION}"]),
        ("dependencies", []),
    ],
)
def test_manifest_values(key: str, value: object) -> None:
    """The manifest must match what Sprint 0 specifies."""
    assert MANIFEST[key] == value


def test_manifest_does_not_collide_with_the_old_integration() -> None:
    """A distinct domain is what lets both integrations run on one Home Assistant.

    The user's house is currently run by `jfl_active`. Both must be installable side by side while
    this one is developed and validated, and that only works because the domains differ. Checked
    against a copy of the original manifest kept in `tests/data/`.
    """
    old = json.loads((ROOT / "tests" / "data" / "legacy_manifest.json").read_text(encoding="utf-8"))
    assert old["domain"] == "jfl_active"
    assert MANIFEST["domain"] != old["domain"]


# `test_protocol_package_is_pure` stood here from Sprint 0, walking `custom_components/jfl_alarm/
# protocol/` for banned imports. That directory moved to `pyjfl` (ADR-0019), and `rglob` over a path
# that does not exist yields nothing — so the test kept passing while checking zero files, which is
# worse than not having it. The purity rule still holds; it is enforced in the library's own
# repository, next to the code it constrains. What remains here is the integration's side of the
# boundary, in `tests/test_library_boundary.py`.


# --- the quality scale ---------------------------------------------------------------------------

# Home Assistant's own tier lists, transcribed from
# https://developers.home-assistant.io/docs/core/integration-quality-scale/checklist/ on
# 2026-08-10. The scale grows: `docs-triggers` and `docs-conditions` joined Bronze after this
# project's `quality_scale.yaml` was written, and were simply absent from it until that date.
BRONZE = [
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow",
    "config-flow-test-coverage",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
]
SILVER = [
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
]
GOLD = [
    "devices",
    "diagnostics",
    "discovery",
    "discovery-update-info",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
]
PLATINUM = [
    "async-dependency",
    "inject-websession",
    "strict-typing",
]

QUALITY_SCALE_RULES = frozenset(BRONZE + SILVER + GOLD + PLATINUM)


def _quality_scale() -> dict[str, dict[str, str]]:
    """Parse `quality_scale.yaml`.

    Parsing it at all is half the test. A backtick is a YAML *reserved indicator* and cannot start
    a plain scalar, so ``comment: `icons.json` …`` made the whole file unparseable for two sprints —
    invisible here, because nothing read it, and fatal in `hassfest`, which does.
    """
    import yaml

    text = (PACKAGE / "quality_scale.yaml").read_text(encoding="utf-8")
    rules: dict[str, dict[str, str]] = yaml.safe_load(text)["rules"]
    return rules


def test_the_quality_scale_names_every_rule_home_assistant_defines() -> None:
    """A missing rule fails `hassfest`, and a rule that no longer exists fails it too.

    The list moves: `docs-triggers` and `docs-conditions` were added to Bronze after this file was
    first written, and were simply absent until 2026-08-10.
    """
    declared = set(_quality_scale())
    assert not QUALITY_SCALE_RULES - declared, (
        f"quality_scale.yaml is missing rules Home Assistant defines: "
        f"{sorted(QUALITY_SCALE_RULES - declared)}"
    )
    assert not declared - QUALITY_SCALE_RULES, (
        f"quality_scale.yaml declares rules that are not in the scale: "
        f"{sorted(declared - QUALITY_SCALE_RULES)}"
    )


def test_every_quality_scale_status_is_one_home_assistant_accepts() -> None:
    """`done`, `todo` or `exempt`, and an `exempt` must say why — that is the whole value of it."""
    for rule, entry in _quality_scale().items():
        assert entry["status"] in {"done", "todo", "exempt"}, rule
        if entry["status"] == "exempt":
            assert entry.get("comment"), f"{rule} is exempt without saying why"


def test_the_declared_tier_is_earned() -> None:
    """`manifest.json` must not claim a tier whose rules are not all `done` or `exempt`.

    AGENTS.md §0's one named form of dishonesty. The check runs on Bronze because that is what the
    manifest declares today; raising the claim means this assertion starts covering more rules.
    """
    tiers = {"bronze": BRONZE, "silver": BRONZE + SILVER, "gold": BRONZE + SILVER + GOLD}
    claimed = MANIFEST.get("quality_scale")
    if claimed not in tiers:
        return
    rules = _quality_scale()
    unmet = [rule for rule in tiers[claimed] if rules[rule]["status"] == "todo"]
    # `brands` is the one exception, and it is a submission to another repository rather than code
    # in this one. It is tracked in BACKLOG.md and must be closed before the first release.
    assert unmet == ["brands"], f"manifest claims {claimed} but these rules are todo: {unmet}"
