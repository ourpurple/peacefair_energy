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
        self._slave = slave
        
        _LOGGER.debug(f"初始化 ModbusHub: 协议={protocol}, 主机={host}, 端口={port}, 从站={slave}")
        
        # 创建客户端
        if protocol == "rtuovertcp":
            self._client = ModbusTcpClient(
                host=host,
                port=port,
                framer=_MODBUS_RTU_FRAMER,
                timeout=2
            )
        elif protocol == "rtuoverudp":
            self._client = ModbusUdpClient(
                host=host,
                port=port,
                framer=_MODBUS_RTU_FRAMER,
                timeout=2
            )
        else:
            raise ValueError(f"不支持的协议: {protocol}")
            
    def connect(self):
        with self._lock:
            self._client.connect()

    def close(self):
        with self._lock:
            self._client.close()

    def read_holding_register(self):
        pass

    def read_input_registers(self, address, count):
        """读取输入寄存器 - 根据方法签名使用关键字参数"""
        with self._lock:
            try:
                # 根据方法签名: (address: 'int', *, count: 'int' = 1, device_id: 'int' = 1, no_response_expected: 'bool' = False)
                # 使用关键字参数调用
                _LOGGER.debug(f"调用 read_input_registers(address={address}, count={count}, device_id={self._slave})")
                return self._client.read_input_registers(
                    address=address,
                    count=count,
                    device_id=self._slave
                )
            except TypeError as e:
                # 如果 device_id 参数不被接受，尝试其他参数名
                error_msg = str(e)
                if "unexpected keyword argument 'device_id'" in error_msg:
                    try:
                        # 尝试使用 unit 参数名
                        _LOGGER.debug(f"尝试使用 unit 参数: read_input_registers(address={address}, count={count}, unit={self._slave})")
                        return self._client.read_input_registers(
                            address=address,
                            count=count,
                            unit=self._slave
                        )
                    except TypeError as e2:
                        try:
                            # 尝试使用 slave 参数名
                            _LOGGER.debug(f"尝试使用 slave 参数: read_input_registers(address={address}, count={count}, slave={self._slave})")
                            return self._client.read_input_registers(
                                address=address,
                                count=count,
                                slave=self._slave
                            )
                        except TypeError as e3:
                            # 最后尝试只传递 address 和 count
                            _LOGGER.debug(f"尝试仅传递 address 和 count: read_input_registers({address}, {count})")
                            return self._client.read_input_registers(
                                address,
                                count
                            )
                else:
                    _LOGGER.error(f"读取寄存器失败: {e}")
                    raise

    def reset_energy(self):
        """重置电能计数"""
        with self._lock:
            # 创建自定义请求
            request = ModbusResetEnergyRequest()
            
            # 执行请求
            try:
                return self._client.execute(request)
            except Exception as e:
                _LOGGER.error(f"执行重置命令失败: {e}")
                raise

    def info_gather(self):
        data = {}
        try:
            result = self.read_input_registers(0, 9)
            if result is not None and not isinstance(result, ModbusIOException) \
                    and hasattr(result, 'registers') and result.registers is not None and len(result.registers) == 9:
                data[DEVICE_CLASS_VOLTAGE] = result.registers[0] / 10
                data[DEVICE_CLASS_CURRENT] = ((result.registers[2] << 16) + result.registers[1]) / 1000
                data[DEVICE_CLASS_POWER] = ((result.registers[4] << 16) + result.registers[3]) / 10
                data[DEVICE_CLASS_ENERGY] = ((result.registers[6] << 16) + result.registers[5]) / 1000
                data[DEVICE_CLASS_FREQUENCY] = result.registers[7] / 10
                data[DEVICE_CLASS_POWER_FACTOR] = result.registers[8] / 100
                _LOGGER.debug(f"成功读取数据: {data}")
                return data
            else:
                if result is None:
                    _LOGGER.debug(f"读取数据失败: 结果为 None")
                elif isinstance(result, ModbusIOException):
                    _LOGGER.debug(f"读取数据失败: ModbusIOException")
                else:
                    reg_len = len(result.registers) if hasattr(result, 'registers') and result.registers else 0
                    _LOGGER.debug(f"读取数据失败: 寄存器数据不完整，长度: {reg_len}")
                return data
        except Exception as e:
            _LOGGER.error(f"收集数据时出错: {e}")
            return data