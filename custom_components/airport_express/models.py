"""Plain config object shared by the monitor and the decision function.

Deliberately not a Home Assistant type: monitor.py and state.py stay
framework-free so the whole detection path is unit-testable without a `hass`
fixture, exactly as it was when this shipped as a standalone service.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceConfig:
    name: str
    id: str
    mdns_name: str | None = None
    ip: str | None = None
    off_delay_seconds: int = 10
    confirm_observations: int = 2

    def __post_init__(self) -> None:
        if not self.mdns_name and not self.ip:
            raise ValueError(f"device '{self.id}': at least one of mdns_name or ip is required")
