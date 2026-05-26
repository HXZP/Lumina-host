# -*- coding: utf-8 -*-
"""
@brief 基于 Windows 显示配置 API 控制屏幕旋转方向的命令行工具。
@note 该脚本使用 user32.dll 中的显示枚举与显示模式切换接口，仅支持 Windows。
"""

from __future__ import annotations

import argparse
import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass


CCHDEVICENAME = 32
CCHFORMNAME = 32
ENUM_CURRENT_SETTINGS = 0xFFFFFFFF

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008

DM_DISPLAYORIENTATION = 0x00000080
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000

CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002

DMDO_DEFAULT = 0
DMDO_90 = 1
DMDO_180 = 2
DMDO_270 = 3

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISP_CHANGE_FAILED = -1
DISP_CHANGE_BADMODE = -2
DISP_CHANGE_NOTUPDATED = -3
DISP_CHANGE_BADFLAGS = -4
DISP_CHANGE_BADPARAM = -5
DISP_CHANGE_BADDUALVIEW = -6


class POINTL(ctypes.Structure):
    """
    @brief 表示桌面坐标系中的二维坐标点。
    @note 该结构与 Windows POINTL 结构保持一致。
    """

    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    """
    @brief 表示 Windows 显示设备信息结构。
    @note 该结构用于适配器与显示器枚举。
    """

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class DEVMODEW_PRINTER(ctypes.Structure):
    """
    @brief 表示 DEVMODEW 联合体中的打印字段布局。
    @note 本脚本不直接使用这些字段，但需要保留结构布局。
    """

    _fields_ = [
        ("dmOrientation", wintypes.SHORT),
        ("dmPaperSize", wintypes.SHORT),
        ("dmPaperLength", wintypes.SHORT),
        ("dmPaperWidth", wintypes.SHORT),
        ("dmScale", wintypes.SHORT),
        ("dmCopies", wintypes.SHORT),
        ("dmDefaultSource", wintypes.SHORT),
        ("dmPrintQuality", wintypes.SHORT),
    ]


class DEVMODEW_DISPLAY(ctypes.Structure):
    """
    @brief 表示 DEVMODEW 联合体中的显示字段布局。
    @note 其中包含显示器位置与旋转方向字段。
    """

    _fields_ = [
        ("dmPosition", POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
    ]


class DEVMODEW_UNION(ctypes.Union):
    """
    @brief 表示 DEVMODEW 中的第一个联合体。
    @note 该联合体用于兼容打印字段与显示字段两种布局。
    """

    _anonymous_ = ("dmDisplay",)
    _fields_ = [
        ("dmPrinter", DEVMODEW_PRINTER),
        ("dmPosition", POINTL),
        ("dmDisplay", DEVMODEW_DISPLAY),
    ]


class DEVMODEW_FLAGS_UNION(ctypes.Union):
    """
    @brief 表示 DEVMODEW 中的第二个联合体。
    @note 该联合体在显示场景下使用 dmDisplayFlags 字段。
    """

    _fields_ = [
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmNup", wintypes.DWORD),
    ]


class DEVMODEW(ctypes.Structure):
    """
    @brief 表示 Windows DEVMODEW 结构。
    @note 该结构用于读取与修改显示设备的当前模式。
    """

    _anonymous_ = ("dummy_union", "flags_union")
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * CCHDEVICENAME),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dummy_union", DEVMODEW_UNION),
        ("dmColor", wintypes.SHORT),
        ("dmDuplex", wintypes.SHORT),
        ("dmYResolution", wintypes.SHORT),
        ("dmTTOption", wintypes.SHORT),
        ("dmCollate", wintypes.SHORT),
        ("dmFormName", wintypes.WCHAR * CCHFORMNAME),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("flags_union", DEVMODEW_FLAGS_UNION),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


@dataclass
class DisplayRotationInfo:
    """
    @brief 保存显示器的旋转状态与标识信息。
    @note 该数据结构用于命令行展示与目标显示器选择。
    """

    index: int
    device_name: str
    adapter_name: str
    monitor_name: str
    is_primary: bool
    width: int
    height: int
    orientation_value: int


user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW),
    wintypes.DWORD,
]
user32.EnumDisplayDevicesW.restype = wintypes.BOOL

user32.EnumDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DEVMODEW),
    wintypes.DWORD,
]
user32.EnumDisplaySettingsExW.restype = wintypes.BOOL

user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(DEVMODEW),
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
]
user32.ChangeDisplaySettingsExW.restype = wintypes.LONG


