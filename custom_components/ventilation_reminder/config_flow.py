"""Config flow for the Ventilation Reminder integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

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
    DOMAIN,
    LANG_AUTO,
    LANG_DE,
    LANG_EN,
)

CONF_ROOM = "room"


def _global_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    """Schema for the global settings, shared by setup and options flow."""
    notify_services = sorted(hass.services.async_services().get("notify", {}))
    return vol.Schema(
        {
            vol.Required(
                CONF_OUTDOOR_SENSORS, default=defaults.get(CONF_OUTDOOR_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature", multiple=True
                )
            ),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_SENSORS,
                default=defaults.get(CONF_OUTDOOR_HUMIDITY_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="humidity", multiple=True
                )
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICES, default=defaults.get(CONF_NOTIFY_SERVICES, [])
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_services,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_MIN_DIFF, default=defaults.get(CONF_MIN_DIFF, DEFAULT_MIN_DIFF)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=5,
                    step=0.5,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_INDOOR_MIN_TEMP,
                default=defaults.get(CONF_INDOOR_MIN_TEMP, DEFAULT_INDOOR_MIN_TEMP),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15,
                    max=30,
                    step=0.5,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_HUMIDITY_THRESHOLD,
                default=defaults.get(
                    CONF_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=40,
                    max=90,
                    step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_DELAY_MINUTES,
                default=defaults.get(CONF_DELAY_MINUTES, DEFAULT_DELAY_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=120,
                    step=1,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_TIME_START, default=defaults.get(CONF_TIME_START, DEFAULT_TIME_START)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_TIME_END, default=defaults.get(CONF_TIME_END, DEFAULT_TIME_END)
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_WEATHER_ENTITY,
                description={"suggested_value": defaults.get(CONF_WEATHER_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Required(
                CONF_HOT_DAY_TEMP,
                default=defaults.get(CONF_HOT_DAY_TEMP, DEFAULT_HOT_DAY_TEMP),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=20,
                    max=40,
                    step=0.5,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_LANGUAGE, default=defaults.get(CONF_LANGUAGE, LANG_AUTO)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[LANG_AUTO, LANG_EN, LANG_DE],
                    translation_key="language",
                )
            ),
        }
    )


def _apply_global_input(
    config: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    """Merge global settings, dropping optional keys the user cleared."""
    merged = {**config, **user_input}
    if CONF_WEATHER_ENTITY not in user_input:
        merged.pop(CONF_WEATHER_ENTITY, None)
    return merged


def _room_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Schema for adding or editing a room."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, vol.UNDEFINED)
            ): selector.TextSelector(),
            vol.Required(
                CONF_INDOOR_SENSORS,
                default=defaults.get(CONF_INDOOR_SENSORS, vol.UNDEFINED),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature", multiple=True
                )
            ),
            vol.Optional(
                CONF_HUMIDITY_SENSORS,
                default=defaults.get(CONF_HUMIDITY_SENSORS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="humidity", multiple=True
                )
            ),
            vol.Optional(
                CONF_WINDOW_SENSORS, default=defaults.get(CONF_WINDOW_SENSORS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    device_class=["window", "door", "opening"],
                    multiple=True,
                )
            ),
        }
    )


def _duplicate_room(
    rooms: list[dict[str, Any]], name: str, skip_index: int | None = None
) -> bool:
    """Check whether a room name (by slug) already exists."""
    new_slug = slugify(name)
    return any(
        slugify(room[CONF_ROOM_NAME]) == new_slug
        for index, room in enumerate(rooms)
        if index != skip_index
    )


class VentilationReminderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: global settings followed by adding one or more rooms."""

    VERSION = 1

    def __init__(self) -> None:
        self._global: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._global = _apply_global_input({}, user_input)
            return await self.async_step_add_room()
        return self.async_show_form(
            step_id="user", data_schema=_global_schema(self.hass, {})
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if _duplicate_room(self._rooms, user_input[CONF_ROOM_NAME]):
                errors["base"] = "room_exists"
            else:
                self._rooms.append(user_input)
                return await self.async_step_room_menu()
        return self.async_show_form(
            step_id="add_room", data_schema=_room_schema(), errors=errors
        )

    async def async_step_room_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="room_menu", menu_options=["add_room", "finish"]
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title="Ventilation Reminder",
            data={CONF_ROOMS: self._rooms, **self._global},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VentilationReminderOptionsFlow()


class VentilationReminderOptionsFlow(OptionsFlow):
    """Manage global settings and the dynamic list of rooms."""

    def __init__(self) -> None:
        self._edit_index: int | None = None

    def _config(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _rooms(self) -> list[dict[str, Any]]:
        return list(self._config().get(CONF_ROOMS, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "add_room", "edit_room", "remove_room"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data=_apply_global_input(self._config(), user_input)
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=_global_schema(self.hass, self._config()),
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            rooms = self._rooms()
            if _duplicate_room(rooms, user_input[CONF_ROOM_NAME]):
                errors["base"] = "room_exists"
            else:
                rooms.append(user_input)
                return self.async_create_entry(
                    title="", data={**self._config(), CONF_ROOMS: rooms}
                )
        return self.async_show_form(
            step_id="add_room", data_schema=_room_schema(), errors=errors
        )

    async def async_step_edit_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms = self._rooms()
        if not rooms:
            return self.async_abort(reason="no_rooms")
        if user_input is not None:
            self._edit_index = next(
                index
                for index, room in enumerate(rooms)
                if room[CONF_ROOM_NAME] == user_input[CONF_ROOM]
            )
            return await self.async_step_edit_room_details()
        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[room[CONF_ROOM_NAME] for room in rooms]
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_room", data_schema=schema)

    async def async_step_edit_room_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms = self._rooms()
        errors: dict[str, str] = {}
        if user_input is not None:
            if _duplicate_room(
                rooms, user_input[CONF_ROOM_NAME], skip_index=self._edit_index
            ):
                errors["base"] = "room_exists"
            else:
                rooms[self._edit_index] = user_input
                return self.async_create_entry(
                    title="", data={**self._config(), CONF_ROOMS: rooms}
                )
        return self.async_show_form(
            step_id="edit_room_details",
            data_schema=_room_schema(rooms[self._edit_index]),
            errors=errors,
        )

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms = self._rooms()
        if user_input is not None:
            keep = [
                room
                for room in rooms
                if room[CONF_ROOM_NAME] not in user_input[CONF_ROOMS]
            ]
            return self.async_create_entry(
                title="", data={**self._config(), CONF_ROOMS: keep}
            )
        if not rooms:
            return self.async_abort(reason="no_rooms")
        schema = vol.Schema(
            {
                vol.Required(CONF_ROOMS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[room[CONF_ROOM_NAME] for room in rooms],
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_room", data_schema=schema)
