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
    def available(self) -> bool:
        """Unavailable while the readings this room is judged by are missing."""
        room = self.coordinator.data.get(self._slug)
        return (
            super().available
            and room is not None
            and room.temp_in is not None
            and self.coordinator.outdoor_temp is not None
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
        # Temperatures are kept in °C internally and shown in the system unit.
        to_display = self.coordinator.to_display
        return {
            "indoor_temperature": to_display(room.temp_in),
            "indoor_humidity": room.humidity,
            "indoor_dew_point": to_display(room.dew_point),
            "outdoor_temperature": to_display(self.coordinator.outdoor_temp),
            "outdoor_humidity": self.coordinator.outdoor_humidity,
            "outdoor_dew_point": to_display(self.coordinator.outdoor_dew_point),
            "forecast_high": to_display(self.coordinator.forecast_high),
            "ventilation_minutes": room.ventilation_minutes,
            "windows_opened_at": room.opened_at,
            "close_recommended": room.close_recommended,
            "close_reason": room.close_reason,
            "open_windows": room.open_window_names,
            "unavailable_windows": room.unknown_window_names,
        }
