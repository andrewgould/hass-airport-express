"""Config flow: the zeroconf path is the one people will actually use."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_express.const import CONF_MDNS_NAME, CONF_OFF_DELAY, DOMAIN


@pytest.fixture(autouse=True)
def stub_setup():
    """Creating an entry shouldn't start a real mDNS browser in a unit test."""
    with patch("custom_components.airport_express.async_setup_entry", return_value=True):
        yield


DISCOVERY = ZeroconfServiceInfo(
    ip_address="192.168.1.137",
    ip_addresses=["192.168.1.137"],
    hostname="Court-yard.local.",
    name="Court yard._airplay._tcp.local.",
    port=7000,
    type="_airplay._tcp.local.",
    properties={"model": "AirPort10,115", "deviceid": "48:A1:95:E5:03:9A", "flags": "0x4"},
)


async def test_zeroconf_discovery_offers_the_express(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["name"] == "Court yard"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Court yard"
    assert result["data"][CONF_HOST] == "192.168.1.137"
    assert result["data"][CONF_MDNS_NAME] == "Court yard"


async def test_discovery_of_an_already_configured_express_is_dropped(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Court yard", CONF_HOST: "10.0.0.9"},
                            unique_id="48:A1:95:E5:03:9A")
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=DISCOVERY
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # ...and the address it moved to is picked up on the way past.
    assert entry.data[CONF_HOST] == "192.168.1.137"


async def test_manual_entry_requires_a_host_or_an_mdns_name(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Court yard", CONF_HOST: "192.168.1.137"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.137"


async def test_options_flow_sets_the_debounce(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_NAME: "Court yard", CONF_HOST: "192.168.1.137"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OFF_DELAY: 30, "confirm_observations": 2, "info_poll_seconds": 45},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OFF_DELAY] == 30
