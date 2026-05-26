# -*- coding: utf-8 -*-
"""
@brief 基于 DDC/CI 与 WMI 控制显示器亮度的命令行工具。
@note 外接显示器优先使用 DDC/CI，笔记本内屏可通过 Windows WMI 亮度接口控制。
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass

from lumina_logging import (
    add_logging_arguments,
    configure_lumina_logging,
    log_and_print,
)


PHYSICAL_MONITOR_DESCRIPTION_SIZE = 128
CCHDEVICENAME = 32
BRIGHTNESS_BACKEND_NONE = "none"
BRIGHTNESS_BACKEND_DDCCI = "ddcci"
BRIGHTNESS_BACKEND_WMI = "wmi"
# WMI 亮度设置立即生效的超时时间，单位为秒。
WMI_SET_BRIGHTNESS_TIMEOUT_SECONDS = 0
HMONITOR = wintypes.HANDLE
HDC = wintypes.HANDLE
LPMONITORRECT = ctypes.POINTER(wintypes.RECT)
LPDWORD = ctypes.POINTER(wintypes.DWORD)
thread_local_state = threading.local()
logger = logging.getLogger(__name__)


class PHYSICAL_MONITOR(ctypes.Structure):
    """
    @brief 表示 Windows 物理显示器句柄及其描述信息。
    @note 该结构与 dxva2.dll 中的 PHYSICAL_MONITOR 结构保持一致。
    """

    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * PHYSICAL_MONITOR_DESCRIPTION_SIZE),
    ]


class MONITORINFOEXW(ctypes.Structure):
    """
    @brief 表示 Windows 显示器扩展信息结构。
    @note 该结构用于从 HMONITOR 读取显示设备名。
    """

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * CCHDEVICENAME),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    """
    @brief 表示 Windows 显示设备枚举信息结构。
    @note 该结构用于读取显示器硬件 ID，以匹配 WMI 内屏亮度对象。
    """

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


@dataclass
class MonitorBrightnessInfo:
    """
    @brief 保存显示器亮度信息。
    @note backend 字段标记当前显示器使用的亮度控制后端。
    """

    index: int
    description: str
    minimum_value: int | None
    current_value: int | None
    maximum_value: int | None
    current_percentage: int | None
    supports_brightness: bool
    backend: str
    backend_key: str | None = None


@dataclass
class WmiBrightnessRecord:
    """
    @brief 保存 Windows WMI 内屏亮度对象信息。
    @note instance_name 用于后续调用 WmiSetBrightness 精确定位对象。
    """

    # WMI 对象实例名。
    instance_name: str
    # 当前亮度百分比，单位为 %。
    current_percentage: int
    # 显示器硬件 ID。
    hardware_id: str | None
    # 支持的亮度百分比档位，单位为 %。
    supported_levels: list[int]


@dataclass
class BrightnessSetResult:
    """
    @brief 保存一次亮度设置的执行结果。
    @note applied_percentage 可能因为显示器支持档位限制与 requested_percentage 不同。
    """

    description: str
    # 请求设置的亮度百分比，单位为 %。
    requested_percentage: int
    # 实际写入的亮度百分比，单位为 %。
    applied_percentage: int


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    HMONITOR,
    HDC,
    LPMONITORRECT,
    wintypes.LPARAM,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)

user32.EnumDisplayMonitors.argtypes = [
    HDC,
    LPMONITORRECT,
    MONITORENUMPROC,
    wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [
    HMONITOR,
    ctypes.POINTER(MONITORINFOEXW),
]
user32.GetMonitorInfoW.restype = wintypes.BOOL

user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW),
    wintypes.DWORD,
]
user32.EnumDisplayDevicesW.restype = wintypes.BOOL

dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
    HMONITOR,
    LPDWORD,
]
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
    HMONITOR,
    wintypes.DWORD,
    ctypes.POINTER(PHYSICAL_MONITOR),
]
dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

dxva2.DestroyPhysicalMonitors.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(PHYSICAL_MONITOR),
]
dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL

dxva2.GetMonitorBrightness.argtypes = [
    wintypes.HANDLE,
    LPDWORD,
    LPDWORD,
    LPDWORD,
]
dxva2.GetMonitorBrightness.restype = wintypes.BOOL

dxva2.SetMonitorBrightness.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
]
dxva2.SetMonitorBrightness.restype = wintypes.BOOL


def ensure_windows_platform() -> None:
    """
    @brief 确保脚本运行在 Windows 平台上。
    @return None
    @note 该脚本依赖 Windows 的显示器配置 API。
    """

    if os.name != "nt":
        raise OSError("该脚本仅支持在 Windows 系统中运行。")


def raise_last_windows_error(message: str) -> None:
    """
    @brief 抛出带有 Windows 错误码的异常。
    @param message 异常的中文描述信息。
    @return None
    """

    error_code = ctypes.get_last_error()
    raise OSError(error_code, f"{message} Windows 错误码: {error_code}")


def enumerate_display_monitors() -> list[HMONITOR]:
    """
    @brief 枚举当前系统中的逻辑显示器句柄。
    @return list[HMONITOR] 逻辑显示器句柄列表。
    """

    monitor_handles: list[HMONITOR] = []

    @MONITORENUMPROC
    def callback(
        hmonitor: HMONITOR,
        hdc: HDC,
        monitor_rect: LPMONITORRECT,
        application_data: wintypes.LPARAM,
    ) -> wintypes.BOOL:
        """
        @brief 处理 EnumDisplayMonitors 返回的单个显示器。
        @param hmonitor 当前显示器的句柄。
        @param hdc 当前显示器的设备上下文句柄。
        @param monitor_rect 当前显示器对应的矩形区域指针。
        @param application_data 调用方传入的附加参数。
        @return wintypes.BOOL 返回 True 表示继续枚举。
        """

        del hdc
        del monitor_rect
        del application_data
        monitor_handles.append(hmonitor)
        return True

    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise_last_windows_error("枚举显示器失败。")

    return monitor_handles


def open_physical_monitors(
    hmonitor: HMONITOR,
) -> tuple[int, ctypes.Array[PHYSICAL_MONITOR]]:
    """
    @brief 根据逻辑显示器句柄打开对应的物理显示器列表。
    @param hmonitor 逻辑显示器句柄。
    @return tuple[int, ctypes.Array[PHYSICAL_MONITOR]] 返回物理显示器数量及其数组。
    """

    monitor_count = wintypes.DWORD()

    if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(
        hmonitor,
        ctypes.byref(monitor_count),
    ):
        raise_last_windows_error("获取物理显示器数量失败。")

    physical_monitor_array = (PHYSICAL_MONITOR * monitor_count.value)()

    if monitor_count.value == 0:
        return 0, physical_monitor_array

    if not dxva2.GetPhysicalMonitorsFromHMONITOR(
        hmonitor,
        monitor_count,
        physical_monitor_array,
    ):
        raise_last_windows_error("打开物理显示器句柄失败。")

    return monitor_count.value, physical_monitor_array


def close_physical_monitors(
    monitor_count: int,
    physical_monitor_array: ctypes.Array[PHYSICAL_MONITOR],
) -> None:
    """
    @brief 释放物理显示器句柄数组。
    @param monitor_count 物理显示器数量。
    @param physical_monitor_array 物理显示器数组。
    @return None
    """

    if monitor_count <= 0:
        return

    if not dxva2.DestroyPhysicalMonitors(monitor_count, physical_monitor_array):
        raise_last_windows_error("释放物理显示器句柄失败。")


def get_monitor_device_name(hmonitor: HMONITOR) -> str:
    """
    @brief 读取逻辑显示器对应的 Windows 显示设备名。
    @param hmonitor 逻辑显示器句柄。
    @return str 显示设备名，例如 Windows DISPLAY1 设备名。
    """

    monitor_info = MONITORINFOEXW()
    monitor_info.cbSize = ctypes.sizeof(MONITORINFOEXW)

    if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(monitor_info)):
        raise_last_windows_error("读取显示器设备名失败。")

    return str(monitor_info.szDevice).strip()


def get_display_monitor_device_id(display_device_name: str) -> str | None:
    """
    @brief 获取显示设备下挂载的监视器硬件 ID。
    @param display_device_name Windows DISPLAY1 设备名。
    @return str | None 成功时返回监视器硬件 ID，否则返回 None。
    """

    display_device = DISPLAY_DEVICEW()
    display_device.cb = ctypes.sizeof(DISPLAY_DEVICEW)

    if not user32.EnumDisplayDevicesW(
        display_device_name,
        0,
        ctypes.byref(display_device),
        0,
    ):
        return None

    return str(display_device.DeviceID).strip() or None


def normalize_monitor_hardware_id(device_id: str | None) -> str | None:
    """
    @brief 将 Windows 设备 ID 标准化为便于比较的硬件 ID。
    @param device_id Windows 显示设备 ID 或 WMI 实例名。
    @return str | None 标准化后的硬件 ID。
    """

    if not device_id:
        return None

    normalized_text = device_id.upper().replace("\\", "_")
    parts = [part for part in normalized_text.split("_") if part]

    for prefix in ("DISPLAY", "MONITOR"):
        for index in range(len(parts) - 1):
            if parts[index] == prefix:
                return parts[index + 1]

    return None


def get_physical_monitor_brightness(
    physical_monitor_handle: wintypes.HANDLE,
) -> tuple[int, int, int]:
    """
    @brief 读取单个物理显示器的亮度范围与当前值。
    @param physical_monitor_handle 物理显示器句柄。
    @return tuple[int, int, int] 依次返回最小值、当前值和最大值。
    """

    minimum_value = wintypes.DWORD()
    current_value = wintypes.DWORD()
    maximum_value = wintypes.DWORD()

    if not dxva2.GetMonitorBrightness(
        physical_monitor_handle,
        ctypes.byref(minimum_value),
        ctypes.byref(current_value),
        ctypes.byref(maximum_value),
    ):
        raise_last_windows_error("读取显示器亮度失败。")

    return minimum_value.value, current_value.value, maximum_value.value


def convert_monitor_value_to_percentage(
    minimum_value: int,
    current_value: int,
    maximum_value: int,
) -> int:
    """
    @brief 将显示器原始亮度值换算为百分比。
    @param minimum_value 显示器支持的最小亮度值。
    @param current_value 当前亮度值。
    @param maximum_value 显示器支持的最大亮度值。
    @return int 0 到 100 范围内的百分比亮度值。
    """

    if maximum_value <= minimum_value:
        return 0

    return round(
        (current_value - minimum_value) * 100 / (maximum_value - minimum_value)
    )


def convert_percentage_to_monitor_value(
    minimum_value: int,
    maximum_value: int,
    target_percentage: int,
) -> int:
    """
    @brief 将百分比亮度换算为显示器原始亮度值。
    @param minimum_value 显示器支持的最小亮度值。
    @param maximum_value 显示器支持的最大亮度值。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return int 可直接写入显示器的原始亮度值。
    """

    return round(
        minimum_value + (maximum_value - minimum_value) * target_percentage / 100
    )


def get_monitor_description(physical_monitor: PHYSICAL_MONITOR) -> str:
    """
    @brief 获取物理显示器的可读描述信息。
    @param physical_monitor 物理显示器结构体对象。
    @return str 显示器描述文本。
    """

    return str(physical_monitor.szPhysicalMonitorDescription).strip()


def import_win32com_client():
    """
    @brief 导入 pywin32 的 WMI COM 调用模块。
    @return object 返回 win32com.client 模块对象。
    @note 未安装 pywin32 时返回 None，使 WMI 后端成为可选能力。
    """

    try:
        import win32com.client
    except ImportError:
        return None

    return win32com.client


def initialize_com_for_current_thread() -> bool:
    """
    @brief 为当前线程初始化 COM 环境。
    @return bool 返回 True 表示本线程已经完成或无需重复完成 COM 初始化。
    @note WMI 依赖 COM；后台线程访问 WMI 前需要单独初始化。
    """

    if getattr(thread_local_state, "com_initialized", False):
        return True

    try:
        import pythoncom
    except ImportError:
        return False

    try:
        pythoncom.CoInitialize()
    except Exception:
        return False

    thread_local_state.com_initialized = True
    return True


def get_wmi_service():
    """
    @brief 获取 root\\WMI 命名空间的 WMI 服务对象。
    @return object | None 成功时返回 WMI 服务对象，否则返回 None。
    """

    if not initialize_com_for_current_thread():
        return None

    win32com_client = import_win32com_client()

    if win32com_client is None:
        return None

    try:
        locator = win32com_client.Dispatch("WbemScripting.SWbemLocator")
        return locator.ConnectServer(".", "root\\WMI")
    except Exception:
        return None


def get_wmi_brightness_records() -> list[WmiBrightnessRecord]:
    """
    @brief 枚举 Windows WMI 内屏亮度对象。
    @return list[WmiBrightnessRecord] 内屏亮度对象列表。
    """

    wmi_service = get_wmi_service()
    brightness_records: list[WmiBrightnessRecord] = []

    if wmi_service is None:
        return brightness_records

    try:
        brightness_items = list(
            wmi_service.ExecQuery("SELECT * FROM WmiMonitorBrightness")
        )
    except Exception as error:
        logger.debug("WMI 亮度对象枚举不可用: %s", error)
        return brightness_records

    for item in brightness_items:
        try:
            instance_name = str(item.InstanceName)
            current_percentage = int(item.CurrentBrightness)
            hardware_id = normalize_monitor_hardware_id(instance_name)
            supported_levels = [
                int(level)
                for level in list(item.Level)
            ]
        except Exception as error:
            logger.debug("跳过不可读取的 WMI 亮度对象: %s", error)
            continue

        brightness_records.append(
            WmiBrightnessRecord(
                instance_name=instance_name,
                current_percentage=current_percentage,
                hardware_id=hardware_id,
                supported_levels=supported_levels,
            )
        )

    return brightness_records


def get_wmi_brightness_method_instance_names() -> set[str]:
    """
    @brief 枚举可执行 WMI 亮度设置方法的实例名。
    @return set[str] 支持 WmiSetBrightness 的实例名集合。
    @note 某些系统存在 root\\WMI 命名空间但不开放亮度方法，此时返回空集合。
    """

    method_instance_names: set[str] = set()
    wmi_service = get_wmi_service()

    if wmi_service is None:
        return method_instance_names

    try:
        method_items = list(
            wmi_service.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods")
        )
    except Exception as error:
        logger.debug("WMI 亮度设置方法枚举不可用: %s", error)
        return method_instance_names

    for item in method_items:
        try:
            method_instance_names.add(str(item.InstanceName).lower())
        except Exception as error:
            logger.debug("跳过不可读取的 WMI 亮度方法对象: %s", error)

    return method_instance_names


def build_wmi_brightness_record_map() -> dict[str, WmiBrightnessRecord]:
    """
    @brief 构建以内屏硬件 ID 为键的 WMI 亮度对象字典。
    @return dict[str, WmiBrightnessRecord] WMI 亮度对象字典。
    """

    record_map: dict[str, WmiBrightnessRecord] = {}

    for record in get_wmi_brightness_records():
        if record.hardware_id is None:
            continue

        record_map[record.hardware_id] = record

    return record_map


def get_supported_wmi_brightness_levels(instance_name: str) -> list[int]:
    """
    @brief 获取指定 WMI 内屏对象支持的亮度档位。
    @param instance_name WMI 亮度对象实例名。
    @return list[int] 支持的亮度百分比列表，单位为 %。
    """

    for record in get_wmi_brightness_records():
        if record.instance_name.lower() != instance_name.lower():
            continue

        return record.supported_levels

    return []


def clamp_brightness_to_supported_level(
    target_percentage: int,
    supported_levels: list[int],
) -> int:
    """
    @brief 将目标亮度对齐到显示器支持的最近档位。
    @param target_percentage 目标亮度百分比，单位为 %。
    @param supported_levels 支持的亮度百分比档位列表，单位为 %。
    @return int 实际应写入的亮度百分比，单位为 %。
    """

    if not supported_levels:
        return target_percentage

    return min(
        supported_levels,
        key=lambda level: abs(level - target_percentage),
    )


def set_wmi_brightness(instance_name: str, target_percentage: int) -> int:
    """
    @brief 通过 WMI 设置笔记本内屏亮度。
    @param instance_name WMI 亮度对象实例名。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return int 实际写入的亮度百分比，单位为 %。
    """

    wmi_service = get_wmi_service()

    if wmi_service is None:
        raise RuntimeError("当前环境无法访问 WMI 内屏亮度接口。")

    supported_levels = get_supported_wmi_brightness_levels(instance_name)
    applied_percentage = clamp_brightness_to_supported_level(
        target_percentage,
        supported_levels,
    )

    try:
        method_items = list(
            wmi_service.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods")
        )
    except Exception as error:
        raise RuntimeError("当前环境无法枚举 WMI 内屏亮度设置方法。") from error

    for method_item in method_items:
        if str(method_item.InstanceName).lower() != instance_name.lower():
            continue

        method_definition = method_item.Methods_("WmiSetBrightness")
        input_parameters = method_definition.InParameters.SpawnInstance_()
        input_parameters.Properties_.Item("Timeout").Value = (
            WMI_SET_BRIGHTNESS_TIMEOUT_SECONDS
        )
        input_parameters.Properties_.Item("Brightness").Value = int(
            applied_percentage
        )
        method_item.ExecMethod_(
            "WmiSetBrightness",
            input_parameters,
        )
        logger.info(
            "WMI 设置亮度成功: instance=%s, requested=%s%%, applied=%s%%。",
            instance_name,
            target_percentage,
            applied_percentage,
        )
        return applied_percentage

    raise RuntimeError("未找到匹配的 WMI 内屏亮度设置对象。")


def get_monitor_brightness_infos() -> list[MonitorBrightnessInfo]:
    """
    @brief 获取当前系统中所有显示器的亮度信息。
    @return list[MonitorBrightnessInfo] 显示器亮度信息列表。
    """

    monitor_infos: list[MonitorBrightnessInfo] = []
    logical_monitors = enumerate_display_monitors()
    current_index = 1
    wmi_record_map = build_wmi_brightness_record_map()
    wmi_method_instance_names = get_wmi_brightness_method_instance_names()

    for logical_monitor in logical_monitors:
        display_device_name = get_monitor_device_name(logical_monitor)
        monitor_device_id = get_display_monitor_device_id(display_device_name)
        monitor_hardware_id = normalize_monitor_hardware_id(monitor_device_id)
        wmi_record = None

        if monitor_hardware_id is not None:
            wmi_record = wmi_record_map.get(monitor_hardware_id)

        monitor_count, physical_monitor_array = open_physical_monitors(logical_monitor)

        try:
            for physical_monitor in physical_monitor_array:
                description = get_monitor_description(physical_monitor)
                wmi_supported = (
                    wmi_record is not None
                    and wmi_record.instance_name.lower()
                    in wmi_method_instance_names
                )
                available_backends: list[str] = []
                minimum_value = None
                current_value = None
                maximum_value = None
                current_percentage = None
                supports_brightness = False
                backend = BRIGHTNESS_BACKEND_NONE
                backend_key = None

                if wmi_supported:
                    available_backends.append(BRIGHTNESS_BACKEND_WMI)

                try:
                    minimum_value, current_value, maximum_value = (
                        get_physical_monitor_brightness(
                            physical_monitor.hPhysicalMonitor
                        )
                    )
                    current_percentage = convert_monitor_value_to_percentage(
                        minimum_value,
                        current_value,
                        maximum_value,
                    )
                    supports_brightness = True
                    backend = BRIGHTNESS_BACKEND_DDCCI
                    backend_key = None
                    available_backends.insert(0, BRIGHTNESS_BACKEND_DDCCI)
                except OSError as error:
                    logger.debug(
                        "显示器 [%s] %s 不支持 DDC/CI 亮度读取: %s",
                        current_index,
                        description,
                        error,
                    )

                if not supports_brightness and wmi_supported:
                    minimum_value = 0
                    current_value = wmi_record.current_percentage
                    maximum_value = 100
                    current_percentage = wmi_record.current_percentage
                    supports_brightness = True
                    backend = BRIGHTNESS_BACKEND_WMI
                    backend_key = wmi_record.instance_name

                monitor_info = MonitorBrightnessInfo(
                    index=current_index,
                    description=description,
                    minimum_value=minimum_value,
                    current_value=current_value,
                    maximum_value=maximum_value,
                    current_percentage=current_percentage,
                    supports_brightness=supports_brightness,
                    backend=backend,
                    backend_key=backend_key,
                )
                monitor_infos.append(monitor_info)
                logger.debug(
                    "识别显示器 [%s] %s，可用控制方式=%s，选用=%s，当前亮度=%s，支持亮度=%s。",
                    monitor_info.index,
                    monitor_info.description,
                    ", ".join(available_backends) or BRIGHTNESS_BACKEND_NONE,
                    monitor_info.backend,
                    monitor_info.current_percentage,
                    monitor_info.supports_brightness,
                )
                current_index += 1
        finally:
            close_physical_monitors(monitor_count, physical_monitor_array)

    return monitor_infos


def print_monitor_list(monitor_infos: list[MonitorBrightnessInfo]) -> None:
    """
    @brief 将显示器亮度信息输出到命令行。
    @param monitor_infos 显示器亮度信息列表。
    @return None
    """

    if not monitor_infos:
        log_and_print(
            logger,
            logging.WARNING,
            "未发现可访问的物理显示器。",
        )
        return

    for monitor_info in monitor_infos:
        if monitor_info.supports_brightness:
            log_and_print(
                logger,
                logging.INFO,
                f"[{monitor_info.index}] {monitor_info.description} | "
                f"控制方式: {monitor_info.backend} | "
                f"当前亮度: {monitor_info.current_percentage}% | "
                f"原始范围: {monitor_info.minimum_value}-{monitor_info.maximum_value}",
            )
        else:
            log_and_print(
                logger,
                logging.INFO,
                f"[{monitor_info.index}] {monitor_info.description} | "
                f"不支持当前可用的亮度控制后端",
            )


def set_ddcci_brightness_by_index(
    target_index: int,
    target_percentage: int,
) -> BrightnessSetResult:
    """
    @brief 通过 DDC/CI 按索引设置单个显示器亮度。
    @param target_index 目标显示器索引，从 1 开始。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return BrightnessSetResult 返回亮度设置结果。
    """

    logical_monitors = enumerate_display_monitors()
    current_index = 1

    for logical_monitor in logical_monitors:
        monitor_count, physical_monitor_array = open_physical_monitors(logical_monitor)

        try:
            for physical_monitor in physical_monitor_array:
                if current_index == target_index:
                    minimum_value, _, maximum_value = get_physical_monitor_brightness(
                        physical_monitor.hPhysicalMonitor
                    )
                    raw_brightness_value = convert_percentage_to_monitor_value(
                        minimum_value,
                        maximum_value,
                        target_percentage,
                    )

                    if not dxva2.SetMonitorBrightness(
                        physical_monitor.hPhysicalMonitor,
                        raw_brightness_value,
                    ):
                        raise_last_windows_error("设置显示器亮度失败。")

                    logger.info(
                        "DDC/CI 设置亮度成功: index=%s, requested=%s%%, raw=%s。",
                        target_index,
                        target_percentage,
                        raw_brightness_value,
                    )
                    return BrightnessSetResult(
                        description=get_monitor_description(physical_monitor),
                        requested_percentage=target_percentage,
                        applied_percentage=target_percentage,
                    )

                current_index += 1
        finally:
            close_physical_monitors(monitor_count, physical_monitor_array)

    raise IndexError(f"未找到索引为 {target_index} 的显示器。")


def set_brightness_by_index(target_index: int, target_percentage: int) -> str:
    """
    @brief 按索引设置单个显示器亮度。
    @param target_index 目标显示器索引，从 1 开始。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return str 返回被设置显示器的描述信息。
    """

    for monitor_info in get_monitor_brightness_infos():
        if monitor_info.index != target_index:
            continue

        if not monitor_info.supports_brightness:
            raise RuntimeError(f"显示器索引 {target_index} 不支持亮度控制。")

        if monitor_info.backend == BRIGHTNESS_BACKEND_WMI:
            if monitor_info.backend_key is None:
                raise RuntimeError("WMI 内屏亮度对象缺少实例名。")

            set_wmi_brightness(
                monitor_info.backend_key,
                target_percentage,
            )
            return monitor_info.description

        if monitor_info.backend == BRIGHTNESS_BACKEND_DDCCI:
            return set_ddcci_brightness_by_index(
                target_index,
                target_percentage,
            ).description

        raise RuntimeError(f"显示器索引 {target_index} 不支持亮度控制。")

    raise IndexError(f"未找到索引为 {target_index} 的显示器。")


def set_brightness_by_index_with_result(
    target_index: int,
    target_percentage: int,
) -> BrightnessSetResult:
    """
    @brief 按索引设置单个显示器亮度并返回实际执行结果。
    @param target_index 目标显示器索引，从 1 开始。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return BrightnessSetResult 返回亮度设置结果。
    """

    for monitor_info in get_monitor_brightness_infos():
        if monitor_info.index != target_index:
            continue

        if not monitor_info.supports_brightness:
            raise RuntimeError(f"显示器索引 {target_index} 不支持亮度控制。")

        if monitor_info.backend == BRIGHTNESS_BACKEND_WMI:
            if monitor_info.backend_key is None:
                raise RuntimeError("WMI 内屏亮度对象缺少实例名。")

            applied_percentage = set_wmi_brightness(
                monitor_info.backend_key,
                target_percentage,
            )
            return BrightnessSetResult(
                description=monitor_info.description,
                requested_percentage=target_percentage,
                applied_percentage=applied_percentage,
            )

        if monitor_info.backend == BRIGHTNESS_BACKEND_DDCCI:
            return set_ddcci_brightness_by_index(
                target_index,
                target_percentage,
            )

        raise RuntimeError(f"显示器索引 {target_index} 不支持亮度控制。")

    raise IndexError(f"未找到索引为 {target_index} 的显示器。")


def set_brightness_for_all(target_percentage: int) -> list[str]:
    """
    @brief 为所有支持亮度控制的显示器设置亮度。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return list[str] 返回已成功设置的显示器描述列表。
    """

    updated_monitors: list[str] = []

    for monitor_info in get_monitor_brightness_infos():
        if not monitor_info.supports_brightness:
            continue

        try:
            set_brightness_by_index(
                monitor_info.index,
                target_percentage,
            )
            updated_monitors.append(monitor_info.description)
        except Exception:
            continue

    return updated_monitors


def get_brightness_backend_label(backend: str) -> str:
    """
    @brief 获取亮度控制后端的可读标签。
    @param backend 亮度控制后端标识。
    @return str 后端可读标签。
    """

    if backend == BRIGHTNESS_BACKEND_WMI:
        return "WMI"

    if backend == BRIGHTNESS_BACKEND_DDCCI:
        return "DDC/CI"

    return "无"


def parse_arguments() -> argparse.Namespace:
    """
    @brief 解析命令行参数。
    @return argparse.Namespace 解析后的命令行参数对象。
    """

    parser = argparse.ArgumentParser(
        description="使用 DDC/CI 或 WMI 读取、设置显示器亮度。"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "list",
        help="列出可访问的显示器以及当前亮度信息。",
    )

    get_parser = subparsers.add_parser(
        "get",
        help="读取显示器亮度信息。",
    )
    get_parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="读取指定索引的显示器亮度，不传则列出全部。",
    )

    set_parser = subparsers.add_parser(
        "set",
        help="设置显示器亮度百分比。",
    )
    set_parser.add_argument(
        "brightness",
        type=int,
        help="目标亮度百分比，范围为 0 到 100。",
    )
    set_parser.add_argument(
        "--index",
        type=int,
        default=1,
        help="目标显示器索引，默认设置第 1 个显示器。",
    )
    set_parser.add_argument(
        "--all",
        action="store_true",
        help="设置所有支持亮度控制的显示器。",
    )
    add_logging_arguments(parser)

    return parser.parse_args()


def validate_brightness_percentage(target_percentage: int) -> None:
    """
    @brief 校验亮度百分比是否在合法范围内。
    @param target_percentage 目标亮度百分比。
    @return None
    """

    if target_percentage < 0 or target_percentage > 100:
        raise ValueError("亮度百分比必须在 0 到 100 之间。")


def main() -> int:
    """
    @brief 脚本主入口。
    @return int 返回进程退出码，0 表示成功，1 表示失败。
    """

    ensure_windows_platform()
    arguments = parse_arguments()
    log_file_path = configure_lumina_logging(
        arguments.log_dir,
        arguments.log_level,
    )
    logger.info("monitor_brightness 启动，日志文件: %s，参数: %s", log_file_path, vars(arguments))

    try:
        if arguments.command is None or arguments.command == "list":
            print_monitor_list(get_monitor_brightness_infos())
            return 0

        if arguments.command == "get":
            monitor_infos = get_monitor_brightness_infos()

            if arguments.index is None:
                print_monitor_list(monitor_infos)
                return 0

            for monitor_info in monitor_infos:
                if monitor_info.index == arguments.index:
                    print_monitor_list([monitor_info])
                    return 0

            raise IndexError(f"未找到索引为 {arguments.index} 的显示器。")

        if arguments.command == "set":
            validate_brightness_percentage(arguments.brightness)

            if arguments.all:
                updated_monitors = set_brightness_for_all(arguments.brightness)

                if not updated_monitors:
                    raise RuntimeError("没有找到支持亮度控制的显示器。")

                log_and_print(
                    logger,
                    logging.INFO,
                    f"已将 {len(updated_monitors)} 台显示器的亮度设置为 "
                    f"{arguments.brightness}% 。",
                )
                return 0

            updated_result = set_brightness_by_index_with_result(
                arguments.index,
                arguments.brightness,
            )

            if updated_result.applied_percentage == arguments.brightness:
                log_and_print(
                    logger,
                    logging.INFO,
                    f"已将显示器 [{arguments.index}] "
                    f"{updated_result.description} 的亮度设置为 "
                    f"{arguments.brightness}% 。",
                )
            else:
                log_and_print(
                    logger,
                    logging.INFO,
                    f"已请求显示器 [{arguments.index}] "
                    f"{updated_result.description} 设置为 "
                    f"{arguments.brightness}% ，实际写入 "
                    f"{updated_result.applied_percentage}% 。",
                )

            return 0

        raise ValueError("未知命令。")
    except Exception as error:
        log_and_print(
            logger,
            logging.ERROR,
            f"执行失败: {error}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
