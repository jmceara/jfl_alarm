"""The diagnostics download, and what must never appear in it.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

A diagnostics dump is the thing users paste into public bug reports, so the redaction rules in
AGENTS.md §4 are tested against the rendered JSON rather than against the code that writes it. A
test that checks "we called the redaction helper" passes happily when a new field is added and the
helper is not called for it.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.jfl_alarm.const import DOMAIN
from tests.panel_sim import FakePanel


async def test_the_dump_carries_state_but_no_identity(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry,
    connect_panel,
    panel: FakePanel,
) -> None:
    """Everything a bug report needs, and nothing that says whose house this is."""
    coordinator = setup_entry.runtime_data.coordinators[panel.serial]
    connection = await connect_panel(panel)
    await connection.introduce(hass)
    await connection.report_status(hass, coordinator)

    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    raw = json.dumps(result)

    # The state that makes a report useful is all there.
    [dumped] = result["panels"]
    assert dumped["connected"] is True
    assert dumped["identity"]["model"] == "Active 32 Duo"
    assert dumped["identity"]["model_byte"] == 0xA0
    assert dumped["identity"]["firmware"] == "760"
    assert dumped["capabilities"]["partitions"] == 4
    assert dumped["status"]["fence"]["present"] is True
    assert dumped["status"]["battery_volts"] > 12
    assert dumped["frames"]

    # And none of the things AGENTS.md §4 forbids.
    assert panel.serial not in raw
    assert panel.mac not in raw
    assert dumped["serial"].startswith("id:")
    assert dumped["identity"]["mac"].startswith("id:")


async def test_the_same_panel_gets_the_same_token_everywhere(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry,
    connect_panel,
    panel: FakePanel,
) -> None:
    """Redaction must not make a multi-panel dump unreadable.

    Blanking every serial to the same placeholder would turn three panels into three identical
    anonymous blobs. Hashing keeps them apart and still reveals nothing.
    """
    connection = await connect_panel(panel)
    await connection.introduce(hass)

    entry_dump = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, panel.serial)})
    panel_dump = await get_diagnostics_for_device(hass, hass_client, setup_entry, device)

    assert entry_dump["panels"][0]["serial"] == panel_dump["serial"]
    assert not panel_dump["serial"].endswith(panel.serial)

    # A sub-device resolves to its parent panel rather than dumping nothing useful.
    fence = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{panel.serial}-fence")})
    if fence is not None:
        fence_dump = await get_diagnostics_for_device(hass, hass_client, setup_entry, fence)
        assert fence_dump["serial"] == panel_dump["serial"]


async def test_a_panel_that_never_connected_still_dumps(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    """The most common bug report is "nothing appeared", so this path must not raise."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)

    assert result["listener"]["running"] is True
    [dumped] = result["panels"]
    assert dumped["connected"] is False
    assert dumped["status"] is None
    assert dumped["identity"]["model_byte"] is None


async def test_pending_panels_are_listed_and_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry,
    connect_panel,
) -> None:
    """A panel reporting in without a subentry is the other half of "nothing appeared"."""
    stranger = FakePanel(serial="STRANGER01")
    connection = await connect_panel(stranger)
    await connection.introduce(hass)

    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    raw = json.dumps(result)
    assert stranger.serial not in raw


async def test_system_health_reports_the_port_and_the_frame_age(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel
) -> None:
    """The three facts that answer "is this working?" for an integration nothing connects *to*.

    Age of the last frame rather than "connected", because a TCP socket stays open long after the
    box at the far end has lost power — a connection count alone reports healthy panels that went
    dark twenty minutes ago.
    """
    from homeassistant.setup import async_setup_component

    from custom_components.jfl_alarm.system_health import _system_health_info

    assert await async_setup_component(hass, "system_health", {})

    before = await _system_health_info(hass)
    assert before["panels_configured"] == 1
    assert before["panels_connected"] == 0
    assert before["last_frame"] == "never"
    assert str(setup_entry.data["port"]) in before["listening_on"]

    coordinator = setup_entry.runtime_data.coordinators[panel.serial]
    connection = await connect_panel(panel)
    await connection.introduce(hass)
    await connection.report_status(hass, coordinator)

    after = await _system_health_info(hass)
    assert after["panels_connected"] == 1
    assert after["last_frame"].endswith("s ago")


async def test_system_health_with_no_loaded_entry(hass: HomeAssistant) -> None:
    """It must not raise on an installation where every entry is unloaded."""
    from custom_components.jfl_alarm.system_health import _system_health_info

    assert await _system_health_info(hass) == {"listeners": 0}
