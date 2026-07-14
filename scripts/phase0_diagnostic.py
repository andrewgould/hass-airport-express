#!/usr/bin/env python3
"""Phase 0 reverse-engineering logger.

Run this FIRST, against the real AirPort Express, before trusting the service.
It logs every TXT-record change for the device's ``_raop._tcp`` and
``_airplay._tcp`` services with timestamps, and periodically fetches the ``/info``
binary plist, so you can correlate the raw fields against what streaming was
actually doing.

Procedure
---------
1. Start this with your Express's mDNS name or IP:
       python scripts/phase0_diagnostic.py --name "Living Room"
       python scripts/phase0_diagnostic.py --ip 192.168.1.42
2. From a phone, run this sequence while watching the log, noting the wall-clock
   time you do each action:
       a. start an AirPlay stream to the Express
       b. stop it normally
       c. leave it idle a minute
       d. (if possible) pause mid-stream from a source that supports pause
       e. repeat a few times
3. Correlate: which field/bit flips exactly when streaming starts/stops? Which
   service (_raop vs _airplay) reacts first and most reliably? Do TXT and /info
   agree?
4. Encode the finding in src/hass_airport_express/state.py and capture a couple
   of representative records into tests/fixtures/ for the unit tests.

Output is line-per-event; tee it to captures/ for later analysis:
       python scripts/phase0_diagnostic.py --ip 192.168.1.42 | tee captures/run1.log
"""

from __future__ import annotations

import argparse
import asyncio
import plistlib
from datetime import UTC, datetime

import aiohttp
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

RAOP_TYPE = "_raop._tcp.local."
AIRPLAY_TYPE = "_airplay._tcp.local."


def ts() -> str:
    return datetime.now(UTC).astimezone().strftime("%H:%M:%S.%f")[:-3]


def matches(name: str, want_name: str | None) -> bool:
    return want_name is None or want_name.lower() in name.lower()


class Logger:
    def __init__(self, azc: AsyncZeroconf, want_name: str | None, want_ip: str | None):
        self._azc = azc
        self._name = want_name
        self._ip = want_ip

    def on_change(self, zc: Zeroconf, service_type: str, name: str,
                  state_change: ServiceStateChange) -> None:
        if not matches(name, self._name):
            return
        short = service_type.replace("._tcp.local.", "")
        if state_change is ServiceStateChange.Removed:
            print(f"{ts()}  {short:9}  REMOVED  {name}")
            return
        asyncio.ensure_future(self._dump(service_type, name, short, state_change))

    async def _dump(self, service_type, name, short, change):
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(self._azc.zeroconf, 3000):
            return
        addrs = ",".join(info.parsed_addresses())
        if self._ip and self._name is None and self._ip not in info.parsed_addresses():
            return
        props = info.decoded_properties if hasattr(info, "decoded_properties") else info.properties
        flat = " ".join(f"{k}={v!r}" for k, v in sorted(props.items(), key=lambda x: str(x[0])))
        print(f"{ts()}  {short:9}  {change.name.upper():8}  [{addrs}]  {flat}")


async def poll_info(ip: str, interval: float):
    url = f"http://{ip}:7000/info"
    while True:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as s, s.get(url) as r:
                body = await r.read()
            info = plistlib.loads(body)
            flags = info.get("statusFlags")
            interesting = {k: info.get(k) for k in ("statusFlags", "name", "model", "features")
                           if k in info}
            print(f"{ts()}  /info      statusFlags={flags!r}  {interesting}")
        except Exception as e:  # noqa: BLE001
            print(f"{ts()}  /info      ERROR {type(e).__name__}: {e}")
        await asyncio.sleep(interval)


async def main_async(args) -> None:
    print(f"# Phase 0 diagnostic — name={args.name!r} ip={args.ip!r} "
          f"info_interval={args.info_interval}s")
    print(f"# {'time':12}  {'service':9}  {'change':8}  data")
    azc = AsyncZeroconf()
    logger = Logger(azc, args.name, args.ip)
    browser = AsyncServiceBrowser(
        azc.zeroconf, [RAOP_TYPE, AIRPLAY_TYPE], handlers=[logger.on_change]
    )
    tasks = []
    if args.ip:
        tasks.append(asyncio.create_task(poll_info(args.ip, args.info_interval)))
    try:
        await asyncio.Event().wait()  # run until Ctrl-C
    finally:
        for t in tasks:
            t.cancel()
        await browser.async_cancel()
        await azc.async_close()


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--name", help="mDNS instance name substring to match (e.g. 'Living Room')")
    p.add_argument("--ip", help="device IP; enables the /info poll and IP-based matching")
    p.add_argument("--info-interval", type=float, default=10.0,
                   help="seconds between /info polls (default 10; use a low value for Phase 0)")
    args = p.parse_args()
    if not args.name and not args.ip:
        p.error("provide at least --name or --ip")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n# stopped")


if __name__ == "__main__":
    main()
