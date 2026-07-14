"""Entry point: ``python -m hass_airport_express`` or the console script."""

from __future__ import annotations

import asyncio
import logging

from . import config, logging_setup, service

log = logging.getLogger(__name__)


def main() -> None:
    cfg = config.load()
    logging_setup.configure(cfg.options.log_level, cfg.options.log_format)
    log.info("starting hass-airport-express")
    try:
        asyncio.run(service.run(cfg))
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