def ensure_windows_platform() -> None:
    """
    @brief 确保脚本运行在 Windows 平台上。
    @return None
    @note 该脚本依赖 Windows 的显示配置接口。
    """

    if os.name != "nt":
        raise OSError("该脚本仅支持在 Windows 系统中运行。")


def initialize_display_device() -> DISPLAY_DEVICEW:
    """
    @brief 创建并初始化 DISPLAY_DEVICEW 结构体。
    @return DISPLAY_DEVICEW 已设置 cb 字段的结构体实例。
    """

    display_device = DISPLAY_DEVICEW()
    display_device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    return display_device


def initialize_dev_mode() -> DEVMODEW:
    """
    @brief 创建并初始化 DEVMODEW 结构体。
    @return DEVMODEW 已设置 dmSize 字段的结构体实例。
    """

    dev_mode = DEVMODEW()
    dev_mode.dmSize = ctypes.sizeof(DEVMODEW)
    return dev_mode


def is_active_desktop_display(display_device: DISPLAY_DEVICEW) -> bool:
    """
    @brief 判断显示设备是否处于桌面活动状态。
    @param display_device 待判断的显示设备结构体。
    @return bool 返回 True 表示该设备已附加到桌面。
    """

    if not display_device.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
        return False

    if display_device.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
        return False

    return True


def enumerate_active_display_adapters() -> list[DISPLAY_DEVICEW]:
    """
    @brief 枚举当前系统中所有活动的显示适配器。
    @return list[DISPLAY_DEVICEW] 活动显示适配器列表。
    """

    display_adapters: list[DISPLAY_DEVICEW] = []
    adapter_index = 0

    while True:
        display_adapter = initialize_display_device()
        result = user32.EnumDisplayDevicesW(
            None,
            adapter_index,
            ctypes.byref(display_adapter),
            0,
        )

        if not result:
            break

        if is_active_desktop_display(display_adapter):
            display_adapters.append(display_adapter)

        adapter_index += 1

    return display_adapters


def get_monitor_names_for_adapter(adapter_device_name: str) -> list[str]:
    """
    @brief 获取某个显示适配器下关联的显示器名称列表。
    @param adapter_device_name 显示适配器设备名，例如 \\\\.\\DISPLAY1。
    @return list[str] 该适配器下显示器名称列表。
    """

    monitor_names: list[str] = []
    monitor_index = 0

    while True:
        monitor_device = initialize_display_device()
        result = user32.EnumDisplayDevicesW(
            adapter_device_name,
            monitor_index,
            ctypes.byref(monitor_device),
            0,
        )

        if not result:
            break

        monitor_name = str(monitor_device.DeviceString).strip()

        if monitor_name and monitor_name not in monitor_names:
            monitor_names.append(monitor_name)

        monitor_index += 1

    return monitor_names


def get_current_display_mode(device_name: str) -> DEVMODEW:
    """
    @brief 读取指定显示设备的当前显示模式。
    @param device_name 显示设备名，例如 \\\\.\\DISPLAY1。
    @return DEVMODEW 当前显示模式结构体。
    """

    dev_mode = initialize_dev_mode()
    result = user32.EnumDisplaySettingsExW(
        device_name,
        ENUM_CURRENT_SETTINGS,
        ctypes.byref(dev_mode),
        0,
    )

    if not result:
        raise RuntimeError(f"读取显示设备 {device_name} 的当前模式失败。")

    return dev_mode


def orientation_value_to_degrees(orientation_value: int) -> int:
    """
    @brief 将 Windows 方向值转换为角度值。
    @param orientation_value Windows 方向常量值。
    @return int 对应的角度值，仅可能为 0、90、180、270。
    """

    if orientation_value == DMDO_DEFAULT:
        return 0

    if orientation_value == DMDO_90:
        return 90

    if orientation_value == DMDO_180:
        return 180

    if orientation_value == DMDO_270:
        return 270

    raise ValueError(f"不支持的方向值: {orientation_value}")


def orientation_value_to_label(orientation_value: int) -> str:
    """
    @brief 将 Windows 方向值转换为可读文本。
    @param orientation_value Windows 方向常量值。
    @return str 方向说明文本。
    """

    if orientation_value == DMDO_DEFAULT:
        return "默认方向（0°）"

    if orientation_value == DMDO_90:
        return "逆时针旋转 90°"

    if orientation_value == DMDO_180:
        return "旋转 180°"

    if orientation_value == DMDO_270:
        return "顺时针旋转 90°（等价于逆时针 270°）"

    return f"未知方向值 {orientation_value}"


