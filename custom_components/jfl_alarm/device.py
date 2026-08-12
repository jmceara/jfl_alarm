"""The device tree, and keeping it in step with a panel that introduces itself late.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

**Home Assistant reads an entity's `device_info` exactly once**, when the entity is added to a
platform. That is a problem for an integration whose devices dial in: entities are created before
any panel has connected, so at registration time the model is the permissive "unknown" fallback and
there is no firmware version and no MAC address. Reassigning `_attr_device_info` afterwards changes
nothing — the registry has already been written, and it keeps saying *Unknown JFL panel* for ever.

So the registry is updated explicitly, once, when the connection frame arrives:
`async_refresh_panel_device`. This module exists separately from `entity.py` so that the coordinator
can call it without importing the entity layer, which imports the coordinator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from pyjfl import UNKNOWN_MODEL

from .const import DOMAIN, LOGGER, MANUFACTURER

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pyjfl import ConnectionInfo, WirelessRecord


def panel_device_id(serial: str) -> str:
    """Return the device registry identifier of a panel.

    Derived from the serial and nothing else, so the device survives removing and re-adding the
    integration — AGENTS.md §5.
    """
    return serial


def partition_device_id(serial: str, number: int) -> str:
    """Return the device registry identifier of one partition sub-device."""
    return f"{serial}-partition{number}"


def fence_device_id(serial: str) -> str:
    """Return the device registry identifier of the electric fence sub-device."""
    return f"{serial}-fence"


def zone_device_id(serial: str, number: int) -> str:
    """Return the device registry identifier of one zone's sub-device."""
    return f"{serial}-zone{number}"


@callback
def build_panel_device(info: ConnectionInfo | None, serial: str, name: str) -> DeviceInfo:
    """Describe the panel itself.

    Everything an installer would otherwise be tempted to expose as a sensor goes here. Firmware
    `"760"` is rendered `7.60`: it is a version, and Home Assistant sorts and displays it as one.

    *name* is the **subentry title**, not the model name, and that is not a cosmetic choice. Panel
    entities are created before the panel has dialled in, and Home Assistant derives an entity's
    `entity_id` from the device name *once*, at registration. Naming the device after the model
    would leave every entity on the panel called `sensor.unknown_jfl_panel_*` for ever.
    """
    spec = info.spec if info is not None else UNKNOWN_MODEL
    device = DeviceInfo(
        identifiers={(DOMAIN, panel_device_id(serial))},
        manufacturer=MANUFACTURER,
        name=name,
        model=spec.name,
        serial_number=serial,
    )
    if info is None:
        return device
    device["model_id"] = f"0x{info.model_byte:02X}"
    if info.firmware:
        device["sw_version"] = render_firmware(info.firmware)
    if info.mac:
        device["connections"] = {(CONNECTION_NETWORK_MAC, info.mac)}
    if info.hardware_version:
        # The board revision, from the `0x43` login tail — it is *not* in the `0x21` frame, which is
        # where Sprint 8.8 looked for it first. `hw_version` is the field Home Assistant shows
        # beside the firmware, which is exactly where an installer expects to read it.
        device["hw_version"] = info.hardware_version
    return device


def render_firmware(raw: str) -> str:
    """Turn the panel's three-character version field into a version string: `760` -> `7.60`."""
    digits = raw.strip()
    if len(digits) == 3 and digits.isdigit():
        return f"{digits[0]}.{digits[1:]}"
    return digits


@callback
def build_partition_device(serial: str, number: int, *, name: str = "") -> DeviceInfo:
    """Describe one partition as a sub-device of the panel.

    Named through `translation_key` rather than with a literal, so a Brazilian installation reads
    "Partição 1" and not "Partition 1". The alarm entity on this device sets `_attr_name = None`
    and takes the device's name, so this is the only place that name is decided.

    *name* is the partition's **programmed** name, once Sprint 6's read has fetched it. That one is
    a literal, and rightly: *Interno* is the installer's own word, in the installer's own language,
    and there is nothing to translate.
    """
    device = DeviceInfo(
        identifiers={(DOMAIN, partition_device_id(serial, number))},
        manufacturer=MANUFACTURER,
        # No `model`: a partition is not a product, and the field would show untranslated English
        # under a translated name. The name says what it is.
        via_device=(DOMAIN, panel_device_id(serial)),
    )
    if name:
        device["name"] = name
    else:
        device["translation_key"] = "partition"
        device["translation_placeholders"] = {"number": str(number)}
    return device


@callback
def build_fence_device(serial: str) -> DeviceInfo:
    """Describe the electric fence as a sub-device of the panel."""
    return DeviceInfo(
        identifiers={(DOMAIN, fence_device_id(serial))},
        manufacturer=MANUFACTURER,
        translation_key="fence",
        via_device=(DOMAIN, panel_device_id(serial)),
    )


