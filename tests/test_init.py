"""Tests for setup, registry cleanup and the reminder logic."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ventilation_reminder.const import (
    CONF_DELAY_MINUTES,
    CONF_FROST_MIN_TEMP,
    CONF_HOT_DAY_TEMP,
    CONF_HUMIDITY_SENSORS,
    CONF_INDOOR_MIN_TEMP,
    CONF_INDOOR_SENSORS,
    CONF_MIN_DIFF,
    CONF_NOTIFY_SERVICES,
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_SENSORS,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)
from custom_components.ventilation_reminder.coordinator import VentilationCoordinator

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


def _set_temperature(
    hass: HomeAssistant, entity_id: str, value: float, unit: str
) -> None:
    hass.states.async_set(
        entity_id,
        str(value),
        {ATTR_DEVICE_CLASS: "temperature", ATTR_UNIT_OF_MEASUREMENT: unit},
    )


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
    room = device_registry.async_get_device({(DOMAIN, f"{entry.entry_id}_living_room")})
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
    assert (
        "Living room (25.0 °C, 55 %, ~18 min)" in notifications[open_ids[0]]["message"]
    )

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


async def test_no_humidity_reminder_when_hotter_outside(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Drier but much hotter air outside must not trigger a reminder."""
    freezer.move_to("2026-07-15 15:00:00+00:00")
    # Inside 24.5 °C / 69 % -> dew point ~18.3 °C.
    # Outside 33 °C / 30 % -> dew point ~13.0 °C: drier, but far too hot.
    hass.states.async_set("sensor.outdoor_temperature", "33.0")
    hass.states.async_set("sensor.outdoor_humidity", "30.0")
    hass.states.async_set("sensor.living_temperature", "24.5")
    hass.states.async_set("sensor.living_humidity", "69.0")

    config = {**CONFIG, CONF_OUTDOOR_HUMIDITY_SENSORS: ["sensor.outdoor_humidity"]}
    entry = await _setup_entry(hass, config)
    entity_id = _sensor_entity_id(hass, entry)

    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["outdoor_dew_point"] < state.attributes["indoor_dew_point"]


async def test_frost_threshold_blocks_the_humidity_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A room this cold must not be aired out for the sake of its humidity."""
    freezer.move_to("2026-01-15 18:00:00+00:00")  # 10:00 local, inside window
    hass.states.async_set("sensor.outdoor_temperature", "2.0")
    hass.states.async_set("sensor.living_temperature", "14.0")
    hass.states.async_set("sensor.living_humidity", "72.0")

    entry = await _setup_entry(hass, {**CONFIG, CONF_FROST_MIN_TEMP: 15.0})
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "off"

    # Warm enough again -> the humidity path works as usual
    hass.states.async_set("sensor.living_temperature", "16.0")
    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "on"


async def test_cold_outside_asks_for_a_short_burst(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """In winter the reminder asks for a burst, not for an open window."""
    freezer.move_to("2026-01-15 18:00:00+00:00")  # 10:00 local, inside window
    # 20 °C inside, 2 °C outside -> 18 K difference -> 7 minutes
    hass.states.async_set("sensor.outdoor_temperature", "2.0")
    hass.states.async_set("sensor.living_temperature", "20.0")
    hass.states.async_set("sensor.living_humidity", "72.0")

    # A ten minute delay would outlast the burst it announces
    config = {**CONFIG, CONF_DELAY_MINUTES: 10}
    entry = await _setup_entry(hass, config)
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["ventilation_minutes"] == 7

    notifications = hass.data.get("persistent_notification", {})
    open_ids = [nid for nid in notifications if nid.startswith("ventilation_open_")]
    message = notifications[open_ids[0]]["message"]
    assert "Air out briefly in" in message
    assert "Living room (20.0 °C, 72 %, ~7 min)" in message


async def test_close_reminder_after_the_recommended_duration(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Burst ventilating never gets warmer outside, so time has to end it."""
    freezer.move_to("2026-01-15 18:00:00+00:00")  # 10:00 local, inside window
    hass.states.async_set("sensor.outdoor_temperature", "2.0")
    hass.states.async_set("sensor.living_temperature", "20.0")
    hass.states.async_set("sensor.living_humidity", "72.0")
    hass.states.async_set(
        "binary_sensor.living_window",
        "on",
        {ATTR_DEVICE_CLASS: "window", "friendly_name": "Living window"},
    )

    config = {
        **CONFIG,
        CONF_ROOMS: [
            {
                **CONFIG[CONF_ROOMS][0],
                CONF_WINDOW_SENSORS: ["binary_sensor.living_window"],
            }
        ],
    }
    entry = await _setup_entry(hass, config)
    room = entry.runtime_data.data["living_room"]
    assert room.opened_at is not None
    assert not room.close_recommended

    # Still inside the recommended seven minutes
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not entry.runtime_data.data["living_room"].close_recommended

    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    room = entry.runtime_data.data["living_room"]
    assert room.close_recommended
    assert room.close_reason == "aired"

    notifications = hass.data.get("persistent_notification", {})
    close_ids = [nid for nid in notifications if nid.startswith("ventilation_close_")]
    assert len(close_ids) == 1
    message = notifications[close_ids[0]]["message"]
    assert "That is enough fresh air." in message
    assert "Living room (Living window)" in message

    # Closing the window ends it and forgets the timer
    hass.states.async_set(
        "binary_sensor.living_window",
        "off",
        {ATTR_DEVICE_CLASS: "window", "friendly_name": "Living window"},
    )
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert not entry.runtime_data.data["living_room"].close_recommended
    assert entry.runtime_data._opened_at == {}


