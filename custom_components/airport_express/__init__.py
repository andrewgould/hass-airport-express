"""Is something AirPlaying to this AirPort Express right now?

A gen-2 Express is a plain AirPlay/RAOP receiver: it never reports play state,
so Home Assistant's Apple TV integration can only ever show it as `idle`. What
the hardware *does* expose is a status-flags bit that flips while a stream is
open, on its mDNS TXT records and its /info endpoint alike. This integration
watches those and turns them into one binary_sensor.
"""

from __future__ import annotations

import asyncio

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_CONFIRM_OBSERVATIONS,
    CONF_INFO_POLL_SECONDS,
    CONF_MDNS_NAME,
    CONF_OFF_DELAY,
    DEFAULT_CONFIRM_OBSERVATIONS,
    DEFAULT_INFO_POLL_SECONDS,
    DEFAULT_OFF_DELAY,
    DOMAIN,
    PLATFORMS,
    SIGNAL_UPDATE,
)
from .models import DeviceConfig
from .monitor import DeviceMonitor


class AirPortExpressRuntime:
    """Holds the monitor, its tasks, and the latest activity state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        config = {**entry.data, **entry.options}
        self.device = DeviceConfig(
            name=config.get(CONF_NAME, "AirPort Express"),
            id=entry.entry_id,
            mdns_name=config.get(CONF_MDNS_NAME),
            ip=config.get(CONF_HOST),
            off_delay_seconds=config.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY),
            confirm_observations=config.get(
                CONF_CONFIRM_OBSERVATIONS, DEFAULT_CONFIRM_OBSERVATIONS
            ),
        )
        self.monitor = DeviceMonitor(
            device=self.device,
            info_poll_seconds=config.get(CONF_INFO_POLL_SECONDS, DEFAULT_INFO_POLL_SECONDS),
            on_state=self._handle_state,
            session=async_get_clientsession(hass),
        )
        self.active = False
        self._tasks: list[asyncio.Task] = []

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    def _handle_state(self, device: DeviceConfig, active: bool) -> None:
        self.active = active
        async_dispatcher_send(self.hass, self.signal)

    async def async_setup(self) -> None:
        # Share Home Assistant's own Zeroconf instance rather than opening a
        # second one: two browsers on the same multicast group in one process
        # is exactly the sort of thing that half-works.
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        await self.monitor.start(aiozc)
        self._tasks = [
            self.entry.async_create_background_task(
                self.hass, self.monitor.poll_loop(), f"{DOMAIN}_info_poll"
            ),
            self.entry.async_create_background_task(
                self.hass, self.monitor.tick_debouncer(), f"{DOMAIN}_debounce_tick"
            ),
        ]

    async def async_unload(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        await self.monitor.close()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = AirPortExpressRuntime(hass, entry)
    await runtime.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime: AirPortExpressRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.async_unload()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: reload so the debounce settings are rebuilt cleanly."""
    await hass.config_entries.async_reload(entry.entry_id)
