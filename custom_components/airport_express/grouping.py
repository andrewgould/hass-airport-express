"""Add a speaker to a HomePod's (or Apple TV's) playback, and take it out again.

The speaker is usually this Express, but since 1.2.0 it can also be another
HomePod from the Apple TV integration (say, the bedroom joining the kitchen).

The Express can't join anything by itself: an AirPlay receiver only plays what
it's sent. The HomePod is the one that sends, so grouping is a request to the
HomePod - "add this output device" - over its Media Remote Protocol, which is
what Control Center does when you tick a second speaker. pyatv exposes that as
`audio.add_output_devices` / `remove_output_devices`.

Home Assistant's Apple TV integration doesn't offer media_player.join for these
devices, so the leader's address and any pairing credentials are read from its
Apple TV config entry and a short-lived connection of our own is opened for
each call. HomePods accept it without pairing.
"""

from __future__ import annotations

import asyncio
import logging

import pyatv
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyatv.const import FeatureName, FeatureState, Protocol

_LOGGER = logging.getLogger(__name__)

APPLE_TV_DOMAIN = "apple_tv"
CONF_CREDENTIALS = "credentials"
SCAN_TIMEOUT = 5
# The HomePod reports the new group some time after it accepts the command:
# about 5s while it is playing, since it has to open a stream to the Express
# first. Wait up to this long for its output list to agree.
SETTLE_SECONDS = 20
SETTLE_POLL = 0.5


async def async_express_identifier(hass: HomeAssistant, host: str) -> str:
    """The Express's AirPlay device id (its MAC), which is what a leader groups by."""
    confs = await pyatv.scan(hass.loop, hosts=[host], timeout=SCAN_TIMEOUT)
    if not confs:
        raise HomeAssistantError(f"AirPort Express at {host} did not answer a scan")
    return confs[0].identifier


def _apple_tv_entry(hass: HomeAssistant, entity_id: str):
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.platform != APPLE_TV_DOMAIN or entity.config_entry_id is None:
        raise HomeAssistantError(
            f"{entity_id} is not a media player from the Apple TV integration"
        )
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None:
        raise HomeAssistantError(f"No Apple TV config entry for {entity_id}")
    return entry


async def _async_scan_apple_tv(hass: HomeAssistant, entity_id: str):
    entry = _apple_tv_entry(hass, entity_id)
    address = entry.data[CONF_ADDRESS]
    confs = await pyatv.scan(hass.loop, hosts=[address], timeout=SCAN_TIMEOUT)
    if not confs:
        raise HomeAssistantError(f"{entity_id} ({address}) did not answer a scan")
    return entry, confs[0]


async def async_homepod_identifier(hass: HomeAssistant, entity_id: str) -> str:
    """The id a leader lists this HomePod (or Apple TV) by among its output devices.

    That's the `psi` from its AirPlay TXT record, a UUID that starts with
    roughly its MAC (the Kitchen's FA:D7:CB:02:B4:63 is FBD7CB02-B463-...).
    An Express has no `psi` and is listed by its MAC, the AirPlay device id,
    so that's the fallback.
    """
    _, conf = await _async_scan_apple_tv(hass, entity_id)
    airplay = conf.get_service(Protocol.AirPlay)
    psi = airplay.properties.get("psi") if airplay is not None else None
    return psi or conf.identifier


async def _async_connect_leader(hass: HomeAssistant, leader_entity_id: str):
    entry, conf = await _async_scan_apple_tv(hass, leader_entity_id)
    for protocol, creds in entry.data.get(CONF_CREDENTIALS, {}).items():
        if creds and conf.get_service(Protocol(int(protocol))) is not None:
            conf.set_credentials(Protocol(int(protocol)), creds)

    atv = await pyatv.connect(conf, hass.loop, session=async_get_clientsession(hass))
    feature = atv.features.get_feature(FeatureName.AddOutputDevices)
    if feature.state != FeatureState.Available:
        await _async_close(atv)
        raise HomeAssistantError(
            f"{leader_entity_id} can't take extra speakers (AddOutputDevices is "
            f"{feature.state.name})"
        )
    return atv


async def _async_close(atv) -> None:
    tasks = atv.close()
    if tasks:
        await asyncio.wait(tasks, timeout=5)


def _members(atv) -> list[str]:
    return [device.identifier for device in atv.audio.output_devices]


async def _async_settle(atv, express_id: str, present: bool) -> bool:
    """Wait for the leader's output list to show the speaker in (or out of) it."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SETTLE_SECONDS
    while (express_id in _members(atv)) != present:
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(SETTLE_POLL)
    return True


async def async_join(hass: HomeAssistant, leader_entity_id: str, express_id: str) -> bool:
    """Add the speaker to the leader's playback. False if it was already there."""
    atv = await _async_connect_leader(hass, leader_entity_id)
    try:
        if express_id in _members(atv):
            return False
        await atv.audio.add_output_devices(express_id)
        if not await _async_settle(atv, express_id, present=True):
            raise HomeAssistantError(
                f"{leader_entity_id} accepted the request but after {SETTLE_SECONDS}s its "
                f"outputs are still {[d.name for d in atv.audio.output_devices]}"
            )
        _LOGGER.debug("Added %s to %s", express_id, leader_entity_id)
        return True
    finally:
        await _async_close(atv)


async def async_unjoin(hass: HomeAssistant, leader_entity_id: str, express_id: str) -> bool:
    """Take the speaker out of the leader's playback. False if it wasn't in it."""
    atv = await _async_connect_leader(hass, leader_entity_id)
    try:
        if express_id not in _members(atv):
            return False
        await atv.audio.remove_output_devices(express_id)
        if not await _async_settle(atv, express_id, present=False):
            raise HomeAssistantError(
                f"{leader_entity_id} accepted the request but after {SETTLE_SECONDS}s "
                f"still lists {express_id}"
            )
        _LOGGER.debug("Removed %s from %s", express_id, leader_entity_id)
        return True
    finally:
        await _async_close(atv)