@callback
def build_zone_device(serial: str, number: int, *, name: str = "", model: str = "") -> DeviceInfo:
    """Describe one zone as a sub-device of the panel.

    **A zone is a detector, and a detector is a device.** Sprint 5 promoted zones out of the panel
    device so that a wireless sensor gathers its own opening, battery, supervision and tamper
    entities under one heading — which is what a user means by "is the kitchen sensor all right?".

    *name* is the zone's **programmed** name once Sprint 6's read has fetched it. Both forms go
    through a `translation_key`, never a literal — `zone_named` carries the number *and* the name as
    placeholders, so a Brazilian installation reads *Zona 3 Cozinha* rather than *Zone 3 Cozinha*.
    Writing the composed name literally is exactly the bug that put an English word on a Portuguese
    device page.

    *model* names the **wireless detector** enrolled on this zone, when there is one. The family
    is the high byte of the detector's serial (`WirelessRecord.model`), confirmed against the
    panel's UI on 2026-08-09 — which reversed Sprint 5's note that the model was not knowable.
    A **hard-wired** zone still gets no model and no guess: the panel reports the *state* of a
    wired zone and never what is attached to it, so a reed switch and a magnetic contact are the
    same nibble.
    """
    device = DeviceInfo(
        identifiers={(DOMAIN, zone_device_id(serial, number))},
        manufacturer=MANUFACTURER,
        translation_key="zone_named" if name else "zone",
        translation_placeholders=(
            {"number": str(number), "name": name} if name else {"number": str(number)}
        ),
        via_device=(DOMAIN, panel_device_id(serial)),
    )
    if model:
        device["model"] = model
    return device


@callback
def async_apply_programmed_names(
    hass: HomeAssistant,
    *,
    entry_id: str,
    subentry_id: str,
    serial: str,
    zones: Mapping[int, str],
    partitions: Mapping[int, str],
    wireless: Mapping[int, WirelessRecord],
) -> None:
    """Write the panel's own names onto the zone and partition devices.

    **The device registry has to be told; `DeviceInfo` is read once and never again.** Every zone
    device was created before the programming was read, so this is the same problem — and the same
    solution — as the panel's model arriving late in `async_refresh_panel_device`.

    **Through `async_get_or_create`, not `async_update_device`, and that is the whole trick.** Only
    the former resolves a `translation_key` into a name; the latter takes a literal. Writing a
    literal here is what produced `Zone 8 A-D ECR` — an English word — in a Portuguese interface,
    on a device that had until then correctly read *Zona 8*.

    So a zone reads `Zona 3 Cozinha` or `Zone 3 Kitchen`, in the user's own language, and a zone
    with no programmed name falls back to the plain numbered key. **Never `Zone 3 (unnamed)`**: a
    parenthetical that says nothing is noise on every dashboard row, and the bare number already
    reads as "no name" — `docs/development/entity-map.md`.

    A partition that *has* a name is the one thing written literally, because *Interno* is the
    installer's own word and there is nothing to translate.

    `entity_id`s do not move. Home Assistant derives one from the device name **once**, at
    registration, so a zone that has existed since Sprint 2 keeps its id and only its friendly name
    changes. That is the behaviour the entity map asked for, and a test holds it.
    """
    registry = dr.async_get(hass)
    for number, name in zones.items():
        if (
            registry.async_get_device(identifiers={(DOMAIN, zone_device_id(serial, number))})
            is None
        ):
            continue
        radio = wireless.get(number)
        device = build_zone_device(
            serial, number, name=name, model=(radio.model or "") if radio is not None else ""
        )
        if radio is not None:
            # A zone in the wireless enrolment table is a radio device, and that table is the only
            # place the panel says so. The serial is the detector's own, printed on its label.
            device["serial_number"] = f"{radio.serial:010d}"
        registry.async_get_or_create(
            config_entry_id=entry_id, config_subentry_id=subentry_id, **device
        )

    for number, name in partitions.items():
        if (
            registry.async_get_device(identifiers={(DOMAIN, partition_device_id(serial, number))})
            is None
        ):
            continue
        registry.async_get_or_create(
            config_entry_id=entry_id,
            config_subentry_id=subentry_id,
            **build_partition_device(serial, number, name=name),
        )


@callback
def async_refresh_panel_device(
    hass: HomeAssistant,
    *,
    entry_id: str,
    subentry_id: str,
    info: ConnectionInfo,
    name: str,
) -> None:
    """Write the panel's real identity into the device registry.

    Called when the `0x21` frame arrives, which is the first moment the model byte, the firmware
    version and the MAC address are known — and which is always *after* the entities were created.
    Without this the device page reads "Unknown JFL panel" with no firmware for the life of the
    installation, because `device_info` is never looked at again.
    """
    device = build_panel_device(info, info.serial, name)
    LOGGER.debug(
        "%s: updating the device registry with model %s (0x%02X), firmware %s",
        info.serial,
        info.spec.name,
        info.model_byte,
        info.firmware,
    )
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry_id,
        config_subentry_id=subentry_id,
        **device,
    )
