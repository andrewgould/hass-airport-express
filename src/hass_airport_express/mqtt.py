"""MQTT publishing + Home Assistant discovery.

Topic + discovery-payload conventions deliberately mirror hass-shairport-sync so
the entity feels native alongside other AirPlay integrations.
"""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from .config import DeviceConfig, MqttConfig

log = logging.getLogger(__name__)

PAYLOAD_ON = "ON"
PAYLOAD_OFF = "OFF"
PAYLOAD_AVAILABLE = "online"
PAYLOAD_NOT_AVAILABLE = "offline"


class MqttPublisher:
    def __init__(self, cfg: MqttConfig) -> None:
        self._cfg = cfg
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.client_id,
        )
        if cfg.username:
            self._client.username_pw_set(cfg.username, cfg.password)
        # Service-level LWT: if the monitor dies, HA marks every entity unavailable.
        self._service_availability_topic = f"{cfg.base_topic}/status"
        self._client.will_set(
            self._service_availability_topic, PAYLOAD_NOT_AVAILABLE, qos=1, retain=True
        )

    # --- topic helpers -------------------------------------------------------
    def state_topic(self, device: DeviceConfig) -> str:
        return f"{self._cfg.base_topic}/{device.id}/state"

    def _discovery_topic(self, device: DeviceConfig) -> str:
        return f"{self._cfg.discovery_prefix}/binary_sensor/{device.id}/config"

    # --- lifecycle -----------------------------------------------------------
    def connect(self) -> None:
        self._client.connect(self._cfg.host, self._cfg.port)
        self._client.loop_start()
        self._client.publish(
            self._service_availability_topic, PAYLOAD_AVAILABLE, qos=1, retain=True
        )
        log.info("connected to MQTT broker %s:%s", self._cfg.host, self._cfg.port)

    def disconnect(self) -> None:
        self._client.publish(
            self._service_availability_topic, PAYLOAD_NOT_AVAILABLE, qos=1, retain=True
        )
        self._client.loop_stop()
        self._client.disconnect()

    # --- publishing ----------------------------------------------------------
    def publish_discovery(self, device: DeviceConfig) -> None:
        """Announce the binary_sensor so HA creates it automatically."""
        payload = {
            "name": device.name,
            "unique_id": f"airport_express_{device.id}",
            "state_topic": self.state_topic(device),
            "payload_on": PAYLOAD_ON,
            "payload_off": PAYLOAD_OFF,
            "device_class": "sound",
            "availability_topic": self._service_availability_topic,
            "payload_available": PAYLOAD_AVAILABLE,
            "payload_not_available": PAYLOAD_NOT_AVAILABLE,
            "device": {
                "identifiers": [f"airport_express_{device.id}"],
                "name": device.name,
                "manufacturer": "Apple",
                "model": "AirPort Express (gen 2)",
            },
        }
        self._client.publish(
            self._discovery_topic(device), json.dumps(payload), qos=1, retain=True
        )
        log.debug("published discovery for %s", device.id)

    def publish_state(self, device: DeviceConfig, active: bool) -> None:
        payload = PAYLOAD_ON if active else PAYLOAD_OFF
        # retain so HA gets the last state immediately on restart
        self._client.publish(self.state_topic(device), payload, qos=1, retain=True)
        log.info("%s -> %s", device.id, payload)
