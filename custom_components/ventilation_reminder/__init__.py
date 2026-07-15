"""The Ventilation Reminder integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import CONF_ROOM_NAME, CONF_ROOMS, DOMAIN, STORAGE_VERSION
from .coordinator import VentilationCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SWITCH]

type VentilationConfigEntry = ConfigEntry[VentilationCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: VentilationConfigEntry) -> bool:
    """Set up Ventilation Reminder from a config entry."""
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _async_register_hub_device(hass, entry)
    _async_cleanup_registries(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_register_hub_device(
    hass: HomeAssistant, entry: VentilationConfigEntry
) -> None:
    """Register the hub device the per-room devices link to via via_device."""
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Ventilation Reminder",
        manufacturer="Ventilation Reminder",
    )


def _async_cleanup_registries(
    hass: HomeAssistant, entry: VentilationConfigEntry
) -> None:
    """Remove entities and devices of rooms that no longer exist."""
    config = {**entry.data, **entry.options}
    slugs = {slugify(room[CONF_ROOM_NAME]) for room in config.get(CONF_ROOMS, [])}

    valid_unique_ids = {
        f"{entry.entry_id}_{slug}_ventilation_recommended" for slug in slugs
    }
    valid_unique_ids.add(f"{entry.entry_id}_snooze_today")
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.unique_id not in valid_unique_ids:
            entity_registry.async_remove(entity.entity_id)

    valid_identifiers = {(DOMAIN, entry.entry_id)} | {
        (DOMAIN, f"{entry.entry_id}_{slug}") for slug in slugs
    }
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not (device.identifiers & valid_identifiers):
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def _async_update_listener(
    hass: HomeAssistant, entry: VentilationConfigEntry
) -> None:
    """Reload the integration when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry
) -> bool:
    """Unload a config entry, flushing persisted coordinator state."""
    await entry.runtime_data.async_save_state()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the persisted state when the entry is removed for good."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
