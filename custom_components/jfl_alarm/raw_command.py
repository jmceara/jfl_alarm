"""The `send_raw_command` action — the reverse-engineering tool, in its own module.

Author: Jonis Maurin Ceará <jmceara AT gmail.com>
Based on the code developed by Carlos Jose Fernandes,
available at https://github.com/fernac03/JFL_ACTIVE

**Why this is a separate module and not four more functions in `services.py`.** An action that sends
arbitrary bytes to an alarm panel is exactly the surface a `home-assistant/core` reviewer refuses,
and this project has its own evidence for why they are right: during the 2026-08-09 capture, JFL's
own ActiveNet erased a user's access code with a malformed programming write. So the core track does
not ship it — and the cleanest way to withhold a feature from one publication target is to keep it
in a file that target's `include` list simply never reaches
(`publish-targets.yaml`, and ADR-0019 for the reasoning). `services.py` imports it defensively and
registers the action only when the module is present, so the HACS track keeps the tool and the core
track never had it.

The action itself is unchanged: **admin only**, both of the coordinator's gates still apply, and
every call is logged at `warning` rather than `debug`, because it is the one path in the integration
that can send something nobody has verified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import ServiceCall, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util.json import JsonValueType

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import JflPanelCoordinator

SERVICE_SEND_RAW_COMMAND = "send_raw_command"

ATTR_COMMAND = "command"
ATTR_PAYLOAD = "payload"


def schema(target_schema: vol.Schema) -> vol.Schema:
    """Extend the shared device-target schema with this action's own two fields.

    Takes the base schema as an argument rather than importing it, so that `services.py` owns the
    definition of what targeting a panel means and this module cannot drift from it.
    """
    return target_schema.extend(
        {
            vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFF)),
            vol.Optional(ATTR_PAYLOAD, default=""): cv.string,
        }
    )


async def async_send_raw_command(
    coordinator: JflPanelCoordinator, call: ServiceCall
) -> ServiceResponse:
    """Send an arbitrary command and return whatever the panel said next.

    **Admin only.** This is how the next undocumented command gets found, and it is also how a
    careless call reaches a live alarm — so the caller must be a Home Assistant administrator, the
    panel's two gates still apply, and the whole thing is logged at `warning`.
    """
    if call.context.user_id is not None:
        user = await coordinator.hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="admin_only")

    payload = parse_payload(str(call.data.get(ATTR_PAYLOAD, "")))
    frames: list[JsonValueType] = list(
        await coordinator.async_send_raw(int(call.data[ATTR_COMMAND]), payload)
    )
    return {"frames": frames}


def parse_payload(text: str) -> bytes:
    """Parse a hex payload written the way a capture prints it: `01 02 FF`, or `0102FF`."""
    cleaned = text.replace(",", " ").replace("0x", "").replace(":", " ").strip()
    if not cleaned:
        return b""
    try:
        if " " in cleaned:
            return bytes(int(part, 16) for part in cleaned.split())
        return bytes.fromhex(cleaned)
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_payload",
            translation_placeholders={"payload": text},
        ) from err