def normalize_absolute_orientation(text: str) -> int:
    """
    @brief 将命令行中的绝对方向文本转换为 Windows 方向值。
    @param text 用户输入的方向文本。
    @return int Windows 方向常量值。
    """

    normalized_text = text.strip().lower()

    if normalized_text in {"default", "0", "默认", "恢复默认"}:
        return DMDO_DEFAULT

    if normalized_text == "90":
        return DMDO_90

    if normalized_text == "180":
        return DMDO_180

    if normalized_text == "270":
        return DMDO_270

    raise ValueError("绝对方向仅支持 default、0、90、180、270。")


def get_rotation_step(direction_text: str) -> int:
    """
    @brief 将相对旋转方向文本转换为步进值。
    @param direction_text 用户输入的相对旋转方向文本。
    @return int 旋转步进值，单位为 90 度。
    """

    normalized_text = direction_text.strip().lower()

    if normalized_text in {"left", "ccw", "左", "左转"}:
        return 1

    if normalized_text in {"right", "cw", "右", "右转"}:
        return 3

    if normalized_text in {"180", "flip", "翻转"}:
        return 2

    raise ValueError("相对旋转方向仅支持 left、right、180。")


def calculate_target_orientation(
    current_orientation: int,
    rotation_step: int,
) -> int:
    """
    @brief 根据当前方向和相对步进值计算目标方向。
    @param current_orientation 当前 Windows 方向值。
    @param rotation_step 旋转步进值，单位为 90 度。
    @return int 目标 Windows 方向值。
    """

    return (current_orientation + rotation_step) % 4


def build_display_rotation_info(
    index: int,
    display_adapter: DISPLAY_DEVICEW,
) -> DisplayRotationInfo:
    """
    @brief 构建单个显示设备的旋转信息对象。
    @param index 命令行展示使用的显示器索引，从 1 开始。
    @param display_adapter 显示适配器结构体对象。
    @return DisplayRotationInfo 构建后的显示器信息对象。
    """

    current_mode = get_current_display_mode(str(display_adapter.DeviceName))
    monitor_names = get_monitor_names_for_adapter(str(display_adapter.DeviceName))
    monitor_name = " / ".join(monitor_names)

    if not monitor_name:
        monitor_name = "未知显示器"

    is_primary = False

    if display_adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE:
        is_primary = True

    return DisplayRotationInfo(
        index=index,
        device_name=str(display_adapter.DeviceName),
        adapter_name=str(display_adapter.DeviceString),
        monitor_name=monitor_name,
        is_primary=is_primary,
        width=int(current_mode.dmPelsWidth),
        height=int(current_mode.dmPelsHeight),
        orientation_value=int(current_mode.dmDisplayOrientation),
    )


def get_display_rotation_infos() -> list[DisplayRotationInfo]:
    """
    @brief 获取当前系统所有活动显示器的旋转信息。
    @return list[DisplayRotationInfo] 显示器旋转信息列表。
    """

    display_infos: list[DisplayRotationInfo] = []
    display_adapters = enumerate_active_display_adapters()
    display_index = 1

    for display_adapter in display_adapters:
        display_infos.append(
            build_display_rotation_info(
                display_index,
                display_adapter,
            )
        )
        display_index += 1

    return display_infos


def get_display_shape_text(width: int, height: int) -> str:
    """
    @brief 根据宽高判断显示器当前形态。
    @param width 当前显示宽度。
    @param height 当前显示高度。
    @return str 返回横向、纵向或正方形描述。
    """

    if width > height:
        return "横向"

    if width < height:
        return "纵向"

    return "正方形"


def print_display_infos(display_infos: list[DisplayRotationInfo]) -> None:
    """
    @brief 将显示器旋转信息输出到命令行。
    @param display_infos 显示器旋转信息列表。
    @return None
    """

    if not display_infos:
        print("未发现活动显示器。")
        return

    for display_info in display_infos:
        primary_text = "主显示器"

        if not display_info.is_primary:
            primary_text = "扩展显示器"

        shape_text = get_display_shape_text(
            display_info.width,
            display_info.height,
        )

        print(f"[{display_info.index}] {display_info.device_name} | {primary_text}")
        print(f"    适配器: {display_info.adapter_name}")
        print(f"    显示器: {display_info.monitor_name}")
        print(
            "    当前方向: "
            f"{orientation_value_to_label(display_info.orientation_value)}"
        )
        print(
            f"    当前分辨率: {display_info.width} x {display_info.height} | "
            f"当前形态: {shape_text}"
        )


