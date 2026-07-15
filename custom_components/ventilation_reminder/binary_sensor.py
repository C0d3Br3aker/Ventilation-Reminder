"""Per-room "ventilation recommended" binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VentilationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one binary sensor per configured room."""
    coordinator: VentilationCoordinator = entry.runtime_data
    async_add_entities(
        VentilationRecommendedSensor(coordinator, slug) for slug in coordinator.data
    )


class VentilationRecommendedSensor(
    CoordinatorEntity[VentilationCoordinator], BinarySensorEntity
):
    """On while opening the windows of this room is recommended."""

    _attr_icon = "mdi:window-open-variant"

    def __init__(self, coordinator: VentilationCoordinator, slug: str) -> None:
        super().__init__(coordinator)
        self._slug = slug
        room = coordinator.data[slug]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{slug}_ventilation_recommended"
        )
        self._attr_name = f"{room.name} ventilation recommended"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Ventilation Reminder",
            manufacturer="Ventilation Reminder",
        )

    @property
    def is_on(self) -> bool:
        room = self.coordinator.data.get(self._slug)
        return bool(room and room.open_recommended)

    @property
    def extra_state_attributes(self) -> dict:
        room = self.coordinator.data.get(self._slug)
        if room is None:
            return {}
        return {
            "indoor_temperature": room.temp_in,
            "outdoor_temperature": self.coordinator.outdoor_temp,
            "close_recommended": room.close_recommended,
            "open_windows": room.open_window_names,
        }
