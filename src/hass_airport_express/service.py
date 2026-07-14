"""Top-level orchestration: wire config -> MQTT -> per-device monitors."""

from __future__ import annotations

import asyncio
import logging

from zeroconf.asyncio import AsyncZeroconf

from .config import Config
from .monitor import DeviceMonitor
from .mqtt import MqttPublisher

log = logging.getLogger(__name__)


async def run(cfg: Config) -> None:
    publisher = MqttPublisher(cfg.mqtt)
    publisher.connect()
    for device in cfg.devices:
        publisher.publish_discovery(device)

    azc = AsyncZeroconf()
    monitors = [
        DeviceMonitor(
            device=device,
            info_poll_seconds=cfg.options.info_poll_seconds,
            on_state=publisher.publish_state,
        )
        for device in cfg.devices
    ]

    tasks: list[asyncio.Task] = []
    try:
        for mon in monitors:
            await mon.start(azc)
            tasks.append(asyncio.create_task(mon.poll_loop()))
            tasks.append(asyncio.create_task(mon.tick_debouncer()))
        log.info("hass-airport-express running; watching %d device(s)", len(monitors))
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        for mon in monitors:
            await mon.close()
        await azc.async_close()
        publisher.disconnect()
