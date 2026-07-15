"""Tests for setup, registry cleanup and the reminder logic."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.ventilation_reminder.const import (
    CONF_DELAY_MINUTES,
    CONF_HOT_DAY_TEMP,
    CONF_HUMIDITY_SENSORS,
    CONF_INDOOR_SENSORS,
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_SENSORS,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

CONFIG = {
    CONF_OUTDOOR_SENSORS: ["sensor.outdoor_temperature"],
    CONF_DELAY_MINUTES: 1,
    CONF_ROOMS: [
        {
            CONF_ROOM_NAME: "Living room",
            CONF_INDOOR_SENSORS: ["sensor.living_temperature"],
            CONF_HUMIDITY_SENSORS: ["sensor.living_humidity"],
            CONF_WINDOW_SENSORS: [],
        }
    ],
}


async def _setup_entry(hass: HomeAssistant, config: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=config, title="Ventilation Reminder")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sensor_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_living_room_ventilation_recommended"
    )
    assert entity_id is not None
    return entity_id


async def test_setup_creates_room_device_and_cleans_stale_entities(
    hass: HomeAssistant,
) -> None:
    """Rooms get their own device; leftovers of removed rooms are purged."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG)
    entry.add_to_hass(hass)

    # Simulate a leftover entity of a room that was removed earlier
    entity_registry = er.async_get(hass)
    stale = entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{entry.entry_id}_old_room_ventilation_recommended",
        config_entry=entry,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(stale.entity_id) is None
    assert _sensor_entity_id(hass, entry)

    device_registry = dr.async_get(hass)
    hub = device_registry.async_get_device({(DOMAIN, entry.entry_id)})
    room = device_registry.async_get_device(
        {(DOMAIN, f"{entry.entry_id}_living_room")}
    )
    assert hub is not None
    assert room is not None
    assert room.via_device_id == hub.id
    assert room.name == "Living room"


async def test_open_reminder_lifecycle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Sensor turns on after the delay, notifies, and clears again."""
    freezer.move_to("2026-07-15 17:00:00+00:00")  # 10:00 local, inside window
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")
    hass.states.async_set("sensor.living_humidity", "55.0")

    entry = await _setup_entry(hass, CONFIG)
    entity_id = _sensor_entity_id(hass, entry)
    assert hass.states.get(entity_id).state == "off"

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["indoor_temperature"] == 25.0
    assert state.attributes["indoor_humidity"] == 55.0

    # No notify services configured -> persistent notification fallback
    notifications = hass.data.get("persistent_notification", {})
    open_ids = [nid for nid in notifications if nid.startswith("ventilation_open_")]
    assert len(open_ids) == 1
    assert "Living room (25.0 °C, 55 %)" in notifications[open_ids[0]]["message"]

    # Outside warms up -> recommendation and notification go away
    hass.states.async_set("sensor.outdoor_temperature", "26.0")
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "off"
    notifications = hass.data.get("persistent_notification", {})
    assert not [nid for nid in notifications if nid.startswith("ventilation_open_")]


async def test_hot_day_hint_from_weather_forecast(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With a weather entity configured, hot days are mentioned."""
    freezer.move_to("2026-07-15 17:00:00+00:00")

    async def mock_get_forecasts(call: ServiceCall) -> dict:
        return {"weather.home": {"forecast": [{"temperature": 31.5}]}}

    hass.services.async_register(
        "weather",
        "get_forecasts",
        mock_get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")
    hass.states.async_set("sensor.living_humidity", "55.0")

    config = {**CONFIG, CONF_WEATHER_ENTITY: "weather.home", CONF_HOT_DAY_TEMP: 25.0}
    entry = await _setup_entry(hass, config)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    notifications = hass.data.get("persistent_notification", {})
    open_ids = [nid for nid in notifications if nid.startswith("ventilation_open_")]
    assert len(open_ids) == 1
    assert "31.5 °C" in notifications[open_ids[0]]["message"]
    assert entry.runtime_data.forecast_high == 31.5


async def test_humidity_triggers_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """High humidity flags the room even below the temperature thresholds."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    # 21 °C inside: below indoor_min_temp (23), diff (3 K) above min_diff —
    # but temp condition requires indoor_min, so only humidity can trigger.
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "21.0")
    hass.states.async_set("sensor.living_humidity", "72.0")

    entry = await _setup_entry(hass, CONFIG)
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "on"


async def test_dew_point_comparison_with_outdoor_humidity(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With outdoor humidity sensors, dew points decide, not temperature."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    # Inside 21 °C / 72 % -> dew point ~15.8 °C.
    # Outside 18 °C / 95 % -> dew point ~17.2 °C: cooler, but *wetter* air.
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.outdoor_humidity", "95.0")
    hass.states.async_set("sensor.living_temperature", "21.0")
    hass.states.async_set("sensor.living_humidity", "72.0")

    config = {**CONFIG, CONF_OUTDOOR_HUMIDITY_SENSORS: ["sensor.outdoor_humidity"]}
    entry = await _setup_entry(hass, config)
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # The old "cooler outside" heuristic would recommend; dew points forbid it
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["outdoor_dew_point"] > state.attributes["indoor_dew_point"]

    # Drier air outside (18 °C / 50 % -> dew point ~7.4 °C) -> recommend.
    # One cycle to pick up the new condition, one to pass the delay.
    hass.states.async_set("sensor.outdoor_humidity", "50.0")
    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert abs(state.attributes["indoor_dew_point"] - 15.76) < 0.1
    assert abs(state.attributes["outdoor_dew_point"] - 7.41) < 0.1