def get_display_info_by_index(target_index: int) -> DisplayRotationInfo:
    """
    @brief 根据索引获取目标显示器的旋转信息。
    @param target_index 目标显示器索引，从 1 开始。
    @return DisplayRotationInfo 目标显示器信息对象。
    """

    display_infos = get_display_rotation_infos()

    for display_info in display_infos:
        if display_info.index == target_index:
            return display_info

    raise IndexError(f"未找到索引为 {target_index} 的显示器。")


def should_swap_dimensions(
    current_orientation: int,
    target_orientation: int,
) -> bool:
    """
    @brief 判断旋转前后是否需要交换显示宽高。
    @param current_orientation 当前 Windows 方向值。
    @param target_orientation 目标 Windows 方向值。
    @return bool 返回 True 表示需要交换宽高。
    """

    current_is_portrait_family = bool(current_orientation % 2)
    target_is_portrait_family = bool(target_orientation % 2)

    if current_is_portrait_family == target_is_portrait_family:
        return False

    return True


def get_change_result_text(result_code: int) -> str:
    """
    @brief 将 ChangeDisplaySettingsExW 返回码转换为中文说明。
    @param result_code ChangeDisplaySettingsExW 返回码。
    @return str 返回码对应的中文说明。
    """

    if result_code == DISP_CHANGE_SUCCESSFUL:
        return "操作成功。"

    if result_code == DISP_CHANGE_RESTART:
        return "设置已写入，但需要重启系统后生效。"

    if result_code == DISP_CHANGE_FAILED:
        return "显示驱动拒绝执行该操作。"

    if result_code == DISP_CHANGE_BADMODE:
        return "显示器或驱动不支持该模式。"

    if result_code == DISP_CHANGE_NOTUPDATED:
        return "设置未能写入注册表。"

    if result_code == DISP_CHANGE_BADFLAGS:
        return "传入的标志位无效。"

    if result_code == DISP_CHANGE_BADPARAM:
        return "传入的参数无效。"

    if result_code == DISP_CHANGE_BADDUALVIEW:
        return "当前 DualView 配置不支持该操作。"

    return f"未知返回码: {result_code}"


def apply_orientation_to_device(
    device_name: str,
    target_orientation: int,
    persist_to_registry: bool,
) -> int:
    """
    @brief 将目标方向应用到指定显示设备。
    @param device_name 显示设备名，例如 \\\\.\\DISPLAY1。
    @param target_orientation 目标 Windows 方向值。
    @param persist_to_registry 是否写入注册表以持久化配置。
    @return int ChangeDisplaySettingsExW 的返回码。
    """

    current_mode = get_current_display_mode(device_name)
    current_orientation = int(current_mode.dmDisplayOrientation)

    if should_swap_dimensions(current_orientation, target_orientation):
        original_width = int(current_mode.dmPelsWidth)
        original_height = int(current_mode.dmPelsHeight)
        current_mode.dmPelsWidth = original_height
        current_mode.dmPelsHeight = original_width

    current_mode.dmDisplayOrientation = target_orientation
    current_mode.dmFields |= (
        DM_DISPLAYORIENTATION
        | DM_PELSWIDTH
        | DM_PELSHEIGHT
    )

    test_result = user32.ChangeDisplaySettingsExW(
        device_name,
        ctypes.byref(current_mode),
        None,
        CDS_TEST,
        None,
    )

    if test_result != DISP_CHANGE_SUCCESSFUL:
        raise RuntimeError(
            "显示模式测试失败: "
            f"{get_change_result_text(int(test_result))}"
        )

    apply_flags = 0

    if persist_to_registry:
        apply_flags = CDS_UPDATEREGISTRY

    apply_result = user32.ChangeDisplaySettingsExW(
        device_name,
        ctypes.byref(current_mode),
        None,
        apply_flags,
        None,
    )

    if apply_result not in {
        DISP_CHANGE_SUCCESSFUL,
        DISP_CHANGE_RESTART,
    }:
        raise RuntimeError(
            "应用显示模式失败: "
            f"{get_change_result_text(int(apply_result))}"
        )

    return int(apply_result)


def set_display_orientation_by_index(
    target_index: int,
    target_orientation: int,
    persist_to_registry: bool,
) -> tuple[DisplayRotationInfo, int]:
    """
    @brief 按索引设置目标显示器的绝对方向。
    @param target_index 目标显示器索引，从 1 开始。
    @param target_orientation 目标 Windows 方向值。
    @param persist_to_registry 是否写入注册表以持久化配置。
    @return tuple[DisplayRotationInfo, int] 返回目标显示器信息和 API 返回码。
    """

    display_info = get_display_info_by_index(target_index)
    result_code = apply_orientation_to_device(
        display_info.device_name,
        target_orientation,
        persist_to_registry,
    )
    return display_info, result_code


