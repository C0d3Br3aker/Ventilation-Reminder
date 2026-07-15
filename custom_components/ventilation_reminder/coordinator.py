"""Coordinator for the Ventilation Reminder integration."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_DELAY_MINUTES,
    CONF_HOT_DAY_TEMP,
    CONF_HUMIDITY_SENSORS,
    CONF_HUMIDITY_THRESHOLD,
    CONF_INDOOR_MIN_TEMP,
    CONF_INDOOR_SENSORS,
    CONF_LANGUAGE,
    CONF_MIN_DIFF,
    CONF_NOTIFY_SERVICES,
    CONF_OUTDOOR_HUMIDITY_SENSORS,
    CONF_OUTDOOR_SENSORS,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_TIME_END,
    CONF_TIME_START,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DEFAULT_DELAY_MINUTES,
    DEFAULT_HOT_DAY_TEMP,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_INDOOR_MIN_TEMP,
    DEFAULT_MIN_DIFF,
    DEFAULT_TIME_END,
    DEFAULT_TIME_START,
    DEW_POINT_MIN_DIFF,
    DOMAIN,
    LANG_AUTO,
    LANG_DE,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ACTION_EVENT = "mobile_app_notification_action"
NOTIFICATION_GROUP = "ventilation_reminder"
FORECAST_MAX_AGE = timedelta(minutes=30)
STORE_SAVE_DELAY = 10


@dataclass
class RoomState:
    """Evaluated state of a single room."""

    name: str
    slug: str
    temp_in: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    open_window_names: list[str] = field(default_factory=list)
    open_recommended: bool = False
    close_recommended: bool = False


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "?"


def _dew_point(temp: float | None, rel_humidity: float | None) -> float | None:
    """Dew point in °C via the Magnus formula (valid for -45…60 °C)."""
    if temp is None or rel_humidity is None or rel_humidity <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = (a * temp / (b + temp)) + math.log(rel_humidity / 100.0)
    return b * gamma / (a - gamma)


class VentilationCoordinator(DataUpdateCoordinator[dict[str, RoomState]]):
    """Evaluates all rooms and sends aggregated notifications."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Ventilation Reminder",
            config_entry=entry,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.rooms: list[dict] = self.config.get(CONF_ROOMS, [])
        self.outdoor_temp: float | None = None
        self.outdoor_humidity: float | None = None
        self.outdoor_dew_point: float | None = None
        self.forecast_high: float | None = None
        self._forecast_fetched: datetime | None = None

        self._open_since: dict[str, datetime] = {}
        self._close_since: dict[str, datetime] = {}
        # Rooms dismissed via the "Done" button, until their condition resets
        self._acked_open: set[str] = set()
        self._acked_close: set[str] = set()
        # Rooms currently shown in the open/close notification
        self._notified_open: set[str] = set()
        self._notified_close: set[str] = set()
        self._snoozed_on: date | None = None

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )

        suffix = entry.entry_id[:8]
        self.done_action = f"ventilation_done_{suffix}"
        self.snooze_action = f"ventilation_snooze_{suffix}"
        self._open_tag = f"ventilation_open_{suffix}"
        self._close_tag = f"ventilation_close_{suffix}"

    async def async_setup(self) -> None:
        """Restore persisted state and subscribe to state changes and actions."""
        await self._async_restore_state()

        entities: list[str] = list(self.config.get(CONF_OUTDOOR_SENSORS, []))
        entities += self.config.get(CONF_OUTDOOR_HUMIDITY_SENSORS, [])
        for room in self.rooms:
            entities += room.get(CONF_INDOOR_SENSORS, [])
            entities += room.get(CONF_HUMIDITY_SENSORS, [])
            entities += room.get(CONF_WINDOW_SENSORS, [])
        if entities:
            self.entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, list(dict.fromkeys(entities)), self._handle_state_change
                )
            )
        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                NOTIFICATION_ACTION_EVENT, self._handle_notification_action
            )
        )

    @callback
    def _handle_state_change(self, event: Event) -> None:
        # async_request_refresh is debounced, so sensor bursts are cheap
        self.hass.async_create_task(self.async_request_refresh())

    async def _handle_notification_action(self, event: Event) -> None:
        action = event.data.get("action")
        if action == self.done_action:
            self._acked_open |= self._notified_open
            self._acked_close |= self._notified_close
            await self._async_clear_notifications()
            self._schedule_save()
            await self.async_request_refresh()
        elif action == self.snooze_action:
            await self.async_set_snooze(True)

    # --- Persistence --------------------------------------------------------

    def _state_to_save(self) -> dict[str, Any]:
        return {
            "open_since": {
                slug: when.isoformat() for slug, when in self._open_since.items()
            },
            "close_since": {
                slug: when.isoformat() for slug, when in self._close_since.items()
            },
            "acked_open": sorted(self._acked_open),
            "acked_close": sorted(self._acked_close),
            "notified_open": sorted(self._notified_open),
            "notified_close": sorted(self._notified_close),
            "snoozed_on": self._snoozed_on.isoformat() if self._snoozed_on else None,
        }

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._state_to_save, STORE_SAVE_DELAY)

    async def async_save_state(self) -> None:
        """Flush the persisted state immediately (called on unload)."""
        await self._store.async_save(self._state_to_save())

    async def _async_restore_state(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return

        def _parse_times(raw: dict[str, str]) -> dict[str, datetime]:
            times = {}
            for slug, iso in raw.items():
                if (when := dt_util.parse_datetime(iso)) is not None:
                    times[slug] = when
            return times

        self._open_since = _parse_times(stored.get("open_since", {}))
        self._close_since = _parse_times(stored.get("close_since", {}))
        self._acked_open = set(stored.get("acked_open", []))
        self._acked_close = set(stored.get("acked_close", []))
        self._notified_open = set(stored.get("notified_open", []))
        self._notified_close = set(stored.get("notified_close", []))
        if snoozed_on := stored.get("snoozed_on"):
            self._snoozed_on = dt_util.parse_date(snoozed_on)

    # --- Snooze -----------------------------------------------------------

    @property
    def is_snoozed(self) -> bool:
        return self._snoozed_on == dt_util.now().date()

    async def async_set_snooze(self, snoozed: bool) -> None:
        self._snoozed_on = dt_util.now().date() if snoozed else None
        if snoozed:
            await self._async_clear_notifications()
        self._schedule_save()
        self.async_update_listeners()
        await self.async_request_refresh()

    # --- Evaluation -------------------------------------------------------

    def _float_states(self, entity_ids: list[str]) -> list[float]:
        values = []
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            try:
                values.append(float(state.state))
            except ValueError:
                continue
        return values

    def _language(self) -> str:
        lang = self.config.get(CONF_LANGUAGE, LANG_AUTO)
        if lang == LANG_AUTO:
            lang = LANG_DE if (self.hass.config.language or "en").startswith("de") else "en"
        return lang

    async def _async_update_forecast(self) -> None:
        """Fetch today's forecast high, at most every FORECAST_MAX_AGE."""
        entity_id = self.config.get(CONF_WEATHER_ENTITY)
        if not entity_id:
            self.forecast_high = None
            return
        now = dt_util.utcnow()
        if (
            self._forecast_fetched is not None
            and now - self._forecast_fetched < FORECAST_MAX_AGE
        ):
            return
        self._forecast_fetched = now
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
            forecast = response[entity_id]["forecast"]
            self.forecast_high = float(forecast[0]["temperature"])
        except Exception:  # noqa: BLE001 - a broken weather entity must not kill updates
            _LOGGER.debug("Could not read forecast from %s", entity_id, exc_info=True)
            self.forecast_high = None

    async def _async_update_data(self) -> dict[str, RoomState]:
        now = dt_util.utcnow()
        delay = timedelta(
            minutes=self.config.get(CONF_DELAY_MINUTES, DEFAULT_DELAY_MINUTES)
        )
        min_diff = float(self.config.get(CONF_MIN_DIFF, DEFAULT_MIN_DIFF))
        indoor_min = float(
            self.config.get(CONF_INDOOR_MIN_TEMP, DEFAULT_INDOOR_MIN_TEMP)
        )
        humidity_max = float(
            self.config.get(CONF_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)
        )

        outdoor_values = self._float_states(self.config.get(CONF_OUTDOOR_SENSORS, []))
        self.outdoor_temp = max(outdoor_values) if outdoor_values else None
        # Worst case (max temp, max humidity) so we never overpromise drying
        outdoor_humidity_values = self._float_states(
            self.config.get(CONF_OUTDOOR_HUMIDITY_SENSORS, [])
        )
        self.outdoor_humidity = (
            max(outdoor_humidity_values) if outdoor_humidity_values else None
        )
        self.outdoor_dew_point = _dew_point(self.outdoor_temp, self.outdoor_humidity)
        await self._async_update_forecast()

        data: dict[str, RoomState] = {}
        for room in self.rooms:
            name = room[CONF_ROOM_NAME]
            slug = slugify(name)
            state = RoomState(name=name, slug=slug)

            indoor_values = self._float_states(room.get(CONF_INDOOR_SENSORS, []))
            state.temp_in = min(indoor_values) if indoor_values else None

            humidity_values = self._float_states(room.get(CONF_HUMIDITY_SENSORS, []))
            state.humidity = max(humidity_values) if humidity_values else None
            state.dew_point = _dew_point(state.temp_in, state.humidity)

            window_entities = room.get(CONF_WINDOW_SENSORS, [])
            for entity_id in window_entities:
                window = self.hass.states.get(entity_id)
                if window is not None and window.state == "on":
                    state.open_window_names.append(
                        window.attributes.get("friendly_name", entity_id)
                    )

            outdoor_cooler = (
                self.outdoor_temp is not None
                and state.temp_in is not None
                and self.outdoor_temp < state.temp_in
            )
            temp_condition = (
                self.outdoor_temp is not None
                and state.temp_in is not None
                and state.temp_in - self.outdoor_temp >= min_diff
                and state.temp_in >= indoor_min
            )
            # Ventilating only dries the room if the air outside carries less
            # moisture. With outdoor humidity sensors we compare dew points;
            # without them, "cooler outside" is the best approximation.
            if self.outdoor_dew_point is not None and state.dew_point is not None:
                drying_possible = (
                    state.dew_point - self.outdoor_dew_point >= DEW_POINT_MIN_DIFF
                )
            else:
                drying_possible = outdoor_cooler
            humidity_condition = (
                state.humidity is not None
                and state.humidity >= humidity_max
                and drying_possible
            )
            open_condition = not state.open_window_names and (
                temp_condition or humidity_condition
            )
            close_condition = (
                bool(window_entities)
                and bool(state.open_window_names)
                and self.outdoor_temp is not None
                and state.temp_in is not None
                and self.outdoor_temp > state.temp_in
            )

            # The condition must hold continuously for the configured delay
            if open_condition:
                self._open_since.setdefault(slug, now)
                state.open_recommended = now - self._open_since[slug] >= delay
            else:
                self._open_since.pop(slug, None)
                self._acked_open.discard(slug)
            if close_condition:
                self._close_since.setdefault(slug, now)
                state.close_recommended = now - self._close_since[slug] >= delay
            else:
                self._close_since.pop(slug, None)
                self._acked_close.discard(slug)

            data[slug] = state

        await self._async_handle_notifications(data)
        self._schedule_save()
        return data

    # --- Notifications ----------------------------------------------------

    def _in_notify_window(self) -> bool:
        start = dt_util.parse_time(self.config.get(CONF_TIME_START, DEFAULT_TIME_START))
        end = dt_util.parse_time(self.config.get(CONF_TIME_END, DEFAULT_TIME_END))
        if start is None or end is None:
            return True
        now = dt_util.now().time()
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end

    def _room_text(self, room: RoomState) -> str:
        details = f"{_fmt(room.temp_in)} °C"
        if room.humidity is not None:
            details += f", {room.humidity:.0f} %"
        return f"{room.name} ({details})"

    def _hot_day_hint(self, lang: str) -> str:
        hot_day_temp = float(
            self.config.get(CONF_HOT_DAY_TEMP, DEFAULT_HOT_DAY_TEMP)
        )
        if self.forecast_high is None or self.forecast_high < hot_day_temp:
            return ""
        if lang == LANG_DE:
            return (
                f" Heute werden bis zu {_fmt(self.forecast_high)} °C erwartet –"
                " jetzt gut durchlüften."
            )
        return (
            f" Up to {_fmt(self.forecast_high)} °C expected today –"
            " a good moment to air out."
        )

    async def _async_handle_notifications(self, data: dict[str, RoomState]) -> None:
        open_set = {
            slug
            for slug, room in data.items()
            if room.open_recommended and slug not in self._acked_open
        }
        close_set = {
            slug
            for slug, room in data.items()
            if room.close_recommended and slug not in self._acked_close
        }

        if self.is_snoozed or not self._in_notify_window():
            # Never send while suppressed, but clear notifications whose
            # condition has fully lapsed so they don't linger overnight.
            if self._notified_open and not open_set:
                await self._async_clear(self._open_tag)
                self._notified_open = set()
            if self._notified_close and not close_set:
                await self._async_clear(self._close_tag)
                self._notified_close = set()
            return

        lang = self._language()
        out_txt = _fmt(self.outdoor_temp)

        if open_set != self._notified_open:
            if not open_set:
                await self._async_clear(self._open_tag)
            else:
                rooms_txt = ", ".join(
                    self._room_text(data[slug]) for slug in sorted(open_set)
                )
                if lang == LANG_DE:
                    title = "🪟 Jetzt lüften!"
                    message = (
                        f"Draußen sind es {out_txt} °C. "
                        f"Fenster öffnen in: {rooms_txt}."
                    )
                else:
                    title = "🪟 Time to ventilate!"
                    message = (
                        f"It is {out_txt} °C outside. "
                        f"Open the windows in: {rooms_txt}."
                    )
                message += self._hot_day_hint(lang)
                await self._async_send(title, message, self._open_tag, lang)
            self._notified_open = open_set

        if close_set != self._notified_close:
            if not close_set:
                await self._async_clear(self._close_tag)
            else:
                rooms_txt = ", ".join(
                    f"{data[slug].name} ({', '.join(data[slug].open_window_names)})"
                    for slug in sorted(close_set)
                )
                if lang == LANG_DE:
                    title = "🪟 Fenster schließen!"
                    message = (
                        f"Draußen ist es mit {out_txt} °C wärmer als drinnen. "
                        f"Noch offen: {rooms_txt}."
                    )
                else:
                    title = "🪟 Close the windows!"
                    message = (
                        f"It is warmer outside ({out_txt} °C) than inside. "
                        f"Still open: {rooms_txt}."
                    )
                await self._async_send(title, message, self._close_tag, lang)
            self._notified_close = close_set

    async def _async_send(self, title: str, message: str, tag: str, lang: str) -> None:
        services = self.config.get(CONF_NOTIFY_SERVICES, [])
        if not services:
            persistent_notification.async_create(
                self.hass, message, title=title, notification_id=tag
            )
            return
        payload = {
            "title": title,
            "message": message,
            "data": {
                "tag": tag,
                "group": NOTIFICATION_GROUP,
                "actions": [
                    {
                        "action": self.done_action,
                        "title": "Erledigt" if lang == LANG_DE else "Done",
                    },
                    {
                        "action": self.snooze_action,
                        "title": "Heute nicht mehr"
                        if lang == LANG_DE
                        else "Not again today",
                    },
                ],
            },
        }
        for service in services:
            try:
                await self.hass.services.async_call("notify", service, payload)
            except Exception:  # noqa: BLE001 - a broken notifier must not kill updates
                _LOGGER.warning("Failed to send notification via notify.%s", service)

    async def _async_clear(self, tag: str) -> None:
        services = self.config.get(CONF_NOTIFY_SERVICES, [])
        if not services:
            persistent_notification.async_dismiss(self.hass, tag)
            return
        payload = {"message": "clear_notification", "data": {"tag": tag}}
        for service in services:
            try:
                await self.hass.services.async_call("notify", service, payload)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to clear notification via notify.%s", service)

    async def _async_clear_notifications(self) -> None:
        await self._async_clear(self._open_tag)
        await self._async_clear(self._close_tag)
        self._notified_open = set()
        self._notified_close = set()
