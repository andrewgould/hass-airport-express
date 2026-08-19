"""The one entity this integration exists to provide."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AirPortExpressRuntime
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: AirPortExpressRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AirPlayActiveBinarySensor(entry, runtime)])


class AirPlayActiveBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_name = "AirPlay active"

    def __init__(self, entry: ConfigEntry, runtime: AirPortExpressRuntime) -> None:
        self._entry = entry
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_airplay_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.device.name,
            manufacturer="Apple",
            model="AirPort Express (gen 2)",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._runtime.signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._runtime.active

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """The raw per-source readings.

        Worth having in front of you: the sources can disagree briefly, and
        knowing which one saw what is the difference between diagnosing this
        in a minute and recapturing the whole thing.
        """
        attrs: dict[str, str] = {}
        for source, obs in self._runtime.monitor.latest.items():
            attrs[f"{source}_flags"] = obs.raw or "unknown"
            attrs[f"{source}_active"] = "unknown" if obs.active is None else str(obs.active)
        return attrs
