"""
修复版 ModbusHub for pymodbus >=3.0.0
动态适配 framer 导入问题。
"""
import logging
from pymodbus.client import ModbusTcpClient, ModbusUdpClient
from pymodbus.exceptions import ModbusIOException
import threading

_LOGGER = logging.getLogger(__name__)

# ========== 动态解决 pymodbus 3.x 的 framer 导入兼容性问题 ==========
def resolve_rtu_framer():
    """直接返回字符串 'rtu' 作为 framer 参数"""
    return 'rtu'

# 全局解析并保存结果
_MODBUS_RTU_FRAMER = resolve_rtu_framer()

# ====== 增强版：修复 ModbusRequest 导入 ======
try:
    # 尝试从新版 pymodbus 导入
    from pymodbus.pdu.requests import ModbusRequest
except ImportError:
    try:
        # 尝试从旧版位置导入
        from pymodbus.pdu import ModbusRequest
    except ImportError:
        # 如果都失败，创建一个基类
        class ModbusRequest:
            pass

# ====== 修复设备类常量导入 ======
try:
    from homeassistant.components.sensor import SensorDeviceClass
    DEVICE_CLASS_VOLTAGE = SensorDeviceClass.VOLTAGE
    DEVICE_CLASS_CURRENT = SensorDeviceClass.CURRENT
    DEVICE_CLASS_POWER = SensorDeviceClass.POWER
    DEVICE_CLASS_ENERGY = SensorDeviceClass.ENERGY
    DEVICE_CLASS_POWER_FACTOR = SensorDeviceClass.POWER_FACTOR
except ImportError:
    DEVICE_CLASS_VOLTAGE = "voltage"
    DEVICE_CLASS_CURRENT = "current"
    DEVICE_CLASS_POWER = "power"
    DEVICE_CLASS_ENERGY = "energy"
    DEVICE_CLASS_POWER_FACTOR = "power_factor"

from .const import(
    DEVICE_CLASS_FREQUENCY
)

HPG_SENSOR_TYPES = [
    DEVICE_CLASS_VOLTAGE,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_POWER_FACTOR,
    DEVICE_CLASS_FREQUENCY
]

class ModbusResetEnergyRequest(ModbusRequest):
    _rtu_frame_size = 4
    function_code = 0x42
    
    def __init__(self, **kwargs):
        try:
            super().__init__(**kwargs)
        except TypeError:
            # 最小化初始化
            pass

    def encode(self):
        return b''

    def get_response_pdu_size(self):
        return 4

    def __str__(self):
        return "ModbusResetEnergyRequest"

