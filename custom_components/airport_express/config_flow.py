"""Config flow: zeroconf discovery, or add one by hand."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_CONFIRM_OBSERVATIONS,
    CONF_INFO_POLL_SECONDS,
    CONF_MDNS_NAME,
    CONF_OFF_DELAY,
    DEFAULT_CONFIRM_OBSERVATIONS,
    DEFAULT_INFO_POLL_SECONDS,
    DEFAULT_OFF_DELAY,
    DOMAIN,
)


def _options_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_OFF_DELAY, default=defaults.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY)
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=600)),
            vol.Required(
                CONF_CONFIRM_OBSERVATIONS,
                default=defaults.get(CONF_CONFIRM_OBSERVATIONS, DEFAULT_CONFIRM_OBSERVATIONS),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            vol.Required(
                CONF_INFO_POLL_SECONDS,
                default=defaults.get(CONF_INFO_POLL_SECONDS, DEFAULT_INFO_POLL_SECONDS),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
        }
    )


class AirPortExpressConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """An AirPort Express announced itself on _airplay._tcp."""
        props = {k.lower(): v for k, v in discovery_info.properties.items()}
        # deviceid is the MAC and survives a DHCP change; fall back to the host.
        unique_id = props.get("deviceid") or discovery_info.host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.host})

        name = (discovery_info.name or "").split(".")[0] or "AirPort Express"
        self._discovered = {
            CONF_NAME: name,
            CONF_HOST: discovery_info.host,
            CONF_MDNS_NAME: name,
        }
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered[CONF_NAME], data=self._discovered
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovered[CONF_NAME],
                "host": self._discovered[CONF_HOST],
            },
        )

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_HOST) and not user_input.get(CONF_MDNS_NAME):
                errors["base"] = "need_host_or_name"
            else:
                await self.async_set_unique_id(
                    user_input.get(CONF_HOST) or user_input[CONF_MDNS_NAME]
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Court yard"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_MDNS_NAME): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AirPortExpressOptionsFlow()


class AirPortExpressOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema({**self.config_entry.data, **self.config_entry.options}),
        )
