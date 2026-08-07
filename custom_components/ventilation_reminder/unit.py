"""Temperature unit helpers.

All evaluation runs in °C, while everything the user sees - sensor readings,
configured thresholds and notification texts - can use any temperature unit
Home Assistant supports.
"""

from __future__ import annotations

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import TemperatureConverter

# Differences carry no offset: a °F step is 5/9 of a °C step, and °C and K
# differences are identical. TemperatureConverter would apply the offset too,
# so differences are scaled by hand.
FAHRENHEIT_DELTA_RATIO = 1.8


def to_celsius(value: float, unit: str | None) -> float | None:
    """Convert a reading to °C, or None if its unit is not a temperature."""
    if unit is None or unit == UnitOfTemperature.CELSIUS:
        return value
    try:
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
    except HomeAssistantError:
        return None


def from_celsius(value: float, unit: str) -> float:
    """Convert a °C value to the given unit."""
    return TemperatureConverter.convert(value, UnitOfTemperature.CELSIUS, unit)


def delta_to_celsius(value: float, unit: str) -> float:
    """Convert a temperature difference in the given unit to a °C difference."""
    if unit == UnitOfTemperature.FAHRENHEIT:
        return value / FAHRENHEIT_DELTA_RATIO
    return value


def delta_from_celsius(value: float, unit: str) -> float:
    """Convert a °C temperature difference to the given unit."""
    if unit == UnitOfTemperature.FAHRENHEIT:
        return value * FAHRENHEIT_DELTA_RATIO
    return value
