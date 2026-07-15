"""Tests for the config and options flows."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.ventilation_reminder.const import (
    CONF_HUMIDITY_SENSORS,
    CONF_INDOOR_SENSORS,
    CONF_OUTDOOR_SENSORS,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

GLOBAL_INPUT = {CONF_OUTDOOR_SENSORS: ["sensor.outdoor_temperature"]}
ROOM_LIVING = {
    CONF_ROOM_NAME: "Living room",
    CONF_INDOOR_SENSORS: ["sensor.living_temperature"],
    CONF_HUMIDITY_SENSORS: [],
    CONF_WINDOW_SENSORS: [],
}
ROOM_BEDROOM = {
    CONF_ROOM_NAME: "Bedroom",
    CONF_INDOOR_SENSORS: ["sensor.bedroom_temperature"],
    CONF_HUMIDITY_SENSORS: [],
    CONF_WINDOW_SENSORS: ["binary_sensor.bedroom_window"],
}

BASE_CONFIG = {
    CONF_OUTDOOR_SENSORS: ["sensor.outdoor_temperature"],
    CONF_ROOMS: [ROOM_LIVING, ROOM_BEDROOM],
}


async def test_full_user_flow(hass: HomeAssistant) -> None:
    """Global settings, two rooms (one duplicate attempt), finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], GLOBAL_INPUT
    )
    assert result["type"] == "form"
    assert result["step_id"] == "add_room"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ROOM_LIVING
    )
    assert result["type"] == "menu"
    assert result["step_id"] == "room_menu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    assert result["step_id"] == "add_room"

    # Duplicate name is rejected
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ROOM_LIVING, CONF_ROOM_NAME: "living-room"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "room_exists"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ROOM_BEDROOM
    )
    assert result["step_id"] == "room_menu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert [room[CONF_ROOM_NAME] for room in rooms] == ["Living room", "Bedroom"]
    assert result["data"][CONF_OUTDOOR_SENSORS] == ["sensor.outdoor_temperature"]


async def test_options_edit_room(hass: HomeAssistant) -> None:
    """A room can be selected and edited in place."""
    entry = MockConfigEntry(domain=DOMAIN, data=BASE_CONFIG)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_room"}
    )
    assert result["step_id"] == "edit_room"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room": "Bedroom"}
    )
    assert result["step_id"] == "edit_room_details"

    edited = {**ROOM_BEDROOM, CONF_INDOOR_SENSORS: ["sensor.new_bedroom_temperature"]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], edited
    )
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert rooms[0] == ROOM_LIVING
    assert rooms[1][CONF_INDOOR_SENSORS] == ["sensor.new_bedroom_temperature"]


async def test_options_edit_room_rejects_duplicate_name(hass: HomeAssistant) -> None:
    """Renaming a room to another existing room's name fails."""
    entry = MockConfigEntry(domain=DOMAIN, data=BASE_CONFIG)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room": "Bedroom"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ROOM_BEDROOM, CONF_ROOM_NAME: "Living Room"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "room_exists"}


async def test_options_remove_room(hass: HomeAssistant) -> None:
    """Removing a room keeps the others."""
    entry = MockConfigEntry(domain=DOMAIN, data=BASE_CONFIG)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_room"}
    )
    assert result["step_id"] == "remove_room"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROOMS: ["Living room"]}
    )
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert [room[CONF_ROOM_NAME] for room in rooms] == ["Bedroom"]


async def test_options_settings_can_clear_weather_entity(hass: HomeAssistant) -> None:
    """Clearing the optional weather entity actually removes it."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**BASE_CONFIG, CONF_WEATHER_ENTITY: "weather.home"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["step_id"] == "settings"

    # Submit without the optional weather entity
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], GLOBAL_INPUT
    )
    assert result["type"] == "create_entry"
    assert CONF_WEATHER_ENTITY not in result["data"]
