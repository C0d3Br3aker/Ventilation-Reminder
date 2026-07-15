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
    _attr_has_entity_name = True
    _attr_translation_key = "ventilation_recommended"

    def __init__(self, coordinator: VentilationCoordinator, slug: str) -> None:
        super().__init__(coordinator)
        self._slug = slug
        room = coordinator.data[slug]
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{slug}_ventilation_recommended"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{slug}")},
            name=room.name,
            manufacturer="Ventilation Reminder",
            via_device=(DOMAIN, coordinator.entry.entry_id),
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
            "indoor_humidity": room.humidity,
            "indoor_dew_point": room.dew_point,
            "outdoor_temperature": self.coordinator.outdoor_temp,
            "outdoor_humidity": self.coordinator.outdoor_humidity,
            "outdoor_dew_point": self.coordinator.outdoor_dew_point,
            "forecast_high": self.coordinator.forecast_high,
            "close_recommended": room.close_recommended,
            "open_windows": room.open_window_names,
        }
