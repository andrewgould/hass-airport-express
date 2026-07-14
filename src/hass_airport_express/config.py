"""Configuration loading — YAML file overlaid with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MqttConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    discovery_prefix: str = "homeassistant"
    base_topic: str = "airport-express"
    client_id: str = "hass-airport-express"


@dataclass
class DeviceConfig:
    name: str
    id: str
    mdns_name: str | None = None
    ip: str | None = None
    off_delay_seconds: int = 20
    confirm_observations: int = 2

    def __post_init__(self) -> None:
        if not self.mdns_name and not self.ip:
            raise ValueError(
                f"device '{self.id}': at least one of mdns_name or ip is required"
            )


@dataclass
class Options:
    info_poll_seconds: int = 45
    log_level: str = "INFO"
    log_format: str = "json"


@dataclass
class Config:
    mqtt: MqttConfig
    devices: list[DeviceConfig]
    options: Options = field(default_factory=Options)


def _env(name: str, default=None):
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def load(path: str | os.PathLike | None = None) -> Config:
    """Load config from ``path`` (default ./config.yaml), applying env overrides."""
    path = Path(path or _env("CONFIG_PATH", "config.yaml"))
    data: dict = {}
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}

    m = data.get("mqtt", {})
    mqtt = MqttConfig(
        host=_env("MQTT_HOST", m.get("host")),
        port=int(_env("MQTT_PORT", m.get("port", 1883))),
        username=_env("MQTT_USERNAME", m.get("username")),
        password=_env("MQTT_PASSWORD", m.get("password")),
        discovery_prefix=_env("MQTT_DISCOVERY_PREFIX", m.get("discovery_prefix", "homeassistant")),
        base_topic=_env("MQTT_BASE_TOPIC", m.get("base_topic", "airport-express")),
        client_id=_env("MQTT_CLIENT_ID", m.get("client_id", "hass-airport-express")),
    )
    if not mqtt.host:
        raise ValueError("mqtt.host is required (set it in config.yaml or MQTT_HOST)")

    devices = [
        DeviceConfig(
            name=d["name"],
            id=d["id"],
            mdns_name=d.get("mdns_name"),
            ip=d.get("ip"),
            off_delay_seconds=int(d.get("off_delay_seconds", 20)),
            confirm_observations=int(d.get("confirm_observations", 2)),
        )
        for d in data.get("devices", [])
    ]
    if not devices:
        raise ValueError("at least one device must be configured under 'devices'")

    o = data.get("options", {})
    options = Options(
        info_poll_seconds=int(_env("INFO_POLL_SECONDS", o.get("info_poll_seconds", 45))),
        log_level=_env("LOG_LEVEL", o.get("log_level", "INFO")),
        log_format=_env("LOG_FORMAT", o.get("log_format", "json")),
    )

    return Config(mqtt=mqtt, devices=devices, options=options)
