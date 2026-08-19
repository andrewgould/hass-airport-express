"""The entity, wired through a real config entry with the monitor stubbed."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_express import state
from custom_components.airport_express.const import DOMAIN

ENTRY_DATA = {CONF_NAME: "Court yard", CONF_HOST: "192.168.1.137"}


@pytest.fixture
def stub_monitor():
    """No real mDNS browser or /info poll; we drive the callback by hand."""
    with (
        patch("custom_components.airport_express.zeroconf.async_get_async_instance",
              new=AsyncMock(return_value=object())),
        patch("custom_components.airport_express.monitor.DeviceMonitor.start",
              new=AsyncMock(return_value=None)),
        patch("custom_components.airport_express.monitor.DeviceMonitor.poll_loop",
              new=AsyncMock(return_value=None)),
        patch("custom_components.airport_express.monitor.DeviceMonitor.tick_debouncer",
              new=AsyncMock(return_value=None)),
        patch("custom_components.airport_express.monitor.DeviceMonitor.close",
              new=AsyncMock(return_value=None)),
    ):
        yield


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_airplay_active"
    )
    assert entity_id is not None
    return entity_id


async def test_sensor_follows_the_monitor(hass, stub_monitor):
    entry = await _setup(hass)
    runtime = hass.data[DOMAIN][entry.entry_id]
    entity_id = _entity_id(hass, entry)

    assert hass.states.get(entity_id).state == "off"
    assert hass.states.get(entity_id).attributes["device_class"] == "sound"

    runtime._handle_state(runtime.device, True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"

    runtime._handle_state(runtime.device, False)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"


async def test_raw_flags_are_exposed_for_diagnosis(hass, stub_monitor):
    """When the sources disagree, you want to see which said what."""
    entry = await _setup(hass)
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.monitor._latest = {
        "airplay": state.Observation("airplay", True, "0x804"),
        "info": state.Observation("info", None, ""),
    }
    runtime._handle_state(runtime.device, True)
    await hass.async_block_till_done()

    attrs = hass.states.get(_entity_id(hass, entry)).attributes
    assert attrs["airplay_flags"] == "0x804"
    assert attrs["airplay_active"] == "True"
    assert attrs["info_active"] == "unknown"


async def test_unload_stops_the_monitor(hass, stub_monitor):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
