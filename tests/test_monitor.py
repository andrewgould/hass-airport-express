"""Regression tests for DeviceMonitor's tick/record wiring.

These caught a real bug found against live hardware on 2026-07-19: mDNS TXT
updates are edge-triggered (they only fire when the value changes), so a
sustained, unchanging "streaming" reading produces exactly ONE event, not a
steady stream of them. The periodic tick used to feed the debouncer a bare
"no information" signal every second, which let off_delay_seconds elapse and
falsely report OFF mid-stream, then immediately flip back ON once the next
confirming observation arrived (because the internal streak counter was never
reset by an explicit "false" reading) -- producing exactly the ~20s ON/OFF
flapping seen in production. The fix: re-derive the combined state from cached
per-source observations on every tick instead of feeding raw None.
"""

from __future__ import annotations

import asyncio

from hass_airport_express import state
from hass_airport_express.config import DeviceConfig
from hass_airport_express.monitor import DeviceMonitor


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def _device(**kw) -> DeviceConfig:
    base = dict(name="Test", id="test", ip="1.2.3.4", off_delay_seconds=20,
                confirm_observations=1)
    base.update(kw)
    return DeviceConfig(**base)


def test_tick_reaffirms_cached_active_state_past_off_delay():
    """A source that's still (cached) active must NOT time out to OFF just
    because no NEW mDNS event has arrived within off_delay_seconds -- that's
    the normal, expected behaviour for a sustained, unchanging stream."""

    async def _run() -> list[bool]:
        clock = FakeClock()
        device = _device(off_delay_seconds=20)
        events: list[bool] = []
        mon = DeviceMonitor(
            device, info_poll_seconds=999, on_state=lambda d, a: events.append(a),
            monotonic=clock,
        )
        await mon._record(state.Observation("airplay", True, "0x804"))
        assert events == [True]

        # simulate 30s of ticks with no new mDNS event (mirrors a real,
        # unchanging, still-active stream) -- must stay ON
        for _ in range(30):
            clock.advance(1)
            await mon._tick_once()
        return events

    assert asyncio.run(_run()) == [True]


def test_tick_still_clears_after_genuine_stop():
    """Once the real signal actually goes inactive, the off-delay must still
    clear the sensor after off_delay_seconds -- the fix must not make it stick
    on forever."""

    async def _run() -> list[bool]:
        clock = FakeClock()
        device = _device(off_delay_seconds=20)
        events: list[bool] = []
        mon = DeviceMonitor(
            device, info_poll_seconds=999, on_state=lambda d, a: events.append(a),
            monotonic=clock,
        )
        await mon._record(state.Observation("airplay", True, "0x804"))
        for _ in range(10):
            clock.advance(1)
            await mon._tick_once()

        await mon._record(state.Observation("airplay", False, "0x4"))
        clock.advance(21)
        await mon._tick_once()
        return events

    assert asyncio.run(_run()) == [True, False]
