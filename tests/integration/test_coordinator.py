"""The coordinator, the entry lifecycle and the repair issues.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE
"""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from pyjfl import Cmd, FrameReader
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.jfl_alarm.const import (
    CONF_STATUS_INTERVAL,
    DOMAIN,
    ISSUE_PANEL_NEVER_CONNECTED,
    ISSUE_UNSUPPORTED_MODEL,
    PANEL_NEVER_CONNECTED_MINUTES,
)
from tests.integration.conftest import make_entry, wait_until
from tests.panel_sim import FakePanel


async def test_the_snapshot_is_never_none(hass: HomeAssistant, setup_entry) -> None:
    """Entities are created before any panel has dialled in, so `data` must already exist."""
    [coordinator] = list(setup_entry.runtime_data.coordinators.values())
    assert coordinator.data is not None
    assert coordinator.data.connection is None
    assert coordinator.data.available is False
    # And the permissive model fallback stands in, rather than raising.
    assert coordinator.data.spec.partitions > 0
    assert coordinator.data.partitions == ()
    assert coordinator.data.zones == ()
    assert coordinator.data.fence.present is False


async def test_setup_does_not_fail_when_no_panel_is_there(hass: HomeAssistant, setup_entry) -> None:
    """`async_config_entry_first_refresh` is deliberately never called.

    A panel typically dials in ten to sixty seconds after Home Assistant starts. A first refresh
    would turn "the panel is still booting" into "the integration failed to set up".
    """
    assert setup_entry.state is ConfigEntryState.LOADED


async def test_an_undecodable_command_is_counted_not_dropped(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel
) -> None:
    """An unknown command is how the next undocumented one gets found."""
    from pyjfl import build_frame

    coordinator = setup_entry.runtime_data.coordinators[panel.serial]
    connection = await connect_panel(panel)
    await connection.introduce(hass)

    await connection.send(build_frame(0x42, 0x7E, b"\x01\x02\x03"))
    await wait_until(hass, lambda: coordinator.data.unknown_packets == 1)


async def test_the_poll_loop_asks_on_its_interval(
    # `freezer` is requested **before** anything that schedules a timer. Starting freezegun after
    # a timer exists moves the clock underneath it, and the timer fires immediately.
    freezer: FrozenDateTimeFactory,
    hass: HomeAssistant,
    port: int,
    connect_panel,
) -> None:
    """The panel never volunteers its status, so something has to ask on a schedule."""
    entry = make_entry(port, options={CONF_STATUS_INTERVAL: 5})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    try:
        panel = FakePanel()
        connection = await connect_panel(panel)
        await connection.introduce(hass)

        freezer.tick(timedelta(seconds=6))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        reply = await connection.read_reply()
        assert FrameReader().feed(reply)[0].cmd == Cmd.STATUS
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_availability_is_logged_once_per_transition(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel, caplog
) -> None:
    """A panel that redials every ninety seconds must not fill the log with a pair of lines."""
    coordinator = setup_entry.runtime_data.coordinators[panel.serial]

    first = await connect_panel(panel)
    await first.introduce(hass)
    await first.close()
    await wait_until(hass, lambda: not coordinator.data.available)

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert sum("stopped reporting" in record.message for record in warnings) == 1

    caplog.clear()
    second = await connect_panel(panel)
    await second.introduce(hass)
    await wait_until(hass, lambda: coordinator.data.available)

    # Recovery is one line at info, and the warning is not repeated.
    assert sum("is reporting again" in record.message for record in caplog.records) == 1


async def test_an_untested_model_raises_a_repair_issue(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """Only the Active 32 Duo has been validated on hardware — AGENTS.md §0."""
    panel = FakePanel(serial="UNTESTED01", model_byte=0xA4)
    entry = make_entry(port, serials=[panel.serial])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    try:
        connection = await connect_panel(panel)
        await connection.introduce(hass)

        issues = ir.async_get(hass)
        issue = issues.async_get_issue(DOMAIN, f"{ISSUE_UNSUPPORTED_MODEL}_{panel.serial}")
        assert issue is not None
        assert issue.translation_key == ISSUE_UNSUPPORTED_MODEL
        assert issue.translation_placeholders["model"] == "Active 100 Bus"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_an_unlisted_model_says_so_rather_than_failing(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """An unknown model byte must degrade permissively, never raise. AGENTS.md §0."""
    panel = FakePanel(serial="MYSTERY001", model_byte=0xEE)
    entry = make_entry(port, serials=[panel.serial])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    try:
        connection = await connect_panel(panel)
        await connection.introduce(hass)

        issues = ir.async_get(hass)
        issue = issues.async_get_issue(DOMAIN, f"{ISSUE_UNSUPPORTED_MODEL}_{panel.serial}")
        assert issue is not None
        assert issue.translation_key == "unknown_model"
        assert issue.translation_placeholders["model_byte"] == "0xEE"

        # Entities still appear, which is the whole point of degrading permissively.
        coordinator = entry.runtime_data.coordinators[panel.serial]
        await connection.report_status(hass, coordinator)
        assert hass.states.get("alarm_control_panel.partition_1") is not None
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_a_verified_model_raises_no_issue(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel
) -> None:
    """The Active 32 Duo is the one model that has been tested, so it gets no warning."""
    connection = await connect_panel(panel)
    await connection.introduce(hass)

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_UNSUPPORTED_MODEL}_{panel.serial}") is None


async def test_silence_raises_the_never_connected_issue(
    freezer: FrozenDateTimeFactory, hass: HomeAssistant, setup_entry
) -> None:
    """The answer to "I installed it and nothing appeared"."""
    freezer.tick(timedelta(minutes=PANEL_NEVER_CONNECTED_MINUTES + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, ISSUE_PANEL_NEVER_CONNECTED)
    assert issue is not None
    assert issue.translation_placeholders["port"] == str(setup_entry.data["port"])


async def test_no_issue_when_a_panel_did_connect(
    freezer: FrozenDateTimeFactory,
    hass: HomeAssistant,
    setup_entry,
    connect_panel,
    panel: FakePanel,
) -> None:
    """The check is about silence, not about elapsed time."""
    connection = await connect_panel(panel)
    await connection.introduce(hass)

    freezer.tick(timedelta(minutes=PANEL_NEVER_CONNECTED_MINUTES + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, ISSUE_PANEL_NEVER_CONNECTED) is None


async def test_reloading_the_entry_leaves_no_listener_behind(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel
) -> None:
    """A reload that leaked its listener would make every later reload fail on a busy port."""
    connection = await connect_panel(panel)
    await connection.introduce(hass)

    assert await hass.config_entries.async_reload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.LOADED

    # The panel redials after a reload, exactly as it does after a restart.
    again = await connect_panel(panel)
    await again.introduce(hass)
    assert setup_entry.runtime_data.server.link(panel.serial).connected


async def test_the_device_of_a_removed_panel_can_be_deleted(
    hass: HomeAssistant, setup_entry, connect_panel, panel: FakePanel
) -> None:
    """A replaced panel leaves a device that will never update again."""
    from custom_components.jfl_alarm import async_remove_config_entry_device

    connection = await connect_panel(panel)
    await connection.introduce(hass)

    devices = dr.async_get(hass)
    live = devices.async_get_device(identifiers={(DOMAIN, panel.serial)})
    assert live is not None
    assert not await async_remove_config_entry_device(hass, setup_entry, live)

    stale = devices.async_get_or_create(
        config_entry_id=setup_entry.entry_id, identifiers={(DOMAIN, "GONEPANEL1")}
    )
    assert await async_remove_config_entry_device(hass, setup_entry, stale)
