"""Snooze switch: suppress all reminders for the rest of the day."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import VentilationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the snooze switch."""
    coordinator: VentilationCoordinator = entry.runtime_data
    async_add_entities([SnoozeSwitch(coordinator)])


class SnoozeSwitch(
    CoordinatorEntity[VentilationCoordinator], SwitchEntity, RestoreEntity
):
    """On = no more reminders today; resets automatically at midnight."""

    _attr_icon = "mdi:bell-sleep"
    _attr_has_entity_name = True
    _attr_translation_key = "snooze_today"

    def __init__(self, coordinator: VentilationCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_snooze_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Ventilation Reminder",
            manufacturer="Ventilation Reminder",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if (
            last is not None
            and last.state == "on"
            and last.attributes.get("snoozed_on")
            == dt_util.now().date().isoformat()
        ):
            await self.coordinator.async_set_snooze(True)

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_snoozed

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.is_snoozed:
            return {"snoozed_on": dt_util.now().date().isoformat()}
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_snooze(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_snooze(False)
