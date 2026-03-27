import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (CONF_HOST, CONF_PORT, CONF_PROTOCOL, CONF_SCAN_INTERVAL, CONF_SLAVE)
from .const import (DOMAIN, DEFAULT_PORT, DEFAULT_PROTOCOL, DEFAULT_SCAN_INTERVAL, DEFAULT_SLAVE, DEVICES, PROTOCOLS)

_LOGGER = logging.getLogger(__name__)


class PeacefairEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """处理 Peacefair 能量监视器的配置流。"""
    
    # Home Assistant 要求配置流必须显式声明 VERSION，且与 manifest.json 中的版本号逻辑关联。
    # 通常设置为 1，除非您在进行破坏性更新的版本迁移。
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """处理初始用户步骤（添加设备）。"""
        errors = {}

        if user_input is not None:
            # 输入验证：检查主机地址格式（简单验证）
            host = user_input[CONF_HOST].strip()
            if not host:
                errors[CONF_HOST] = "host_required"
            
            # 检查设备是否已存在（基于我们维护的列表）
            if not errors:
                existing_devices = self.hass.data.get(DOMAIN, {}).get(DEVICES, [])
                if host in existing_devices:
                    errors["base"] = "already_configured"
                else:
                    # 所有检查通过，创建配置条目
                    # 标题通常用于在UI中标识条目，这里使用主机地址
                    return self.async_create_entry(title=host, data=user_input)

        # 显示表单（首次访问或验证错误后）
        # 注意：`vol.In()` 需要传入一个列表
        data_schema = vol.Schema({
            vol.Required(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): vol.In(list(PROTOCOLS.keys())),
            vol.Required(CONF_HOST, default=""): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
            vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): vol.Coerce(int),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    # 注意：`async_get_options_flow` 方法现在是必需的，即使它只是返回一个流处理器。
    @staticmethod
    @config_entries.HANDLERS.register(DOMAIN)
    def async_get_options_flow(config_entry):
        """获取此配置条目的选项流处理器。"""
        return PeacefairEnergyOptionsFlow(config_entry)


class PeacefairEnergyOptionsFlow(config_entries.OptionsFlow):
    """处理 Peacefair 能量监视器的选项（设置）流。"""

    def __init__(self, config_entry):
        # 通常不需要调用父类的 __init__，或者调用时不带参数
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """管理选项。"""
        errors = {}
        if user_input is not None:
            # 验证扫描间隔
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if scan_interval < 1 or scan_interval > 3600:
                errors[CONF_SCAN_INTERVAL] = "invalid_interval"
            else:
                # 验证通过，保存选项
                return self.async_create_entry(title="", data=user_input)

        # 显示当前设置
        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        data_schema = vol.Schema({
            vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.Coerce(int),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors
        )