def rotate_display_by_index(
    target_index: int,
    direction_text: str,
    persist_to_registry: bool,
) -> tuple[DisplayRotationInfo, int, int]:
    """
    @brief 按索引对目标显示器进行相对旋转。
    @param target_index 目标显示器索引，从 1 开始。
    @param direction_text 相对旋转方向文本。
    @param persist_to_registry 是否写入注册表以持久化配置。
    @return tuple[DisplayRotationInfo, int, int] 返回目标显示器信息、目标方向值和 API 返回码。
    """

    display_info = get_display_info_by_index(target_index)
    rotation_step = get_rotation_step(direction_text)
    target_orientation = calculate_target_orientation(
        display_info.orientation_value,
        rotation_step,
    )
    result_code = apply_orientation_to_device(
        display_info.device_name,
        target_orientation,
        persist_to_registry,
    )
    return display_info, target_orientation, result_code


def parse_arguments() -> argparse.Namespace:
    """
    @brief 解析命令行参数。
    @return argparse.Namespace 解析后的命令行参数对象。
    """

    parser = argparse.ArgumentParser(
        description="读取或修改 Windows 屏幕旋转方向。",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "list",
        help="列出所有活动显示器及其当前方向。",
    )

    get_parser = subparsers.add_parser(
        "get",
        help="读取指定显示器或全部显示器的当前方向。",
    )
    get_parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="读取指定索引的显示器，不传则列出全部。",
    )

    set_parser = subparsers.add_parser(
        "set",
        help="设置显示器的绝对方向。",
    )
    set_parser.add_argument(
        "orientation",
        type=str,
        help="目标方向，支持 default、0、90、180、270。",
    )
    set_parser.add_argument(
        "--index",
        type=int,
        default=1,
        help="目标显示器索引，默认设置第 1 个显示器。",
    )
    set_parser.add_argument(
        "--no-persist",
        action="store_true",
        help="仅尝试立即应用，不写入注册表。",
    )

    rotate_parser = subparsers.add_parser(
        "rotate",
        help="按相对方向旋转显示器。",
    )
    rotate_parser.add_argument(
        "direction",
        type=str,
        help="旋转方向，支持 left、right、180。",
    )
    rotate_parser.add_argument(
        "--index",
        type=int,
        default=1,
        help="目标显示器索引，默认旋转第 1 个显示器。",
    )
    rotate_parser.add_argument(
        "--no-persist",
        action="store_true",
        help="仅尝试立即应用，不写入注册表。",
    )

    return parser.parse_args()


def main() -> int:
    """
    @brief 脚本主入口。
    @return int 返回进程退出码，0 表示成功，1 表示失败。
    """

    ensure_windows_platform()
    arguments = parse_arguments()

    try:
        if arguments.command is None or arguments.command == "list":
            print_display_infos(get_display_rotation_infos())
            return 0

        if arguments.command == "get":
            display_infos = get_display_rotation_infos()

            if arguments.index is None:
                print_display_infos(display_infos)
                return 0

            target_display_info = get_display_info_by_index(arguments.index)
            print_display_infos([target_display_info])
            return 0

        if arguments.command == "set":
            target_orientation = normalize_absolute_orientation(
                arguments.orientation
            )
            target_display_info, result_code = set_display_orientation_by_index(
                arguments.index,
                target_orientation,
                not arguments.no_persist,
            )
            print(
                f"已向显示器 [{target_display_info.index}] "
                f"{target_display_info.device_name} 发送方向切换请求。"
            )
            print(
                f"目标方向: {orientation_value_to_label(target_orientation)}"
            )
            print(
                f"执行结果: {get_change_result_text(result_code)}"
            )
            return 0

        if arguments.command == "rotate":
            target_display_info, target_orientation, result_code = (
                rotate_display_by_index(
                    arguments.index,
                    arguments.direction,
                    not arguments.no_persist,
                )
            )
            print(
                f"已向显示器 [{target_display_info.index}] "
                f"{target_display_info.device_name} 发送相对旋转请求。"
            )
            print(
                f"目标方向: {orientation_value_to_label(target_orientation)}"
            )
            print(
                f"执行结果: {get_change_result_text(result_code)}"
            )
            return 0

        raise ValueError("未知命令。")
    except Exception as error:
        print(f"执行失败: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
