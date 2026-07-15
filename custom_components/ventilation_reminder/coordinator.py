"""Coordinator for the Ventilation Reminder integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_DELAY_MINUTES,
    CONF_INDOOR_MIN_TEMP,
    CONF_INDOOR_SENSORS,
    CONF_LANGUAGE,
    CONF_MIN_DIFF,
    CONF_NOTIFY_SERVICES,
    CONF_OUTDOOR_SENSORS,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_TIME_END,
    CONF_TIME_START,
    CONF_WINDOW_SENSORS,
    DEFAULT_DELAY_MINUTES,
    DEFAULT_INDOOR_MIN_TEMP,
    DEFAULT_MIN_DIFF,
    DEFAULT_TIME_END,
    DEFAULT_TIME_START,
    LANG_AUTO,
    LANG_DE,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ACTION_EVENT = "mobile_app_notification_action"
NOTIFICATION_GROUP = "ventilation_reminder"


@dataclass
class RoomState:
    """Evaluated state of a single room."""

    name: str
    slug: str
    temp_in: float | None = None
    open_window_names: list[str] = field(default_factory=list)
    open_recommended: bool = False
    close_recommended: bool = False


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "?"


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

        self._open_since: dict[str, datetime] = {}
        self._close_since: dict[str, datetime] = {}
        # Rooms dismissed via the "Done" button, until their condition resets
        self._acked_open: set[str] = set()
        self._acked_close: set[str] = set()
        # Rooms currently shown in the open/close notification
        self._notified_open: set[str] = set()
        self._notified_close: set[str] = set()
        self._snoozed_on: date | None = None

        suffix = entry.entry_id[:8]
        self.done_action = f"ventilation_done_{suffix}"
        self.snooze_action = f"ventilation_snooze_{suffix}"
        self._open_tag = f"ventilation_open_{suffix}"
        self._close_tag = f"ventilation_close_{suffix}"

    async def async_setup(self) -> None:
        """Subscribe to sensor state changes and notification actions."""
        entities: list[str] = list(self.config.get(CONF_OUTDOOR_SENSORS, []))
        for room in self.rooms:
            entities += room.get(CONF_INDOOR_SENSORS, [])
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
            await self.async_request_refresh()
        elif action == self.snooze_action:
            await self.async_set_snooze(True)

    # --- Snooze -----------------------------------------------------------

    @property
    def is_snoozed(self) -> bool:
        return self._snoozed_on == dt_util.now().date()

    async def async_set_snooze(self, snoozed: bool) -> None:
        self._snoozed_on = dt_util.now().date() if snoozed else None
        if snoozed:
            await self._async_clear_notifications()
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

    async def _async_update_data(self) -> dict[str, RoomState]:
        now = dt_util.utcnow()
        delay = timedelta(
            minutes=self.config.get(CONF_DELAY_MINUTES, DEFAULT_DELAY_MINUTES)
        )
        min_diff = float(self.config.get(CONF_MIN_DIFF, DEFAULT_MIN_DIFF))
        indoor_min = float(
            self.config.get(CONF_INDOOR_MIN_TEMP, DEFAULT_INDOOR_MIN_TEMP)
        )

        outdoor_values = self._float_states(self.config.get(CONF_OUTDOOR_SENSORS, []))
        self.outdoor_temp = max(outdoor_values) if outdoor_values else None

        data: dict[str, RoomState] = {}
        for room in self.rooms:
            name = room[CONF_ROOM_NAME]
            slug = slugify(name)
            state = RoomState(name=name, slug=slug)

            indoor_values = self._float_states(room.get(CONF_INDOOR_SENSORS, []))
            state.temp_in = min(indoor_values) if indoor_values else None

            window_entities = room.get(CONF_WINDOW_SENSORS, [])
            for entity_id in window_entities:
                window = self.hass.states.get(entity_id)
                if window is not None and window.state == "on":
                    state.open_window_names.append(
                        window.attributes.get("friendly_name", entity_id)
                    )

            open_condition = (
                self.outdoor_temp is not None
                and state.temp_in is not None
                and state.temp_in - self.outdoor_temp >= min_diff
                and state.temp_in >= indoor_min
                and not state.open_window_names
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

    async def _async_handle_notifications(self, data: dict[str, RoomState]) -> None:
        if self.is_snoozed or not self._in_notify_window():
            return
        lang = self._language()
        out_txt = _fmt(self.outdoor_temp)

        open_set = {
            slug
            for slug, room in data.items()
            if room.open_recommended and slug not in self._acked_open
        }
        if open_set != self._notified_open:
            if not open_set:
                await self._async_clear(self._open_tag)
            else:
                rooms_txt = ", ".join(
                    f"{data[slug].name} ({_fmt(data[slug].temp_in)} °C)"
                    for slug in sorted(open_set)
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
                await self._async_send(title, message, self._open_tag, lang)
            self._notified_open = open_set

        close_set = {
            slug
            for slug, room in data.items()
            if room.close_recommended and slug not in self._acked_close
        }
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
        for service in self.config.get(CONF_NOTIFY_SERVICES, []):
            try:
                await self.hass.services.async_call("notify", service, payload)
            except Exception:  # noqa: BLE001 - a broken notifier must not kill updates
                _LOGGER.warning("Failed to send notification via notify.%s", service)

    async def _async_clear(self, tag: str) -> None:
        payload = {"message": "clear_notification", "data": {"tag": tag}}
        for service in self.config.get(CONF_NOTIFY_SERVICES, []):
            try:
                await self.hass.services.async_call("notify", service, payload)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to clear notification via notify.%s", service)

    async def _async_clear_notifications(self) -> None:
        await self._async_clear(self._open_tag)
        await self._async_clear(self._close_tag)
        self._notified_open = set()
        self._notified_close = set()
