"""airport_express.join / unjoin, with pyatv replaced by a fake HomePod."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pyatv.const import FeatureState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_express.const import DOMAIN

from .test_binary_sensor import _entity_id, stub_monitor  # noqa: F401

EXPRESS_ID = "48:A1:95:E5:03:9A"
KITCHEN = SimpleNamespace(name="Kitchen", identifier="FBD7CB02-B463-42E6-A136-905D71A58CDD")
EXPRESS = SimpleNamespace(name="Court yard", identifier=EXPRESS_ID)
LEADER = "media_player.kitchen_homepod"


class FakeHomePod:
    def __init__(self, outputs, feature=FeatureState.Available, obeys=True):
        self.audio = MagicMock()
        self.audio.output_devices = list(outputs)
        self.audio.add_output_devices = AsyncMock(side_effect=self._add)
        self.audio.remove_output_devices = AsyncMock(side_effect=self._remove)
        self.features = MagicMock()
        self.features.get_feature.return_value = SimpleNamespace(state=feature)
        self.closed = False
        self._obeys = obeys

    async def _add(self, *ids):
        if self._obeys:
            self.audio.output_devices += [EXPRESS for i in ids if i == EXPRESS_ID]

    async def _remove(self, *ids):
        if self._obeys:
            self.audio.output_devices = [
                d for d in self.audio.output_devices if d.identifier not in ids
            ]

    def close(self):
        self.closed = True
        return set()


@pytest.fixture
def homepod():
    return FakeHomePod([KITCHEN])


@pytest.fixture
def fake_pyatv(homepod):
    conf = MagicMock()
    conf.identifier = EXPRESS_ID
    with (
        patch("custom_components.airport_express.grouping.pyatv.scan",
              new=AsyncMock(return_value=[conf])) as scan,
        patch("custom_components.airport_express.grouping.pyatv.connect",
              new=AsyncMock(return_value=homepod)),
        patch("custom_components.airport_express.grouping.SETTLE_SECONDS", 0.05),
        patch("custom_components.airport_express.grouping.SETTLE_POLL", 0.01),
    ):
        yield SimpleNamespace(scan=scan, conf=conf)


async def test_join_waits_for_a_slow_leader(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    """Playing, the HomePod lists the new speaker ~5s after accepting it."""
    async def slow_add(*ids):
        async def later():
            await asyncio.sleep(0.02)
            homepod.audio.output_devices = [KITCHEN, EXPRESS]
        asyncio.get_running_loop().create_task(later())

    homepod.audio.add_output_devices.side_effect = slow_add
    entity_id = await _setup(hass)
    assert await _call(hass, "join", entity_id) == {"changed": {entity_id: True}}


async def _setup(hass, unique_id=EXPRESS_ID):
    express = MockConfigEntry(
        domain=DOMAIN, unique_id=unique_id,
        data={CONF_NAME: "Court yard", CONF_HOST: "192.168.1.137"},
    )
    express.add_to_hass(hass)
    apple_tv = MockConfigEntry(
        domain="apple_tv", data={"address": "192.168.1.116", "credentials": {}}
    )
    apple_tv.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "media_player", "apple_tv", "kitchen", config_entry=apple_tv,
        suggested_object_id="kitchen_homepod",
    )
    assert await hass.config_entries.async_setup(express.entry_id)
    await hass.async_block_till_done()
    return _entity_id(hass, express)


async def _call(hass, service, entity_id):
    return await hass.services.async_call(
        DOMAIN, service, {"entity_id": entity_id, "leader": LEADER},
        blocking=True, return_response=True,
    )


async def test_join_adds_the_express(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    entity_id = await _setup(hass)
    response = await _call(hass, "join", entity_id)
    assert response == {"changed": {entity_id: True}}
    homepod.audio.add_output_devices.assert_awaited_once_with(EXPRESS_ID)
    assert homepod.closed
    # The leader was scanned at the address in its Apple TV entry.
    assert fake_pyatv.scan.await_args.kwargs["hosts"] == ["192.168.1.116"]


async def test_join_is_a_no_op_when_already_grouped(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    homepod.audio.output_devices = [KITCHEN, EXPRESS]
    entity_id = await _setup(hass)
    assert await _call(hass, "join", entity_id) == {"changed": {entity_id: False}}
    homepod.audio.add_output_devices.assert_not_awaited()


async def test_unjoin_removes_the_express(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    homepod.audio.output_devices = [KITCHEN, EXPRESS]
    entity_id = await _setup(hass)
    assert await _call(hass, "unjoin", entity_id) == {"changed": {entity_id: True}}
    homepod.audio.remove_output_devices.assert_awaited_once_with(EXPRESS_ID)
    assert homepod.audio.output_devices == [KITCHEN]


async def test_unjoin_is_a_no_op_when_not_grouped(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    entity_id = await _setup(hass)
    assert await _call(hass, "unjoin", entity_id) == {"changed": {entity_id: False}}
    homepod.audio.remove_output_devices.assert_not_awaited()


async def test_hand_added_entry_scans_the_express_for_its_id(
    hass, stub_monitor, fake_pyatv, homepod  # noqa: F811
):
    entity_id = await _setup(hass, unique_id="192.168.1.137")
    await _call(hass, "join", entity_id)
    homepod.audio.add_output_devices.assert_awaited_once_with(EXPRESS_ID)
    hosts = [c.kwargs["hosts"] for c in fake_pyatv.scan.await_args_list]
    assert ["192.168.1.137"] in hosts


async def test_ignored_request_is_an_error(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    homepod._obeys = False
    entity_id = await _setup(hass)
    with pytest.raises(HomeAssistantError, match="still"):
        await _call(hass, "join", entity_id)
    assert homepod.closed


async def test_leader_without_output_device_support(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    homepod.features.get_feature.return_value = SimpleNamespace(state=FeatureState.Unsupported)
    entity_id = await _setup(hass)
    with pytest.raises(HomeAssistantError, match="can't take extra speakers"):
        await _call(hass, "join", entity_id)
    assert homepod.closed


async def test_leader_must_be_an_apple_tv_entity(hass, stub_monitor, fake_pyatv):  # noqa: F811
    entity_id = await _setup(hass)
    with pytest.raises(HomeAssistantError, match="not a media player from the Apple TV"):
        await hass.services.async_call(
            DOMAIN, "join", {"entity_id": entity_id, "leader": "media_player.nope"},
            blocking=True,
        )


async def test_leader_cannot_join_itself(hass, stub_monitor, fake_pyatv):  # noqa: F811
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "join", {"entity_id": LEADER, "leader": LEADER}, blocking=True,
        )


BEDROOM_PSI = "1E483618-ED2C-4A58-97D5-2C57ED0882A7"
BEDROOM = SimpleNamespace(name="Bedroom", identifier=BEDROOM_PSI)
BEDROOM_ENTITY = "media_player.bedroom_homepod"


def _add_bedroom(hass):
    entry = MockConfigEntry(
        domain="apple_tv", data={"address": "192.168.1.162", "credentials": {}}
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "media_player", "apple_tv", "bedroom", config_entry=entry,
        suggested_object_id="bedroom_homepod",
    )


def _bedroom_scans_with_psi(fake_pyatv, homepod):
    """The Bedroom HomePod is listed by its AirPlay psi, not its MAC."""
    fake_pyatv.conf.get_service.return_value = SimpleNamespace(properties={"psi": BEDROOM_PSI})

    async def add(*ids):
        homepod.audio.output_devices += [BEDROOM for i in ids if i == BEDROOM_PSI]

    homepod.audio.add_output_devices.side_effect = add


async def test_join_adds_another_homepod_by_its_psi(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    await _setup(hass)
    _add_bedroom(hass)
    _bedroom_scans_with_psi(fake_pyatv, homepod)
    response = await _call(hass, "join", BEDROOM_ENTITY)
    assert response == {"changed": {BEDROOM_ENTITY: True}}
    homepod.audio.add_output_devices.assert_awaited_once_with(BEDROOM_PSI)
    hosts = [c.kwargs["hosts"] for c in fake_pyatv.scan.await_args_list]
    assert ["192.168.1.162"] in hosts


async def test_unjoin_removes_another_homepod(hass, stub_monitor, fake_pyatv, homepod):  # noqa: F811
    await _setup(hass)
    _add_bedroom(hass)
    _bedroom_scans_with_psi(fake_pyatv, homepod)
    homepod.audio.output_devices = [KITCHEN, BEDROOM]
    assert await _call(hass, "unjoin", BEDROOM_ENTITY) == {"changed": {BEDROOM_ENTITY: True}}
    homepod.audio.remove_output_devices.assert_awaited_once_with(BEDROOM_PSI)
    assert homepod.audio.output_devices == [KITCHEN]


async def test_homepod_without_psi_falls_back_to_its_device_id(
    hass, stub_monitor, fake_pyatv, homepod  # noqa: F811
):
    await _setup(hass)
    _add_bedroom(hass)
    fake_pyatv.conf.get_service.return_value = None
    fake_pyatv.conf.identifier = "1E:48:36:18:ED:2C"
    homepod._obeys = False
    with pytest.raises(HomeAssistantError, match="still"):
        await _call(hass, "join", BEDROOM_ENTITY)
    homepod.audio.add_output_devices.assert_awaited_once_with("1E:48:36:18:ED:2C")
