"""`send_raw_command` — the reverse-engineering action, tested where it lives.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

These tests live in their own file for the same reason `custom_components/jfl_alarm/raw_command.py`
does: the `home-assistant/core` publication target ships neither, because an action that sends
arbitrary bytes to an alarm panel is the surface a core reviewer refuses. Keeping the code and its
tests in files that target simply never includes is what makes withholding the feature a
one-line change in `publish-targets.yaml` rather than a patch that has to be re-applied every time.
ADR-0019.
"""

from __future__ import annotations

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pyjfl import Cmd
from pytest_homeassistant_custom_component.common import MockUser

from custom_components.jfl_alarm.const import DOMAIN
from tests.integration.test_services import (
    _bring_up,
    _next_command,
    _panel_device_id,
    _writable_entry,
)
from tests.panel_sim import FakePanel


async def test_the_raw_command_action_is_registered_without_any_entry(hass: HomeAssistant) -> None:
    """Registered in `async_setup` like every other action — and only when this module ships."""
    from custom_components.jfl_alarm import async_setup

    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "send_raw_command")


async def test_send_raw_command_frames_and_returns_the_reply(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """The reverse-engineering tool: the checksum and the framing are computed for the caller."""
    panel = FakePanel(serial="RAWCMD0001")
    entry = await _writable_entry(hass, port, panel)
    try:
        connection, _ = await _bring_up(hass, entry, connect_panel, panel)
        response = await hass.services.async_call(
            DOMAIN,
            "send_raw_command",
            {
                "device_id": _panel_device_id(hass, entry.entry_id, panel.serial),
                "command": int(Cmd.ARM),
                "payload": "63",
            },
            blocking=True,
            return_response=True,
        )
        frame = await _next_command(connection)
        assert frame.cmd == Cmd.ARM
        assert frame.raw[4] == 0x63
        assert "frames" in response
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_a_bad_raw_payload_is_rejected_before_anything_is_sent(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """A typo is a typo, and a typo must not reach an alarm panel as bytes."""
    panel = FakePanel(serial="RAWBAD0001")
    entry = await _writable_entry(hass, port, panel)
    try:
        connection, _ = await _bring_up(hass, entry, connect_panel, panel)
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "send_raw_command",
                {
                    "device_id": _panel_device_id(hass, entry.entry_id, panel.serial),
                    "command": 0x4D,
                    "payload": "not hex",
                },
                blocking=True,
            )
        with pytest.raises(TimeoutError):
            await connection.read_reply(timeout=0.3)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_an_empty_payload_sends_a_bare_command(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """No payload is a legitimate call — a command byte with nothing to go with it."""
    panel = FakePanel(serial="RAWEMPTY01")
    entry = await _writable_entry(hass, port, panel)
    try:
        connection, _ = await _bring_up(hass, entry, connect_panel, panel)
        response = await hass.services.async_call(
            DOMAIN,
            "send_raw_command",
            {
                "device_id": _panel_device_id(hass, entry.entry_id, panel.serial),
                "command": int(Cmd.ARM),
                "payload": "   ",
            },
            blocking=True,
            return_response=True,
        )
        frame = await _next_command(connection)
        assert frame.cmd == Cmd.ARM
        assert frame.payload == b""
        assert "frames" in response
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_a_non_admin_user_is_refused_before_anything_is_sent(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """Admin only, per the module's own docstring — a careless call must not reach a live alarm."""
    panel = FakePanel(serial="RAWNOTADM1")
    entry = await _writable_entry(hass, port, panel)
    try:
        connection, _ = await _bring_up(hass, entry, connect_panel, panel)
        non_admin = MockUser(groups=[]).add_to_hass(hass)
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "send_raw_command",
                {
                    "device_id": _panel_device_id(hass, entry.entry_id, panel.serial),
                    "command": int(Cmd.ARM),
                    "payload": "63",
                },
                blocking=True,
                context=Context(user_id=non_admin.id),
            )
        with pytest.raises(TimeoutError):
            await connection.read_reply(timeout=0.3)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_an_unknown_user_id_is_also_refused(
    hass: HomeAssistant, port: int, connect_panel
) -> None:
    """A context naming a user id that no longer exists must fail closed, not raise or pass."""
    panel = FakePanel(serial="RAWNOUSER1")
    entry = await _writable_entry(hass, port, panel)
    try:
        connection, _ = await _bring_up(hass, entry, connect_panel, panel)
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "send_raw_command",
                {
                    "device_id": _panel_device_id(hass, entry.entry_id, panel.serial),
                    "command": int(Cmd.ARM),
                    "payload": "63",
                },
                blocking=True,
                context=Context(user_id="no-such-user"),
            )
        with pytest.raises(TimeoutError):
            await connection.read_reply(timeout=0.3)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