class ModbusHub:
    def __init__(self, protocol, host, port, slave):
        self._lock = threading.Lock()
        self._protocol = protocol
        self._host = host
        self._port = port
        self._slave = slave
        self._timeout = 2
        self._last_error_log = 0.0
        self._error_log_interval = 60.0

        _LOGGER.debug(
            f"Initialize ModbusHub: protocol={protocol}, host={host}, port={port}, slave={slave}"
        )
        self._client = self._create_client()

    def _create_client(self):
        if self._protocol == "rtuovertcp":
            return ModbusTcpClient(
                host=self._host,
                port=self._port,
                framer=_MODBUS_RTU_FRAMER,
                timeout=self._timeout,
            )
        if self._protocol == "rtuoverudp":
            return ModbusUdpClient(
                host=self._host,
                port=self._port,
                framer=_MODBUS_RTU_FRAMER,
                timeout=self._timeout,
            )
        raise ValueError(f"Unsupported protocol: {self._protocol}")

    def _is_connected(self):
        return bool(getattr(self._client, "connected", False))

    def _ensure_connected(self):
        if self._is_connected():
            return True
        return bool(self._client.connect())

    def _recreate_client(self):
        try:
            self._client.close()
        except Exception:
            pass
        self._client = self._create_client()

    def _log_connection_issue(self, level, message, exc):
        import time

        now = time.monotonic()
        if now - self._last_error_log >= self._error_log_interval:
            _LOGGER.log(level, "%s: %s", message, exc)
            self._last_error_log = now
        else:
            _LOGGER.debug("%s: %s", message, exc)

    def connect(self):
        with self._lock:
            return self._ensure_connected()

    def close(self):
        with self._lock:
            self._client.close()

    def read_holding_register(self):
        pass

    def _read_input_registers_once(self, address, count):
        try:
            _LOGGER.debug(
                "Call read_input_registers(address=%s, count=%s, device_id=%s)",
                address,
                count,
                self._slave,
            )
            return self._client.read_input_registers(
                address=address,
                count=count,
                device_id=self._slave,
            )
        except TypeError as e:
            error_msg = str(e)
            if "unexpected keyword argument 'device_id'" in error_msg:
                try:
                    _LOGGER.debug(
                        "Fallback unit arg: read_input_registers(address=%s, count=%s, unit=%s)",
                        address,
                        count,
                        self._slave,
                    )
                    return self._client.read_input_registers(
                        address=address,
                        count=count,
                        unit=self._slave,
                    )
                except TypeError:
                    try:
                        _LOGGER.debug(
                            "Fallback slave arg: read_input_registers(address=%s, count=%s, slave=%s)",
                            address,
                            count,
                            self._slave,
                        )
                        return self._client.read_input_registers(
                            address=address,
                            count=count,
                            slave=self._slave,
                        )
                    except TypeError:
                        _LOGGER.debug(
                            "Fallback positional args: read_input_registers(%s, %s)",
                            address,
                            count,
                        )
                        return self._client.read_input_registers(address, count)
            raise

    def read_input_registers(self, address, count):
        with self._lock:
            try:
                if not self._ensure_connected():
                    _LOGGER.debug("Unable to connect to %s:%s before read", self._host, self._port)
                    return None
                return self._read_input_registers_once(address, count)
            except Exception as first_error:
                self._log_connection_issue(
                    logging.DEBUG,
                    f"Read failed, reconnecting {self._host}:{self._port}",
                    first_error,
                )
                try:
                    self._recreate_client()
                    if not self._ensure_connected():
                        _LOGGER.debug("Reconnect failed to %s:%s", self._host, self._port)
                        return None
                    return self._read_input_registers_once(address, count)
                except Exception as second_error:
                    self._log_connection_issue(
                        logging.WARNING,
                        f"Read retry failed {self._host}:{self._port}",
                        second_error,
                    )
                    return None

    def reset_energy(self):
        """Reset energy counter on the device."""
        with self._lock:
            request = ModbusResetEnergyRequest()
            try:
                if not self._ensure_connected():
                    raise ConnectionError(f"Unable to connect to {self._host}:{self._port}")
                return self._client.execute(request)
            except Exception as first_error:
                self._log_connection_issue(
                    logging.WARNING,
                    f"Reset command failed, reconnecting {self._host}:{self._port}",
                    first_error,
                )
                self._recreate_client()
                if not self._ensure_connected():
                    raise ConnectionError(f"Reconnect failed to {self._host}:{self._port}")
                return self._client.execute(request)

    def info_gather(self):
        data = {}
        result = self.read_input_registers(0, 9)
        if result is None:
            return data

        if isinstance(result, ModbusIOException):
            _LOGGER.debug("Read failed with ModbusIOException")
            return data

        if hasattr(result, "isError") and result.isError():
            _LOGGER.debug("Read failed with Modbus error response: %s", result)
            return data

        registers = getattr(result, "registers", None)
        if registers is None or len(registers) != 9:
            reg_len = len(registers) if registers is not None else 0
            _LOGGER.debug("Read failed with invalid register length: %s", reg_len)
            return data

        data[DEVICE_CLASS_VOLTAGE] = registers[0] / 10
        data[DEVICE_CLASS_CURRENT] = ((registers[2] << 16) + registers[1]) / 1000
        data[DEVICE_CLASS_POWER] = ((registers[4] << 16) + registers[3]) / 10
        data[DEVICE_CLASS_ENERGY] = ((registers[6] << 16) + registers[5]) / 1000
        data[DEVICE_CLASS_FREQUENCY] = registers[7] / 10
        data[DEVICE_CLASS_POWER_FACTOR] = registers[8] / 100
        _LOGGER.debug("Read success: %s", data)
        return data