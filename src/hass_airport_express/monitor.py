"""Per-device monitor: mDNS browsing, /info fallback poll, debounce, and the
plumbing that turns raw observations into debounced state changes.

The Zeroconf listener is intentionally thin — it just forwards TXT records to the
decision function in ``state.py``. All the "is it *really* on/off" judgement lives
in the debouncer so it's unit-testable without a network.
"""

from __future__ import annotations

import asyncio
import logging
import plistlib
import time
from collections.abc import Callable

import aiohttp
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from . import state
from .config import DeviceConfig

log = logging.getLogger(__name__)

RAOP_TYPE = "_raop._tcp.local."
AIRPLAY_TYPE = "_airplay._tcp.local."

# Callback invoked with the debounced, confirmed boolean whenever it changes.
StateCallback = Callable[[DeviceConfig, bool], None]


class Debouncer:
    """Hysteresis / off-delay so brief handshake blips don't flap the sensor.

    - Going ACTIVE requires ``confirm_observations`` consecutive active reads.
    - Going INACTIVE waits ``off_delay_seconds`` after the last active read.
    - A ``None`` observation (no information) is ignored — it neither confirms
      nor clears activity.

    ``monotonic`` is injectable so tests can drive time deterministically.
    """

    def __init__(
        self,
        device: DeviceConfig,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._now = monotonic
        self._reported: bool | None = None       # last value we told the world
        self._active_streak = 0
        self._last_active_at: float | None = None

    def observe(self, active: bool | None) -> bool | None:
        """Feed one combined observation; return a new reported state or None."""
        now = self._now()

        if active is True:
            self._active_streak += 1
            self._last_active_at = now
            if (
                self._reported is not True
                and self._active_streak >= self._device.confirm_observations
            ):
                self._reported = True
                return True
            return None

        if active is False:
            self._active_streak = 0
            if self._reported is True:
                # honour off-delay before clearing
                if (
                    self._last_active_at is not None
                    and now - self._last_active_at < self._device.off_delay_seconds
                ):
                    return None
                self._reported = False
                return False
            if self._reported is None:
                self._reported = False
                return False
            return None

        # active is None -> no information; if we're waiting to clear, re-check delay
        if (
            self._reported is True
            and self._last_active_at is not None
            and now - self._last_active_at >= self._device.off_delay_seconds
        ):
            self._reported = False
            return False
        return None


class DeviceMonitor:
    """Owns the mDNS browser + /info poller for a single Express."""

    def __init__(
        self,
        device: DeviceConfig,
        info_poll_seconds: int,
        on_state: StateCallback,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._info_poll_seconds = info_poll_seconds
        self._on_state = on_state
        self._debouncer = Debouncer(device, monotonic=monotonic)
        self._latest: dict[str, state.Observation] = {}
        self._lock = asyncio.Lock()
        self._browser: AsyncServiceBrowser | None = None
        self._azc: AsyncZeroconf | None = None

    # --- public API ----------------------------------------------------------
    async def start(self, azc: AsyncZeroconf) -> None:
        self._azc = azc
        self._browser = AsyncServiceBrowser(
            azc.zeroconf,
            [RAOP_TYPE, AIRPLAY_TYPE],
            handlers=[self._on_service_state_change],
        )
        log.info("watching mDNS for device %s", self._device.id)

    async def poll_loop(self) -> None:
        """Fallback /info cross-check. Self-heals missed multicast events."""
        while True:
            try:
                await self._poll_info_once()
            except Exception:  # noqa: BLE001 - never let the poll loop die
                log.exception("info poll failed for %s", self._device.id)
            await asyncio.sleep(self._info_poll_seconds)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()

    # --- mDNS ---------------------------------------------------------------
    def _matches(self, name: str) -> bool:
        if self._device.mdns_name:
            return self._device.mdns_name.lower() in name.lower()
        # No mDNS name configured -> we resolve and match on IP inside the handler.
        return True

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if not self._matches(name):
            return
        if state_change is ServiceStateChange.Removed:
            # Device dropped off the network — record as inactive (no info) and
            # let the debouncer's off-delay clear it rather than sticking "on".
            asyncio.ensure_future(self._record(state.Observation(
                "airplay" if service_type == AIRPLAY_TYPE else "raop", None, "removed"
            )))
            return
        asyncio.ensure_future(self._resolve_and_record(service_type, name))

    async def _resolve_and_record(self, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        assert self._azc is not None
        if not await info.async_request(self._azc.zeroconf, 3000):
            return
        # If matching by IP, confirm this resolved record is our device.
        if not self._device.mdns_name and self._device.ip:
            addrs = {addr for addr in info.parsed_addresses()}
            if self._device.ip not in addrs:
                return
        txt = info.decoded_properties if hasattr(info, "decoded_properties") else info.properties
        obs = (
            state.from_airplay_txt(txt)
            if service_type == AIRPLAY_TYPE
            else state.from_raop_txt(txt)
        )
        await self._record(obs)

    # --- /info fallback ------------------------------------------------------
    async def _poll_info_once(self) -> None:
        if not self._device.ip:
            return
        url = f"http://{self._device.ip}:7000/info"
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                body = await resp.read()
        try:
            info = plistlib.loads(body)
        except Exception:  # noqa: BLE001
            log.debug("could not parse /info plist for %s", self._device.id)
            return
        await self._record(state.from_info_plist(info))

    # --- fan-in --------------------------------------------------------------
    async def _record(self, obs: state.Observation) -> None:
        async with self._lock:
            self._latest[obs.source] = obs
            await self._reevaluate_locked()

    async def _reevaluate_locked(self) -> None:
        """Re-derive the combined state from cached per-source observations and
        feed it to the debouncer. Must be called with self._lock held.

        mDNS TXT updates are edge-triggered -- a source that's still actively
        streaming won't emit a new event while its value stays unchanged. Feeding
        the debouncer a live re-derivation (rather than a bare "no information")
        on every tick means a still-true cached observation keeps refreshing the
        off-delay clock, instead of the off-delay expiring mid-stream just
        because nothing NEW happened to arrive in the last off_delay_seconds.
        """
        combined = state.combine(list(self._latest.values()))
        changed = self._debouncer.observe(combined)
        if changed is not None:
            self._on_state(self._device, changed)

    async def tick_debouncer(self) -> None:
        """Periodically re-affirm state from cached observations. Cheap; run
        alongside poll_loop. Self-heals off-delay expiry (see _reevaluate_locked)
        and clears state once the Express genuinely goes silent (no cached
        observation refreshes as active for longer than off_delay_seconds)."""
        while True:
            await asyncio.sleep(1)
            await self._tick_once()

    async def _tick_once(self) -> None:
        async with self._lock:
            await self._reevaluate_locked()
