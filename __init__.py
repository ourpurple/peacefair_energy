import logging
import os
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DEVICES,
    DOMAIN,
    ENERGY_SENSOR,
    PROTOCOLS,
    STORAGE_PATH,
    UN_SUBDISCRIPT,
)
from .modbus import ModbusHub

SERVICE_RESET_ENERGY = "reset_energy"
PLATFORMS = ["sensor"]

RESET_ENERGY_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})

_LOGGER = logging.getLogger(__name__)


async def update_listener(hass: HomeAssistant, config_entry):
    scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = hass.data[config_entry.entry_id][COORDINATOR]
    coordinator.update_interval = timedelta(seconds=scan_interval)


async def _async_handle_reset_energy(hass: HomeAssistant, service: ServiceCall) -> None:
    entity_id = service.data[ATTR_ENTITY_ID]
    energy_sensors = hass.data.get(DOMAIN, {}).get(ENERGY_SENSOR, [])
    energy_sensor = next((sensor for sensor in energy_sensors if sensor.entity_id == entity_id), None)

    if energy_sensor is None:
        _LOGGER.warning("Energy sensor not found for reset service: %s", entity_id)
        return

    try:
        energy_sensor.coordinator.reset_energy()
        energy_sensor.reset()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Failed to reset energy for %s: %s", entity_id, err)


async def async_setup(hass: HomeAssistant, hass_config: dict):
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(DEVICES, [])
    domain_data.setdefault(ENERGY_SENSOR, [])

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_ENERGY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_ENERGY,
            _async_handle_reset_energy,
            schema=RESET_ENERGY_SCHEMA,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry):
    config = config_entry.data
    protocol = PROTOCOLS[config[CONF_PROTOCOL]]
    host = config[CONF_HOST]
    port = config[CONF_PORT]
    slave = config[CONF_SLAVE]
    scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    domain_data = hass.data.setdefault(DOMAIN, {})
    devices = domain_data.setdefault(DEVICES, [])
    domain_data.setdefault(ENERGY_SENSOR, [])
    if host not in devices:
        devices.append(host)

    entry_data = hass.data.setdefault(config_entry.entry_id, {})
    coordinator = PeacefairCoordinator(hass, protocol, host, port, slave, scan_interval)
    entry_data[COORDINATOR] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    entry_data[UN_SUBDISCRIPT] = config_entry.add_update_listener(update_listener)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry):
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    if not unload_ok:
        return False

    entry_data = hass.data.get(config_entry.entry_id, {})
    coordinator = entry_data.get(COORDINATOR)

    domain_data = hass.data.get(DOMAIN, {})
    devices = domain_data.get(DEVICES, [])
    host = config_entry.data[CONF_HOST]
    if host in devices:
        devices.remove(host)

    energy_sensors = domain_data.get(ENERGY_SENSOR, [])
    if coordinator is not None and energy_sensors:
        domain_data[ENERGY_SENSOR] = [
            sensor for sensor in energy_sensors if getattr(sensor, "coordinator", None) is not coordinator
        ]

    unsub = entry_data.get(UN_SUBDISCRIPT)
    if unsub is not None:
        unsub()

    hass.data.pop(config_entry.entry_id, None)

    storage_path = hass.config.path(STORAGE_PATH)
    record_file = hass.config.path(f"{STORAGE_PATH}/{config_entry.entry_id}_state.json")
    reset_file = hass.config.path(f"{STORAGE_PATH}/{config_entry.entry_id}_reset.json")
    if os.path.exists(record_file):
        os.remove(record_file)
    if os.path.exists(reset_file):
        os.remove(reset_file)
    if os.path.exists(storage_path) and len(os.listdir(storage_path)) == 0:
        os.rmdir(storage_path)

    if not domain_data.get(DEVICES):
        hass.services.async_remove(DOMAIN, SERVICE_RESET_ENERGY)

    return True


class PeacefairCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, protocol, host, port, slave, scan_interval):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._updates = None
        self._host = host
        self._hub = ModbusHub(protocol, host, port, slave)

    @property
    def host(self):
        return self._host

    def reset_energy(self):
        self._hub.reset_energy()
        if self.data is not None:
            self.data["energy"] = 0.0

    def set_update(self, update):
        self._updates = update

    async def _async_update_data(self):
        data = self.data if self.data is not None else {}
        data_update = self._hub.info_gather()
        if len(data_update) > 0:
            data = data_update
            _LOGGER.debug("Got Data %s", data)
            if self._updates is not None:
                self._updates()
        return data