# Ventilation Reminder

A Home Assistant custom integration that notifies you when it is cooler
outside than inside and ventilating is worthwhile — room-aware, with window
contact sensors, actionable notifications and English/German texts.

## Features

- **Open reminder**: When the warmest outdoor temperature is at least the
  configured difference below a room's coolest temperature, the room is
  warmer than the indoor threshold and all its windows are closed — after
  the delay you get **one** notification listing every affected room, e.g.
  *"It is 19.5 °C outside. Open the windows in: Living room (24.3 °C),
  Bedroom (25.1 °C)."* The message updates as rooms are added and disappears
  automatically once all windows are open.
- **Close reminder**: If windows are open and it gets warmer outside than
  inside again, one aggregated reminder lists the rooms and their open
  windows.
- **Action buttons**: **Done** dismisses the notification on all devices and
  suppresses it until the situation changes. **Not again today** snoozes all
  reminders until midnight.
- **Snooze switch**: `switch.ventilation_reminder_snooze_today` — also
  usable from dashboards and other automations, resets at midnight, survives
  restarts.
- **Per-room entities**: `binary_sensor.<room>_ventilation_recommended` with
  indoor/outdoor temperature, open windows and close recommendation as
  attributes.
- **Quiet hours** and **notification language** (English/German/follow HA
  language) are configurable.
- **Unlimited rooms**, managed via the UI — add or remove rooms at any time.

## Installation

### HACS (recommended)

1. In HACS, add `https://github.com/C0d3Br3aker/Ventilation-Reminder` as a
   custom repository (category *Integration*) and install
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
   `mobile_app_<your_phone>`), thresholds, quiet hours and language.
2. Open the integration's **Configure** dialog to **add rooms**: name,
   indoor temperature sensors and optional window contact sensors per room.

| Setting | Description | Default |
| --- | --- | --- |
| Outdoor temperature sensors | one or more, shared by all rooms | – |
| Notify services | mobile devices via the HA companion app | – |
| Minimum temperature difference | how much cooler it must be outside (hysteresis) | 1 °C |
| Indoor threshold temperature | only remind above this room temperature (prevents winter spam) | 23 °C |
| Delay | condition must hold continuously for this long | 10 min |
| Do not disturb before / after | time window for notifications | 07:00–22:30 |
| Notification language | English, German or follow the HA language | auto |
