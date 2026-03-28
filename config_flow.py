import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
)

from .const import (
    DEFAULT_PORT,
    DEFAULT_PROTOCOL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    PROTOCOLS,
)

_LOGGER = logging.getLogger(__name__)


class PeacefairEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Peacefair Energy Monitor."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not host:
                errors[CONF_HOST] = "host_required"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                user_input[CONF_HOST] = host
                return self.async_create_entry(title=host, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): vol.In(list(PROTOCOLS.keys())),
                vol.Required(CONF_HOST, default=""): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return PeacefairEnergyOptionsFlow(config_entry)


class PeacefairEnergyOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if scan_interval < 1 or scan_interval > 3600:
                errors[CONF_SCAN_INTERVAL] = "invalid_interval"
            else:
                return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        data_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)