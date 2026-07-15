# Ventilation Reminder

A Home Assistant custom integration that notifies you when it is cooler
outside than inside and ventilating is worthwhile — room-aware, with window
contact and humidity sensors, actionable notifications and English/German
texts.

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=C0d3Br3aker&repository=Ventilation-Reminder&category=integration)

## Features

- **Open reminder**: When the warmest outdoor temperature is at least the
  configured difference below a room's coolest temperature, the room is
  warmer than the indoor threshold and all its windows are closed — after
  the delay you get **one** notification listing every affected room, e.g.
  *"It is 19.5 °C outside. Open the windows in: Living room (24.3 °C),
  Bedroom (25.1 °C)."* The message updates as rooms are added and disappears
  automatically once all windows are open.
- **Humidity support**: Rooms with humidity sensors are also flagged when
  the humidity reaches the configurable threshold and ventilating would
  actually dry the room — even below the temperature thresholds. With
  outdoor humidity sensors configured this uses a real **dew point
  comparison** (Magnus formula, outdoor dew point at least 1 K below the
  room's); without them, "cooler outside" is used as an approximation.
- **Close reminder**: If windows are open and it gets warmer outside than
  inside again, one aggregated reminder lists the rooms and their open
  windows.
- **Hot day hint**: With a weather entity configured, the open reminder
  mentions when a hot day is expected — a nudge to air out early.
- **Action buttons**: **Done** dismisses the notification on all devices and
  suppresses it until the situation changes. **Not again today** snoozes all
  reminders until midnight.
- **Snooze switch**: also usable from dashboards and other automations,
  resets at midnight, survives restarts.
- **One device per room** with a `binary_sensor` (localized names) exposing
  indoor temperature/humidity, indoor and outdoor dew point, outdoor
  temperature/humidity, forecast high, open windows and the close
  recommendation as attributes.
- **Quiet hours** and **notification language** (English/German/follow HA
  language) are configurable. Reminders that lapse during quiet hours are
  still cleared from your devices.
- **Works without a phone**: with no notify service configured, reminders
  appear as Home Assistant persistent notifications.
- **Unlimited rooms**, managed via the UI — add, edit or remove rooms at any
  time; delay timers and dismissals survive restarts and reloads.

## Installation

### HACS (recommended)

1. Click the badge above (or add
   `https://github.com/C0d3Br3aker/Ventilation-Reminder` manually in HACS as
   a custom repository, category *Integration*) and install
   **Ventilation Reminder**.
2. Restart Home Assistant.

### Manual

1. Copy `custom_components/ventilation_reminder/` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

Requires Home Assistant 2024.11 or newer.

## Configuration

1. **Settings → Devices & Services → Add Integration → Ventilation
   Reminder**: configure outdoor sensors, notify services (e.g.
   `mobile_app_<your_phone>`), thresholds, quiet hours, an optional weather
   entity and the language.
2. The setup then asks you to **add rooms** right away: name, indoor
   temperature sensors, optional humidity sensors and optional window
   contact sensors per room. Add as many rooms as you like before finishing.
3. Rooms can be added, edited or removed later at any time via the
   integration's **Configure** dialog.

| Setting | Description | Default |
| --- | --- | --- |
| Outdoor temperature sensors | one or more, shared by all rooms | – |
| Outdoor humidity sensors | optional, enables the dew point comparison for humidity reminders | – |
| Notify services | mobile devices via the HA companion app; empty = persistent notifications | – |
| Minimum temperature difference | how much cooler it must be outside (hysteresis) | 1 °C |
| Indoor threshold temperature | only remind above this room temperature (prevents winter spam) | 23 °C |
| Humidity threshold | flag rooms with humidity sensors at or above this value | 65 % |
| Delay | condition must hold continuously for this long | 10 min |
| Do not disturb before / after | time window for notifications | 07:00–22:30 |
| Weather entity | optional, enables the hot day hint | – |
| Hot day threshold | forecast high that counts as a hot day | 25 °C |
| Notification language | English, German or follow the HA language | auto |

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest tests/ -q
```

CI runs [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest),
HACS validation and the test suite on every push.
