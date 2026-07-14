"""Unit tests for the decision + debounce logic.

The TXT/plist-field assertions are marked xfail until Phase 0 confirms the real
field/bit — they document the *shape* of what we'll assert and will be filled in
with captured fixtures. The debounce/hysteresis tests are real now: that logic is
hardware-independent and must be correct regardless of Phase 0.
"""

from __future__ import annotations

import pytest

from hass_airport_express import state
from hass_airport_express.config import DeviceConfig
from hass_airport_express.monitor import Debouncer


# --- combine() ---------------------------------------------------------------
def test_combine_any_active_wins():
    obs = [
        state.Observation("airplay", True, "x"),
        state.Observation("info", False, "y"),
    ]
    assert state.combine(obs) is True


def test_combine_all_inactive():
    obs = [state.Observation("airplay", False, "x"), state.Observation("info", False, "y")]
    assert state.combine(obs) is False


def test_combine_no_information_returns_none():
    obs = [state.Observation("raop", None, ""), state.Observation("info", None, "")]
    assert state.combine(obs) is None


# --- Debouncer: a fake clock so tests are deterministic ----------------------
class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def _device(**kw) -> DeviceConfig:
    base = dict(name="Test", id="test", ip="1.2.3.4", off_delay_seconds=20,
                confirm_observations=2)
    base.update(kw)
    return DeviceConfig(**base)


def test_debounce_requires_consecutive_active_to_turn_on():
    clock = FakeClock()
    d = Debouncer(_device(confirm_observations=2), monotonic=clock)
    assert d.observe(True) is None      # first active — not yet
    assert d.observe(True) is True      # second active — confirmed on


def test_debounce_off_delay_holds_before_clearing():
    clock = FakeClock()
    d = Debouncer(_device(confirm_observations=1, off_delay_seconds=20), monotonic=clock)
    assert d.observe(True) is True
    # inactive arrives, but within off-delay -> stay on
    clock.advance(5)
    assert d.observe(False) is None
    # after the delay elapses, a further inactive clears it
    clock.advance(20)
    assert d.observe(False) is False


def test_debounce_none_after_delay_clears_when_device_goes_silent():
    clock = FakeClock()
    d = Debouncer(_device(confirm_observations=1, off_delay_seconds=10), monotonic=clock)
    assert d.observe(True) is True
    clock.advance(11)
    # no new info at all, but off-delay expired -> clear
    assert d.observe(None) is False


def test_debounce_brief_blip_does_not_flap():
    """Selecting the device then immediately deselecting shouldn't report ON."""
    clock = FakeClock()
    d = Debouncer(_device(confirm_observations=2), monotonic=clock)
    assert d.observe(True) is None      # one blip — needs 2 to confirm
    assert d.observe(False) is False    # cleared to a definite off (first report)


# --- Field decoding: filled in once Phase 0 lands ----------------------------
@pytest.mark.xfail(reason="Phase 0 not complete: real sf bit/value unconfirmed")
def test_airplay_sf_streaming_detected_from_fixture():
    # TODO(phase0): load tests/fixtures/airplay_streaming.txt and assert True,
    # tests/fixtures/airplay_idle.txt and assert False, once captured.
    streaming = {"sf": "0x804"}
    idle = {"sf": "0x4"}
    assert state.from_airplay_txt(streaming).active is True
    assert state.from_airplay_txt(idle).active is False


def test_airplay_sf_unparseable_is_no_information():
    assert state.from_airplay_txt({"sf": "garbage"}).active is None
    assert state.from_airplay_txt({}).active is None
