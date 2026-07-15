"""Constants for the Ventilation Reminder integration."""

DOMAIN = "ventilation_reminder"

CONF_OUTDOOR_SENSORS = "outdoor_sensors"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_MIN_DIFF = "min_diff"
CONF_INDOOR_MIN_TEMP = "indoor_min_temp"
CONF_DELAY_MINUTES = "delay_minutes"
CONF_TIME_START = "time_start"
CONF_TIME_END = "time_end"
CONF_LANGUAGE = "language"
CONF_ROOMS = "rooms"

CONF_ROOM_NAME = "name"
CONF_INDOOR_SENSORS = "indoor_sensors"
CONF_WINDOW_SENSORS = "window_sensors"

DEFAULT_MIN_DIFF = 1.0
DEFAULT_INDOOR_MIN_TEMP = 23.0
DEFAULT_DELAY_MINUTES = 10
DEFAULT_TIME_START = "07:00:00"
DEFAULT_TIME_END = "22:30:00"

LANG_AUTO = "auto"
LANG_EN = "en"
LANG_DE = "de"

UPDATE_INTERVAL_SECONDS = 60