def _stored(entry: MockConfigEntry, data: dict) -> dict:
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": data,
    }


async def test_restart_clears_persistent_notification_state(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A restart wipes persistent notifications, so _notified_* must reset."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, title="Ventilation Reminder")
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = _stored(
        entry, {"notified_open": ["living_room"], "acked_open": ["living_room"]}
    )

    hass.set_state(CoreState.starting)
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator._async_restore_state()

    # No notify services configured -> the notification did not survive
    assert coordinator._notified_open == set()
    # Acks are unrelated to the notification and must be kept
    assert coordinator._acked_open == {"living_room"}


async def test_restart_keeps_notification_state_for_mobile_app(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Mobile app notifications survive a restart, so the tag must not resend."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**CONFIG, CONF_NOTIFY_SERVICES: ["mobile_app_phone"]},
        title="Ventilation Reminder",
    )
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = _stored(
        entry, {"notified_open": ["living_room"]}
    )

    hass.set_state(CoreState.starting)
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator._async_restore_state()

    assert coordinator._notified_open == {"living_room"}


async def test_reload_keeps_persistent_notification_state(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A reload while running leaves persistent notifications in place."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, title="Ventilation Reminder")
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = _stored(
        entry, {"notified_open": ["living_room"]}
    )

    hass.set_state(CoreState.running)
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator._async_restore_state()

    assert coordinator._notified_open == {"living_room"}


async def test_restart_restarts_the_delay_timers(
    hass: HomeAssistant, hass_storage: dict, freezer: FrozenDateTimeFactory
) -> None:
    """Across a restart the condition cannot be shown to have held."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, title="Ventilation Reminder")
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = _stored(
        entry, {"open_since": {"living_room": "2026-07-15T14:00:00+00:00"}}
    )

    hass.set_state(CoreState.starting)
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator._async_restore_state()

    # A three hour old timestamp would clear any delay on the first cycle
    assert coordinator._open_since == {}


async def test_reload_keeps_the_delay_timers(
    hass: HomeAssistant, hass_storage: dict, freezer: FrozenDateTimeFactory
) -> None:
    """A reload does not interrupt evaluation, so timers keep running."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, title="Ventilation Reminder")
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = _stored(
        entry, {"open_since": {"living_room": "2026-07-15T16:59:30+00:00"}}
    )

    hass.set_state(CoreState.running)
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator._async_restore_state()

    assert set(coordinator._open_since) == {"living_room"}


async def test_unchanged_state_is_not_rewritten(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Idle update cycles must not schedule a storage write."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "21.0")
    hass.states.async_set("sensor.living_humidity", "45.0")

    entry = await _setup_entry(hass, CONFIG)
    coordinator = entry.runtime_data

    writes = 0
    original = coordinator._store.async_delay_save

    def _counting_delay_save(*args, **kwargs):
        nonlocal writes
        writes += 1
        return original(*args, **kwargs)

    coordinator._store.async_delay_save = _counting_delay_save

    for _ in range(3):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert writes == 0


async def test_fahrenheit_sensors_are_converted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Sensors reporting °F are normalised before they are compared."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.config.units = US_CUSTOMARY_SYSTEM

    # 64.4 °F = 18 °C outside, 77 °F = 25 °C inside: the same situation as
    # test_open_reminder_lifecycle, only in Fahrenheit.
    _set_temperature(
        hass, "sensor.outdoor_temperature", 64.4, UnitOfTemperature.FAHRENHEIT
    )
    _set_temperature(
        hass, "sensor.living_temperature", 77.0, UnitOfTemperature.FAHRENHEIT
    )
    hass.states.async_set("sensor.living_humidity", "55.0")

    # Thresholds are entered in the system unit: 73.4 °F = 23 °C, 1.8 °F = 1 K
    config = {**CONFIG, CONF_INDOOR_MIN_TEMP: 73.4, CONF_MIN_DIFF: 1.8}
    entry = await _setup_entry(hass, config)
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    # Attributes and texts come back in the system unit
    assert state.attributes["indoor_temperature"] == 77.0
    assert state.attributes["outdoor_temperature"] == 64.4
    assert entry.runtime_data.data["living_room"].temp_in == 25.0

    notifications = hass.data.get("persistent_notification", {})
    open_ids = [nid for nid in notifications if nid.startswith("ventilation_open_")]
    assert "64.4 °F" in notifications[open_ids[0]]["message"]
    assert (
        "Living room (77.0 °F, 55 %, ~18 min)" in notifications[open_ids[0]]["message"]
    )


async def test_celsius_sensor_on_a_fahrenheit_system(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A sensor's own unit wins over the system unit."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.config.units = US_CUSTOMARY_SYSTEM

    _set_temperature(
        hass, "sensor.outdoor_temperature", 18.0, UnitOfTemperature.CELSIUS
    )
    _set_temperature(hass, "sensor.living_temperature", 25.0, UnitOfTemperature.CELSIUS)
    hass.states.async_set("sensor.living_humidity", "55.0")

    config = {**CONFIG, CONF_INDOOR_MIN_TEMP: 73.4, CONF_MIN_DIFF: 1.8}
    entry = await _setup_entry(hass, config)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    room = entry.runtime_data.data["living_room"]
    assert room.temp_in == 25.0
    assert room.open_recommended


async def test_unavailable_window_blocks_the_open_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An unavailable contact must not be treated as a closed window."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")
    hass.states.async_set("sensor.living_humidity", "55.0")
    hass.states.async_set(
        "binary_sensor.living_window",
        STATE_UNAVAILABLE,
        {ATTR_DEVICE_CLASS: "window", "friendly_name": "Living window"},
    )

    config = {
        **CONFIG,
        CONF_ROOMS: [
            {
                **CONFIG[CONF_ROOMS][0],
                CONF_WINDOW_SENSORS: ["binary_sensor.living_window"],
            }
        ],
    }
    entry = await _setup_entry(hass, config)
    entity_id = _sensor_entity_id(hass, entry)

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["unavailable_windows"] == ["Living window"]

    # Once the contact reports again, the reminder works as usual
    hass.states.async_set(
        "binary_sensor.living_window",
        "off",
        {ATTR_DEVICE_CLASS: "window", "friendly_name": "Living window"},
    )
    # One cycle starts the delay timer, the next one lets it expire
    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["unavailable_windows"] == []


async def test_missing_readings_make_the_sensor_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without usable readings the room state is unknown, not 'off'."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")

    entry = await _setup_entry(hass, CONFIG)
    entity_id = _sensor_entity_id(hass, entry)
    assert hass.states.get(entity_id).state == "off"

    hass.states.async_set("sensor.living_temperature", STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_repair_issue_for_entities_that_disappeared(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A deleted or renamed sensor is reported instead of silently ignored."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.set_state(CoreState.running)
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")
    hass.states.async_set("sensor.living_humidity", "55.0")

    entry = await _setup_entry(hass, CONFIG)
    issue_registry = ir.async_get(hass)
    issue_id = f"missing_entities_{entry.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    hass.states.async_remove("sensor.living_humidity")
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entities"] == "sensor.living_humidity"
    assert entry.runtime_data.missing_entities == ["sensor.living_humidity"]

    # It comes back -> the issue is resolved automatically
    hass.states.async_set("sensor.living_humidity", "55.0")
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_attribute_only_change_does_not_refresh(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Attribute updates carry no new reading, so they must not re-evaluate."""
    freezer.move_to("2026-07-15 17:00:00+00:00")
    hass.states.async_set("sensor.outdoor_temperature", "18.0")
    hass.states.async_set("sensor.living_temperature", "25.0")

    entry = await _setup_entry(hass, CONFIG)
    coordinator = entry.runtime_data

    refreshes = 0
    original = coordinator.async_request_refresh

    async def _counting_refresh():
        nonlocal refreshes
        refreshes += 1
        await original()

    coordinator.async_request_refresh = _counting_refresh

    hass.states.async_set("sensor.living_temperature", "25.0", {"battery": 90})
    await hass.async_block_till_done()
    assert refreshes == 0

    hass.states.async_set("sensor.living_temperature", "24.0", {"battery": 90})
    await hass.async_block_till_done()
    assert refreshes == 1
