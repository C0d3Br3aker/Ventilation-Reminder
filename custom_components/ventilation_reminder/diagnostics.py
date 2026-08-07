"""Diagnostics support for Ventilation Reminder."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config": {**entry.data, **entry.options},
        # Every temperature below is in °C, the unit used internally.
        "display_unit": coordinator.display_unit,
        "outdoor_temperature": coordinator.outdoor_temp,
        "outdoor_humidity": coordinator.outdoor_humidity,
        "outdoor_dew_point": coordinator.outdoor_dew_point,
        "forecast_high": coordinator.forecast_high,
        "is_snoozed": coordinator.is_snoozed,
        "missing_entities": coordinator.missing_entities,
        "rooms": {
            slug: asdict(state) for slug, state in (coordinator.data or {}).items()
        },
    }
