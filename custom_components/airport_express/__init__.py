"""Is something AirPlaying to this AirPort Express right now?

A gen-2 Express is a plain AirPlay/RAOP receiver: it never reports play state,
so Home Assistant's Apple TV integration can only ever show it as `idle`. What
the hardware *does* expose is a status-flags bit that flips while a stream is
open, on its mDNS TXT records and its /info endpoint alike. This integration
watches those and turns them into one binary_sensor.

It also offers two actions, `airport_express.join` and `airport_express.unjoin`,
that add the Express to (or take it out of) a HomePod's playback - see
grouping.py.
"""

from __future__ import annotations

import asyncio
import re

import voluptuous as vol
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service import async_extract_entity_ids
from homeassistant.helpers.typing import ConfigType

from . import grouping
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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_JOIN = "join"
SERVICE_UNJOIN = "unjoin"
ATTR_LEADER = "leader"
GROUPING_SCHEMA = cv.make_entity_service_schema({vol.Required(ATTR_LEADER): cv.entity_id})

# A zeroconf-discovered entry's unique_id is the AirPlay deviceid - the MAC,
# which is exactly what a leader groups by. A hand-added one is keyed by host.
_MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


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
        self._airplay_id: str | None = None

    async def async_airplay_id(self) -> str:
        """The id a HomePod uses for this Express in its list of output devices."""
        if self._airplay_id is None:
            unique_id = (self.entry.unique_id or "").upper()
            if _MAC.match(unique_id):
                self._airplay_id = unique_id
            else:
                self._airplay_id = await grouping.async_express_identifier(
                    self.hass, self.device.ip or self.device.mdns_name
                )
        return self._airplay_id

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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _grouping(call: ServiceCall) -> ServiceResponse:
        registry = er.async_get(hass)
        runtimes: dict[str, AirPortExpressRuntime] = {}
        for entity_id in await async_extract_entity_ids(call):
            entity = registry.async_get(entity_id)
            if entity and entity.platform == DOMAIN and entity.config_entry_id:
                runtime = hass.data.get(DOMAIN, {}).get(entity.config_entry_id)
                if runtime is not None:
                    runtimes[entity_id] = runtime
        if not runtimes:
            raise ServiceValidationError("Target an AirPort Express AirPlay activity entity")

        act = grouping.async_join if call.service == SERVICE_JOIN else grouping.async_unjoin
        changed = {}
        for entity_id, runtime in runtimes.items():
            express_id = await runtime.async_airplay_id()
            changed[entity_id] = await act(hass, call.data[ATTR_LEADER], express_id)
        return {"changed": changed}

    for service in (SERVICE_JOIN, SERVICE_UNJOIN):
        hass.services.async_register(
            DOMAIN,
            service,
            _grouping,
            schema=GROUPING_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


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
