# -*- coding: utf-8 -*-
"""
@brief Lumina 屏幕方向上位机服务。
@note 该脚本监听 Lumina 通过 USB HID 上报的方向与亮度事件，并旋转用户绑定的显示器。
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from monitor_rotation import (
    DMDO_90,
    DMDO_180,
    DMDO_270,
    DMDO_DEFAULT,
    get_change_result_text,
    get_display_info_by_index,
    get_display_rotation_infos,
    orientation_value_to_label,
    print_display_infos,
    set_display_orientation_by_index,
)


CONFIG_PATH = Path(__file__).resolve().parent.parent / "lumina_orientation_config.json"
MAX_LUMINA_DEVICE_COUNT = 3
LUMINA_USB_VID = 0x2FE3
LUMINA_USB_PID = 0x2301
LUMINA_USB_PRODUCT_KEYWORD = "Lumina"
LUMINA_HID_REPORT_SIZE = 64
LUMINA_HID_REPORT_ID = 1
LUMINA_HID_DEVICE_ID_SIZE = 12
LUMINA_HID_EVENT_READY = 1
LUMINA_HID_EVENT_ORIENTATION = 2
LUMINA_HID_EVENT_LUX = 3
LUMINA_HID_EVENT_MOTION = 4
LUMINA_HID_EVENT_CLICK = 5
LUMINA_HID_EVENT_STATE = 6
LUMINA_HID_ORIENTATION_UNKNOWN = 0
LUMINA_HID_ORIENTATION_TO_TEXT = {
    1: "X+",
    2: "X-",
    3: "Y+",
    4: "Y-",
}
ORIENTATION_TO_STEP = {
    "X+": 0,
    "Y+": 1,
    "X-": 2,
    "Y-": 3,
}
STEP_TO_WINDOWS_ORIENTATION = {
    0: DMDO_DEFAULT,
    1: DMDO_90,
    2: DMDO_180,
    3: DMDO_270,
}
DEFAULT_BRIGHTNESS_LEVELS = [
    {"min_lux": 0.0, "max_lux": 10.0, "brightness": 0},
    {"min_lux": 10.0, "max_lux": 30.0, "brightness": 25},
    {"min_lux": 30.0, "max_lux": 60.0, "brightness": 50},
    {"min_lux": 60.0, "max_lux": 100.0, "brightness": 75},
    {"min_lux": 100.0, "max_lux": None, "brightness": 100},
]
DEFAULT_BRIGHTNESS_LEVEL_LABELS = [
    "0~10",
    "10~30",
    "30~60",
    "60~100",
    "100<",
]
LEGACY_DEVICE_KEYS = {
    "",
    "default",
    "legacy",
}
logger = logging.getLogger(__name__)


def import_hid_module():
    """
    @brief 导入 hidapi 模块。
    @return 返回 hid 模块对象。
    @note 若当前 Python 环境未安装 hidapi，会给出明确安装提示。
    """

    try:
        import hid
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "缺少 hidapi，请先执行: python -m pip install hidapi"
        ) from error

    return hid


@dataclass
class LuminaOrientationConfig:
    """
    @brief 保存 Lumina 屏幕方向配置。
    @note display_index 用于绑定设备所在屏幕，home_orientation 表示屏幕正放时 Lumina 的朝向。
    """

    display_index: int
    home_orientation: str
    enabled: bool = True
    brightness_mode: str = "manual"
    brightness_levels: list[dict[str, float | int | None]] | None = None


@dataclass
class LuminaDeviceConfig:
    """
    @brief 保存单台 Lumina 的绑定配置。
    @note device_key 使用 HID 路径或历史 key 标识设备；brightness_display_indexes 表示使用该 Lumina 自动亮度的显示器索引。
    """

    device_key: str
    label: str
    display_index: int
    home_orientation: str
    enabled: bool = True
    brightness_mode: str = "manual"
    brightness_display_indexes: list[int] = field(default_factory=list)
    brightness_levels: list[dict[str, float | int | None]] | None = None


@dataclass
class LuminaMultiConfig:
    """
    @brief 保存多台 Lumina 的配置集合。
    @note 配置文件以 devices 列表存储，旧版单设备配置会在加载时自动迁移为一个元素。
    """

    devices: list[LuminaDeviceConfig]


@dataclass
class LuminaOrientationStatus:
    """
    @brief 保存 Lumina 方向服务运行状态。
    @note 该状态供托盘 UI 展示连接状态、设备数量、当前朝向和最近错误。
    """

    enabled: bool
    connected: bool
    device_count: int
    port_name: str | None
    current_orientation: str | None
    current_lux: float | None
    message: str


@dataclass
class LuminaDeviceStatus:
    """
    @brief 保存单台 Lumina 的运行状态。
    @note 该状态按 device_key 区分，供 UI 展示每张设备卡片。
    """

    device_key: str
    label: str
    enabled: bool
    connected: bool
    device_count: int
    port_name: str | None
    current_orientation: str | None
    current_lux: float | None
    message: str


@dataclass
class LuminaDeviceSnapshot:
    """
    @brief 保存 UI 所需的单台 Lumina 配置与状态快照。
    @note 该对象用于托盘面板一次性读取设备卡片、自动亮度档位和绑定关系。
    """

    config: LuminaDeviceConfig
    status: LuminaDeviceStatus
    brightness_level_label: str | None


@dataclass
class LuminaHidEvent:
    """
    @brief 保存 Lumina HID 事件内容。
    @note device_id 用于区分多台设备，sequence 用于观察是否丢包。
    """

    event_type: int
    orientation: str | None
    lux: float | None
    device_id: str
    sequence: int


def normalize_brightness_mode(text: str) -> str:
    """
    @brief 标准化亮度调节模式。
    @param text 用户输入或配置文件中的模式文本。
    @return 返回 manual 或 auto。
    """

    mode = text.strip().lower()

    if mode not in ("manual", "auto"):
        raise ValueError("亮度模式必须是 manual 或 auto")

    return mode


def normalize_brightness_percentage(value: object) -> int:
    """
    @brief 标准化亮度百分比。
    @param value 输入亮度值。
    @return 返回 0 到 100 范围内的整数亮度百分比。
    """

    percentage = int(round(float(value)))

    if percentage < 0:
        return 0

    if percentage > 100:
        return 100

    return percentage


def format_lux_value(value: float | int | None) -> str:
    """
    @brief 格式化 lux 边界值。
    @param value lux 边界值。
    @return 返回适合 UI 展示的短文本。
    """

    if value is None:
        return "--"

    lux_value = float(value)

    if lux_value.is_integer():
        return str(int(lux_value))

    return f"{lux_value:g}"


def format_brightness_level_range_label(
    level: dict[str, float | int | None],
) -> str:
    """
    @brief 格式化单个自动亮度档位的范围标签。
    @param level 自动亮度档位配置。
    @return 返回当前档位范围标签。
    """

    min_text = format_lux_value(level.get("min_lux"))
    max_lux = level.get("max_lux")

    if max_lux is None:
        return f"{min_text}<"

    return f"{min_text}~{format_lux_value(max_lux)}"


def normalize_brightness_levels(
    levels: object,
) -> list[dict[str, float | int | None]]:
    """
    @brief 标准化自动亮度档位配置。
    @param levels 配置文件或 UI 传入的档位列表。
    @return 返回 5 个标准档位。
    """

    if not isinstance(levels, list) or len(levels) != 5:
        return [dict(level) for level in DEFAULT_BRIGHTNESS_LEVELS]

    brightness_values: list[int] = []

    for index, default_level in enumerate(DEFAULT_BRIGHTNESS_LEVELS):
        raw_level = levels[index]

        if not isinstance(raw_level, dict):
            brightness_values.append(int(default_level["brightness"]))
            continue

        brightness_values.append(
            normalize_brightness_percentage(
                raw_level.get("brightness", default_level["brightness"])
            )
        )

    breakpoints: list[float] = []
    previous_breakpoint = 0.0

    for index, default_level in enumerate(DEFAULT_BRIGHTNESS_LEVELS[:4]):
        raw_level = levels[index]
        raw_breakpoint: object = default_level["max_lux"]

        if isinstance(raw_level, dict):
            raw_breakpoint = raw_level.get("max_lux", default_level["max_lux"])

        try:
            breakpoint_value = float(raw_breakpoint)
        except (TypeError, ValueError):
            breakpoint_value = float(default_level["max_lux"])

        if breakpoint_value <= previous_breakpoint:
            breakpoint_value = max(
                float(default_level["max_lux"]),
                previous_breakpoint + 1.0,
            )

        breakpoints.append(breakpoint_value)
        previous_breakpoint = breakpoint_value

    normalized_levels: list[dict[str, float | int | None]] = []

    for index, brightness_value in enumerate(brightness_values):
        if index == 0:
            min_lux = 0.0
        else:
            min_lux = breakpoints[index - 1]

        max_lux: float | None = None

        if index < len(breakpoints):
            max_lux = breakpoints[index]

        normalized_levels.append(
            {
                "min_lux": min_lux,
                "max_lux": max_lux,
                "brightness": brightness_value,
            }
        )

    return normalized_levels


def normalize_lumina_orientation(text: str) -> str:
    """
    @brief 标准化 Lumina 朝向字符串。
    @param text 用户输入或设备消息中的朝向文本。
    @return 返回标准化后的 X+/X-/Y+/Y- 文本。
    """

    orientation = text.strip().upper()

    if orientation not in ORIENTATION_TO_STEP:
        raise ValueError("朝向必须是 X+、X-、Y+ 或 Y-")

    return orientation


def normalize_device_key(value: object) -> str:
    """
    @brief 标准化 Lumina 设备 key。
    @param value 配置文件或 HID 枚举中的设备 key。
    @return 返回非空设备 key。
    """

    device_key = str(value or "").strip()

    if not device_key:
        return "default"

    return device_key


def normalize_reported_device_key(device_id: object) -> str | None:
    """
    @brief 将 Lumina 上报的设备 ID 标准化为稳定设备 key。
    @param device_id Lumina HID 报告中的设备 ID。
    @return 返回稳定设备 key，ID 无效时返回 None。
    """

    normalized_id = str(device_id or "").strip().upper()

    if not normalized_id:
        return None

    if set(normalized_id) <= {"0"}:
        return None

    return f"id:{normalized_id}"


def normalize_brightness_display_indexes(value: object) -> list[int]:
    """
    @brief 标准化显示器自动亮度绑定列表。
    @param value 配置文件中的显示器索引列表。
    @return 返回去重后的显示器索引列表。
    """

    if not isinstance(value, list):
        return []

    normalized_indexes: list[int] = []

    for item in value:
        try:
            display_index = int(item)
        except (TypeError, ValueError):
            continue

        if display_index <= 0:
            continue

        if display_index in normalized_indexes:
            continue

        normalized_indexes.append(display_index)

    return normalized_indexes


def make_default_device_config(
    device_key: str = "default",
    label: str = "Lumina#1",
) -> LuminaDeviceConfig:
    """
    @brief 创建默认 Lumina 单设备配置。
    @param device_key Lumina 设备 key。
    @param label UI 显示标签。
    @return 返回默认单设备配置。
    """

    return LuminaDeviceConfig(
        device_key=normalize_device_key(device_key),
        label=label,
        display_index=1,
        home_orientation="X+",
        enabled=False,
        brightness_mode="manual",
        brightness_display_indexes=[],
        brightness_levels=[dict(level) for level in DEFAULT_BRIGHTNESS_LEVELS],
    )


def build_device_config_from_data(
    config_data: dict,
    fallback_key: str,
    fallback_label: str,
) -> LuminaDeviceConfig:
    """
    @brief 从配置字典构建单台 Lumina 配置。
    @param config_data 配置字典。
    @param fallback_key 缺省设备 key。
    @param fallback_label 缺省 UI 标签。
    @return 返回单台 Lumina 配置。
    """

    brightness_mode = normalize_brightness_mode(
        str(config_data.get("brightness_mode", "manual"))
    )
    brightness_display_indexes = normalize_brightness_display_indexes(
        config_data.get("brightness_display_indexes")
    )

    if (
        "brightness_display_indexes" not in config_data
        and brightness_mode == "auto"
    ):
        brightness_display_indexes = [1, 2, 3]

    return LuminaDeviceConfig(
        device_key=normalize_device_key(
            config_data.get("device_key", fallback_key)
        ),
        label=str(config_data.get("label", fallback_label) or fallback_label),
        display_index=int(config_data.get("display_index", 1)),
        home_orientation=normalize_lumina_orientation(
            str(config_data.get("home_orientation", "X+"))
        ),
        enabled=bool(config_data.get("enabled", True)),
        brightness_mode=brightness_mode,
        brightness_display_indexes=brightness_display_indexes,
        brightness_levels=normalize_brightness_levels(
            config_data.get("brightness_levels")
        ),
    )


def convert_device_to_orientation_config(
    device_config: LuminaDeviceConfig,
) -> LuminaOrientationConfig:
    """
    @brief 将多设备配置中的单台设备转换为旧版配置对象。
    @param device_config 单台 Lumina 配置。
    @return 返回旧版 LuminaOrientationConfig。
    """

    return LuminaOrientationConfig(
        display_index=device_config.display_index,
        home_orientation=device_config.home_orientation,
        enabled=device_config.enabled,
        brightness_mode=device_config.brightness_mode,
        brightness_levels=normalize_brightness_levels(
            device_config.brightness_levels
        ),
    )


def device_config_to_data(
    device_config: LuminaDeviceConfig,
) -> dict:
    """
    @brief 将单台 Lumina 配置转换为可写入 JSON 的字典。
    @param device_config 单台 Lumina 配置。
    @return 返回 JSON 字典。
    """

    return {
        "device_key": normalize_device_key(device_config.device_key),
        "label": device_config.label,
        "display_index": int(device_config.display_index),
        "home_orientation": normalize_lumina_orientation(
            device_config.home_orientation
        ),
        "enabled": bool(device_config.enabled),
        "brightness_mode": normalize_brightness_mode(
            device_config.brightness_mode
        ),
        "brightness_display_indexes": normalize_brightness_display_indexes(
            device_config.brightness_display_indexes
        ),
        "brightness_levels": normalize_brightness_levels(
            device_config.brightness_levels
        ),
    }


def load_multi_config(config_path: Path) -> LuminaMultiConfig:
    """
    @brief 从文件加载多 Lumina 配置。
    @param config_path 配置文件路径。
    @return 返回多 Lumina 配置。
    """

    with config_path.open("r", encoding="utf-8") as config_file:
        config_data = json.load(config_file)

    if isinstance(config_data, dict) and isinstance(config_data.get("devices"), list):
        devices: list[LuminaDeviceConfig] = []

        for index, item in enumerate(config_data["devices"], start=1):
            if not isinstance(item, dict):
                continue

            devices.append(
                build_device_config_from_data(
                    item,
                    f"configured-{index}",
                    f"Lumina#{index}",
                )
            )

        if devices:
            return LuminaMultiConfig(devices=devices)

    if not isinstance(config_data, dict):
        raise ValueError("Lumina 配置文件格式无效。")

    return LuminaMultiConfig(
        devices=[
            build_device_config_from_data(
                config_data,
                "default",
                "Lumina#1",
            )
        ]
    )


def load_multi_config_or_default(config_path: Path) -> LuminaMultiConfig:
    """
    @brief 加载多 Lumina 配置，文件不存在或损坏时返回默认配置。
    @param config_path 配置文件路径。
    @return 返回多 Lumina 配置。
    """

    if not config_path.exists():
        logger.info("Lumina 配置文件不存在，使用默认配置: %s", config_path)
        return LuminaMultiConfig(
            devices=[
                make_default_device_config(),
            ]
        )

    try:
        return load_multi_config(config_path)
    except Exception as error:
        logger.warning("加载 Lumina 配置失败，使用默认配置: %s", error)
        return LuminaMultiConfig(
            devices=[
                make_default_device_config(),
            ]
        )


def save_multi_config(config_path: Path, config: LuminaMultiConfig) -> None:
    """
    @brief 保存多 Lumina 配置到文件。
    @param config_path 配置文件路径。
    @param config 待保存的多 Lumina 配置。
    @return None
    """

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_data = {
        "version": 2,
        "devices": [
            device_config_to_data(device_config)
            for device_config in config.devices
        ],
    }

    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(config_data, config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")


def load_config(config_path: Path) -> LuminaOrientationConfig:
    """
    @brief 从文件加载 Lumina 屏幕方向配置。
    @param config_path 配置文件路径。
    @return 返回 Lumina 屏幕方向配置。
    """

    multi_config = load_multi_config(config_path)

    return convert_device_to_orientation_config(multi_config.devices[0])


def load_config_or_default(config_path: Path) -> LuminaOrientationConfig:
    """
    @brief 加载 Lumina 配置，文件不存在或损坏时返回默认配置。
    @param config_path 配置文件路径。
    @return 返回 Lumina 屏幕方向配置。
    """

    try:
        return load_config(config_path)
    except Exception:
        return convert_device_to_orientation_config(make_default_device_config())


def save_config(config_path: Path, config: LuminaOrientationConfig) -> None:
    """
    @brief 保存 Lumina 屏幕方向配置到文件。
    @param config_path 配置文件路径。
    @param config 待保存的 Lumina 屏幕方向配置。
    @return None
    """

    config_data = {
        "display_index": config.display_index,
        "home_orientation": config.home_orientation,
        "enabled": config.enabled,
        "brightness_mode": config.brightness_mode,
        "brightness_levels": normalize_brightness_levels(config.brightness_levels),
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(config_data, config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")


def configure_service(config_path: Path) -> None:
    """
    @brief 交互式配置 Lumina 绑定的显示器与正放朝向。
    @param config_path 配置文件路径。
    @return None
    """

    display_infos = get_display_rotation_infos()
    print_display_infos(display_infos)

    display_index_text = input("请输入 Lumina 所在显示器索引: ").strip()
    display_index = int(display_index_text)
    display_info = get_display_info_by_index(display_index)

    home_orientation = normalize_lumina_orientation(
        input("屏幕正放时 Lumina 当前朝向是 X+、X-、Y+ 还是 Y-: ")
    )

    config = LuminaOrientationConfig(
        display_index=display_info.index,
        home_orientation=home_orientation,
        enabled=True,
        brightness_mode="manual",
        brightness_levels=[dict(level) for level in DEFAULT_BRIGHTNESS_LEVELS],
    )
    save_config(config_path, config)

    print(
        f"已保存配置: 显示器 [{display_info.index}] "
        f"{display_info.device_name}, 正放朝向 {home_orientation}"
    )


def list_hid_devices() -> None:
    """
    @brief 打印当前可用 HID 设备列表。
    @return None
    """

    hid = import_hid_module()
    devices = list(hid.enumerate())

    if not devices:
        print("未找到 HID 设备。")
        return

    for device in devices:
        print(
            f"{decode_hid_text(device.get('path'))} | "
            f"{decode_hid_text(device.get('product_string'))} | "
            f"VID={format_optional_hex(device.get('vendor_id'))} "
            f"PID={format_optional_hex(device.get('product_id'))}"
        )


def get_display_choices() -> list[tuple[int, str]]:
    """
    @brief 获取可供 UI 选择的显示器列表。
    @return 返回显示器索引与描述文本列表。
    """

    choices: list[tuple[int, str]] = []

    for display_info in get_display_rotation_infos():
        label = f"[{display_info.index}] {display_info.monitor_name}"
        if display_info.is_primary:
            label = f"{label} 主屏"

        choices.append((display_info.index, label))

    return choices


def format_optional_hex(value: int | None) -> str:
    """
    @brief 格式化可选十六进制数值。
    @param value 待格式化的数值。
    @return 返回十六进制文本，没有数值时返回 None。
    """

    if value is None:
        return "None"

    return f"0x{value:04X}"


def decode_hid_text(value: object) -> str:
    """
    @brief 将 hidapi 返回的路径或字符串转换为可显示文本。
    @param value hidapi 返回的字段值。
    @return 返回可显示文本。
    """

    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")

    return str(value)


def is_lumina_hid_device(device_info: dict) -> bool:
    """
    @brief 根据 HID 设备描述符判断是否为 Lumina 设备。
    @param device_info hidapi 返回的设备信息。
    @return 是 Lumina 设备返回 True，否则返回 False。
    """

    if (
        device_info.get("vendor_id") == LUMINA_USB_VID
        and device_info.get("product_id") == LUMINA_USB_PID
    ):
        return True

    product = decode_hid_text(device_info.get("product_string"))
    manufacturer = decode_hid_text(device_info.get("manufacturer_string"))

    if LUMINA_USB_PRODUCT_KEYWORD.lower() in product.lower():
        return True

    if LUMINA_USB_PRODUCT_KEYWORD.lower() in manufacturer.lower():
        return True

    return False


def enumerate_lumina_hid_devices() -> list[dict]:
    """
    @brief 枚举当前系统中识别到的 Lumina HID 设备。
    @return list[dict] 返回 hidapi 设备信息列表。
    """

    hid = import_hid_module()
    return [
        device
        for device in hid.enumerate()
        if is_lumina_hid_device(device)
    ]


def count_lumina_hid_devices() -> int:
    """
    @brief 获取当前系统中识别到的 Lumina HID 设备数量。
    @return int 返回 Lumina HID 设备数量，获取失败时返回 0。
    """

    try:
        return len(enumerate_lumina_hid_devices())
    except Exception:
        return 0


def find_lumina_hid_path() -> bytes | str:
    """
    @brief 自动查找 Lumina HID 设备路径。
    @return 返回识别到的 Lumina HID 设备路径。
    """

    matches = enumerate_lumina_hid_devices()

    if len(matches) == 1:
        return matches[0]["path"]

    if len(matches) > 1:
        names = [decode_hid_text(device.get("path")) for device in matches]
        raise RuntimeError(f"找到多个 Lumina HID 设备: {', '.join(names)}")

    raise RuntimeError("未自动识别到 Lumina HID 设备，请确认设备已连接且固件已烧录。")


def open_lumina_hid_device(path: bytes | str | None):
    """
    @brief 打开 Lumina HID 设备。
    @param path HID 设备路径；为 None 时自动查找。
    @return 返回已经打开的 HID 设备对象。
    """

    hid = import_hid_module()
    device = hid.device()

    if path is None:
        path = find_lumina_hid_path()

    if isinstance(path, str):
        path = path.encode("utf-8")

    device.open_path(path)
    return device


def parse_lumina_hid_report(report: bytes | bytearray | list[int]) -> LuminaHidEvent | None:
    """
    @brief 解析 Lumina HID 输入报告。
    @param report hidapi 读取到的输入报告。
    @return 成功返回 Lumina HID 事件，不是 Lumina 报告时返回 None。
    """

    data = bytes(report)

    if len(data) < LUMINA_HID_REPORT_SIZE:
        return None

    if data[0] != LUMINA_HID_REPORT_ID:
        return None

    event_type = data[1]
    orientation = LUMINA_HID_ORIENTATION_TO_TEXT.get(data[2])
    lux_milli = int.from_bytes(data[6:10], byteorder="little", signed=False)
    sequence = int.from_bytes(data[10:12], byteorder="little", signed=False)
    device_id = data[12:12 + LUMINA_HID_DEVICE_ID_SIZE].hex().upper()
    lux = lux_milli / 1000.0

    return LuminaHidEvent(
        event_type=event_type,
        orientation=orientation,
        lux=lux,
        device_id=device_id,
        sequence=sequence,
    )


def calculate_brightness_from_lux(
    lux_value: float,
    levels: list[dict[str, float | int | None]] | None,
) -> int:
    """
    @brief 根据环境亮度和档位配置计算目标亮度。
    @param lux_value 环境亮度，单位为 lux。
    @param levels 自动亮度档位配置。
    @return 返回目标亮度百分比。
    """

    normalized_levels = normalize_brightness_levels(levels)

    for level in normalized_levels:
        min_lux = float(level["min_lux"])
        max_lux = level["max_lux"]

        if lux_value < min_lux:
            continue

        if max_lux is not None and lux_value >= float(max_lux):
            continue

        return normalize_brightness_percentage(level["brightness"])

    return normalize_brightness_percentage(normalized_levels[-1]["brightness"])


def calculate_brightness_level_label(
    lux_value: float,
    levels: list[dict[str, float | int | None]] | None,
) -> str:
    """
    @brief 根据环境亮度和档位配置计算当前档位标签。
    @param lux_value 环境亮度，单位为 lux。
    @param levels 自动亮度档位配置。
    @return 返回当前档位标签。
    """

    normalized_levels = normalize_brightness_levels(levels)

    for index, level in enumerate(normalized_levels):
        min_lux = float(level["min_lux"])
        max_lux = level["max_lux"]

        if lux_value < min_lux:
            continue

        if max_lux is not None and lux_value >= float(max_lux):
            continue

        return format_brightness_level_range_label(level)

    return format_brightness_level_range_label(normalized_levels[-1])


def calculate_target_orientation(home_orientation: str, current_orientation: str) -> int:
    """
    @brief 根据正放基准朝向和当前朝向计算 Windows 显示方向。
    @param home_orientation 屏幕正放时 Lumina 的朝向。
    @param current_orientation 当前 Lumina 的朝向。
    @return 返回 Windows 显示方向常量。
    """

    home_step = ORIENTATION_TO_STEP[home_orientation]
    current_step = ORIENTATION_TO_STEP[current_orientation]
    relative_step = (current_step - home_step) % 4

    return STEP_TO_WINDOWS_ORIENTATION[relative_step]


def apply_lumina_orientation(
    config: LuminaOrientationConfig,
    current_orientation: str,
    persist: bool,
) -> None:
    """
    @brief 根据 Lumina 当前朝向旋转绑定的显示器。
    @param config Lumina 屏幕方向配置。
    @param current_orientation 当前 Lumina 的朝向。
    @param persist 是否持久化 Windows 显示方向。
    @return None
    """

    target_orientation = calculate_target_orientation(
        config.home_orientation,
        current_orientation,
    )
    display_info, result_code = set_display_orientation_by_index(
        config.display_index,
        target_orientation,
        persist,
    )

    print(
        f"收到 {current_orientation}，显示器 [{display_info.index}] "
        f"切换到 {orientation_value_to_label(target_orientation)}，"
        f"结果: {get_change_result_text(result_code)}"
    )


class LuminaOrientationWorker:
    """
    @brief 在后台线程中监听多台 Lumina 并自动旋转绑定显示器。
    @note 设备拔出或 HID 异常时不会退出程序，会进入重连循环。
    """

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        """
        @brief 初始化 Lumina 方向监听 worker。
        @param config_path 配置文件路径。
        @return None
        """

        self._config_path = config_path
        self._multi_config = load_multi_config_or_default(config_path)
        self._configs = {
            normalize_device_key(device_config.device_key): device_config
            for device_config in self._multi_config.devices
        }
        self._statuses: dict[str, LuminaDeviceStatus] = {}
        self._device_threads: dict[str, threading.Thread] = {}
        self._device_paths: dict[str, bytes | str] = {}
        self._path_device_keys: dict[str, str] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

        with self._lock:
            if self._ensure_unique_labels_locked():
                self._refresh_multi_config_locked()
                save_config_data = self._copy_multi_config_locked()
            else:
                save_config_data = None

        if save_config_data is not None:
            save_multi_config(self._config_path, save_config_data)

    def start(self) -> None:
        """
        @brief 启动后台监听线程。
        @return None
        """

        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="LuminaOrientationManager",
        )
        self._thread.start()

    def stop(self) -> None:
        """
        @brief 请求停止后台监听线程。
        @return None
        """

        self._stop_event.set()
        self._wake_event.set()

        if self._thread is not None:
            self._thread.join(timeout=3.0)

        for device_thread in list(self._device_threads.values()):
            device_thread.join(timeout=1.5)

    def get_status(self) -> LuminaOrientationStatus:
        """
        @brief 获取第一台 Lumina 的运行状态快照。
        @return 返回 Lumina 方向服务状态。
        @note 该接口用于兼容旧 UI；多设备 UI 应使用 get_device_snapshots。
        """

        with self._lock:
            connected_count = self._get_connected_count_locked()
            primary_config = self._get_primary_config_locked()
            primary_status = self._get_status_for_config_locked(
                primary_config,
                connected_count,
            )
            return self._copy_orientation_status(primary_status)

    def get_config(self) -> LuminaOrientationConfig:
        """
        @brief 获取第一台 Lumina 的配置快照。
        @return 返回 Lumina 屏幕方向配置。
        @note 该接口用于兼容旧 UI；多设备 UI 应使用 get_device_snapshots。
        """

        with self._lock:
            return convert_device_to_orientation_config(
                self._get_primary_config_locked()
            )

    def update_config(
        self,
        display_index: int,
        home_orientation: str,
        enabled: bool,
        brightness_mode: str | None = None,
        brightness_levels: list[dict[str, float | int | None]] | None = None,
    ) -> None:
        """
        @brief 更新 Lumina 方向服务配置。
        @param display_index 绑定的显示器索引。
        @param home_orientation 屏幕正放时 Lumina 的朝向。
        @param enabled 是否启用自动旋转。
        @param brightness_mode 亮度调节模式。
        @param brightness_levels 自动亮度档位配置。
        @return None
        """

        with self._lock:
            device_key = self._get_primary_config_locked().device_key

        self.update_device_config(
            device_key,
            display_index=display_index,
            home_orientation=home_orientation,
            enabled=enabled,
            brightness_mode=brightness_mode,
            brightness_levels=brightness_levels,
        )

    def update_device_config(
        self,
        device_key: str,
        display_index: int,
        home_orientation: str,
        enabled: bool,
        brightness_mode: str | None = None,
        brightness_levels: list[dict[str, float | int | None]] | None = None,
    ) -> None:
        """
        @brief 更新指定 Lumina 的方向与自动亮度配置。
        @param device_key Lumina 设备 key。
        @param display_index 绑定的显示器索引。
        @param home_orientation 屏幕正放时 Lumina 的朝向。
        @param enabled 是否启用自动旋转。
        @param brightness_mode 亮度调节模式。
        @param brightness_levels 自动亮度档位配置。
        @return None
        """

        normalized_key = normalize_device_key(device_key)

        with self._lock:
            old_config = self._configs.get(normalized_key)

            if old_config is None:
                old_config = make_default_device_config(
                    normalized_key,
                    self._make_default_label_locked(),
                )

            config = LuminaDeviceConfig(
                device_key=normalized_key,
                label=old_config.label,
                display_index=display_index,
                home_orientation=normalize_lumina_orientation(home_orientation),
                enabled=enabled,
                brightness_mode=normalize_brightness_mode(
                    brightness_mode
                    if brightness_mode is not None
                    else old_config.brightness_mode
                ),
                brightness_display_indexes=normalize_brightness_display_indexes(
                    old_config.brightness_display_indexes
                ),
                brightness_levels=normalize_brightness_levels(
                    brightness_levels
                    if brightness_levels is not None
                    else old_config.brightness_levels
                ),
            )
            self._configs[normalized_key] = config
            self._refresh_multi_config_locked()

            if normalized_key in self._statuses:
                self._statuses[normalized_key].enabled = enabled
                self._statuses[normalized_key].message = (
                    "已启用，等待设备" if enabled else "已暂停"
                )

            save_config_data = self._copy_multi_config_locked()

        save_multi_config(self._config_path, save_config_data)
        self._wake_event.set()

        if enabled:
            self.apply_current_orientation_if_available(normalized_key)

        logger.info(
            "Lumina [%s] 配置已更新: display_index=%s, home_orientation=%s, "
            "enabled=%s, brightness_mode=%s。",
            normalized_key,
            display_index,
            home_orientation,
            enabled,
            brightness_mode,
        )

    def apply_current_orientation_if_available(self, device_key: str) -> None:
        """
        @brief 当前朝向可用时立即应用指定 Lumina 的自动旋转配置。
        @param device_key Lumina 设备 key。
        @return None
        @note 用于开启自动旋转或修改绑定配置后立即校正显示方向。
        """

        normalized_key = normalize_device_key(device_key)

        with self._lock:
            config = self._configs.get(normalized_key)
            status = self._statuses.get(normalized_key)

            if config is None or status is None:
                return

            if not config.enabled or status.current_orientation is None:
                return

            current_orientation = status.current_orientation

        try:
            self._apply_device_orientation(normalized_key, current_orientation)
        except Exception as error:
            logger.warning(
                "Lumina [%s] 立即应用方向失败: %s。",
                normalized_key,
                error,
            )

    def update_brightness_binding(
        self,
        monitor_index: int,
        device_key: str | None,
    ) -> None:
        """
        @brief 更新显示器到 Lumina 的自动亮度绑定关系。
        @param monitor_index 显示器索引。
        @param device_key Lumina 设备 key；传入 None 表示解除绑定。
        @return None
        """

        if monitor_index <= 0:
            return

        normalized_key = (
            normalize_device_key(device_key)
            if device_key is not None
            else None
        )

        with self._lock:
            for config in self._configs.values():
                config.brightness_display_indexes = [
                    display_index
                    for display_index in normalize_brightness_display_indexes(
                        config.brightness_display_indexes
                    )
                    if display_index != monitor_index
                ]

            if normalized_key is not None and normalized_key in self._configs:
                target_config = self._configs[normalized_key]
                target_config.brightness_display_indexes.append(monitor_index)

            self._refresh_multi_config_locked()
            save_config_data = self._copy_multi_config_locked()

        save_multi_config(self._config_path, save_config_data)
        self._wake_event.set()
        logger.info(
            "显示器 [%s] 自动亮度绑定更新为 %s。",
            monitor_index,
            normalized_key or "手动",
        )

    def set_enabled(self, enabled: bool) -> None:
        """
        @brief 设置 Lumina 自动旋转启用状态。
        @param enabled 是否启用自动旋转。
        @return None
        """

        config = self.get_config()
        self.update_config(
            config.display_index,
            config.home_orientation,
            enabled,
            config.brightness_mode,
            config.brightness_levels,
        )

    def get_device_config(self, device_key: str) -> LuminaDeviceConfig:
        """
        @brief 获取指定 Lumina 的配置快照。
        @param device_key Lumina 设备 key。
        @return 返回单台 Lumina 配置。
        """

        normalized_key = normalize_device_key(device_key)

        with self._lock:
            config = self._configs.get(normalized_key)

            if config is None:
                config = make_default_device_config(
                    normalized_key,
                    self._make_default_label_locked(),
                )

            return self._copy_device_config(config)

    def get_device_snapshots(self) -> list[LuminaDeviceSnapshot]:
        """
        @brief 获取所有 Lumina 的 UI 快照。
        @return 返回 Lumina 设备快照列表。
        """

        with self._lock:
            connected_count = self._get_connected_count_locked()
            snapshots: list[LuminaDeviceSnapshot] = []

            for config in self._get_sorted_configs_locked():
                status = self._get_status_for_config_locked(
                    config,
                    connected_count,
                )

                if not status.connected:
                    continue

                level_label = self._calculate_level_label_locked(config, status)
                snapshots.append(
                    LuminaDeviceSnapshot(
                        config=self._copy_device_config(config),
                        status=self._copy_device_status(status),
                        brightness_level_label=level_label,
                    )
                )

            return snapshots[:3]

    def get_brightness_binding_map(self) -> dict[int, str]:
        """
        @brief 获取显示器到 Lumina 的自动亮度绑定表。
        @return dict[int, str] 以显示器索引为键、Lumina 设备 key 为值。
        """

        with self._lock:
            binding_map: dict[int, str] = {}

            for config in self._configs.values():
                for display_index in normalize_brightness_display_indexes(
                    config.brightness_display_indexes
                ):
                    binding_map[display_index] = config.device_key

            return binding_map

    def get_auto_brightness_targets_by_display(self) -> dict[int, int]:
        """
        @brief 获取每块显示器当前对应的 Lumina 自动亮度目标。
        @return dict[int, int] 以显示器索引为键、亮度百分比为值。
        """

        with self._lock:
            targets: dict[int, int] = {}

            for config in self._configs.values():
                status = self._statuses.get(config.device_key)

                if status is None:
                    continue

                if not status.connected:
                    continue

                if config.brightness_mode != "auto":
                    continue

                if status.current_lux is None:
                    continue

                target = calculate_brightness_from_lux(
                    status.current_lux,
                    config.brightness_levels,
                )

                for display_index in normalize_brightness_display_indexes(
                    config.brightness_display_indexes
                ):
                    targets[display_index] = target

            return targets

    def get_auto_brightness_target(self) -> int | None:
        """
        @brief 获取第一块绑定显示器的自动亮度目标。
        @return 自动模式且有 lux 数据时返回亮度百分比，否则返回 None。
        @note 该接口用于兼容旧调用，多显示器应使用 get_auto_brightness_targets_by_display。
        """

        targets = self.get_auto_brightness_targets_by_display()

        if not targets:
            return None

        first_display_index = sorted(targets)[0]
        return targets[first_display_index]

    def get_auto_brightness_level_label(
        self,
        device_key: str | None = None,
    ) -> str | None:
        """
        @brief 获取当前环境亮度对应的自动亮度档位标签。
        @param device_key Lumina 设备 key；传入 None 表示第一台设备。
        @return 自动模式且有 lux 数据时返回档位标签，否则返回 None。
        """

        with self._lock:
            if device_key is None:
                config = self._get_primary_config_locked()
            else:
                config = self._configs.get(normalize_device_key(device_key))

            if config is None:
                return None

            status = self._statuses.get(config.device_key)

            if status is None:
                return None

            return self._calculate_level_label_locked(config, status)

    def _set_status(
        self,
        connected: bool,
        device_count: int,
        port_name: str | None,
        current_orientation: str | None,
        current_lux: float | None,
        message: str,
    ) -> None:
        """
        @brief 更新后台服务状态。
        @param connected 是否已经连接 Lumina。
        @param device_count 当前识别到的 Lumina 设备数量。
        @param port_name 当前 HID 设备路径。
        @param current_orientation 当前朝向。
        @param current_lux 当前环境亮度。
        @param message 状态说明。
        @return None
        """

        with self._lock:
            config = self._get_primary_config_locked()
            self._statuses[config.device_key] = LuminaDeviceStatus(
                device_key=config.device_key,
                label=config.label,
                enabled=config.enabled,
                connected=connected,
                device_count=device_count,
                port_name=port_name,
                current_orientation=current_orientation,
                current_lux=current_lux,
                message=message,
            )

    def _thread_main(self) -> None:
        """
        @brief 后台管理线程主循环。
        @return None
        """

        while not self._stop_event.is_set():
            try:
                self._refresh_connected_devices()
            except Exception as error:
                self._mark_all_devices_disconnected(f"重连中: {error}")
                logger.warning("Lumina 设备枚举失败: %s", error)

            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()

    def _refresh_connected_devices(self) -> None:
        """
        @brief 刷新当前连接的 Lumina，并为每台设备启动读取线程。
        @return None
        """

        devices = sorted(
            enumerate_lumina_hid_devices(),
            key=lambda device: decode_hid_text(device.get("path")),
        )
        limited_devices = devices[:MAX_LUMINA_DEVICE_COUNT]
        connected_keys: set[str] = set()
        should_save_config = False

        with self._lock:
            for index, device in enumerate(limited_devices, start=1):
                path = device.get("path")

                if path is None:
                    continue

                path_key = normalize_device_key(decode_hid_text(path))
                device_key = self._path_device_keys.get(path_key, path_key)
                proposed_label = f"Lumina#{index}"
                config, config_changed = self._get_or_create_config_locked(
                    device_key,
                    proposed_label,
                )
                should_save_config = should_save_config or config_changed
                label = config.label or proposed_label

                if not config.label:
                    config.label = label
                    should_save_config = True

                self._path_device_keys[path_key] = config.device_key
                connected_keys.add(config.device_key)
                self._device_paths[config.device_key] = path
                self._set_device_status_locked(
                    config.device_key,
                    True,
                    len(limited_devices),
                    decode_hid_text(path),
                    self._statuses.get(config.device_key).current_orientation
                    if config.device_key in self._statuses
                    else None,
                    self._statuses.get(config.device_key).current_lux
                    if config.device_key in self._statuses
                    else None,
                    "已连接",
                )

                thread = self._device_threads.get(config.device_key)

                if thread is None or not thread.is_alive():
                    self._start_device_thread_locked(
                        config.device_key,
                        path,
                        label,
                    )

            for config in self._configs.values():
                if config.device_key in connected_keys:
                    continue

                self._set_device_status_locked(
                    config.device_key,
                    False,
                    len(limited_devices),
                    None,
                    self._statuses.get(config.device_key).current_orientation
                    if config.device_key in self._statuses
                    else None,
                    self._statuses.get(config.device_key).current_lux
                    if config.device_key in self._statuses
                    else None,
                    "未连接",
                )

            should_save_config = (
                self._ensure_unique_labels_locked()
                or should_save_config
            )
            self._refresh_multi_config_locked()
            save_config_data = self._copy_multi_config_locked()

        if should_save_config:
            save_multi_config(self._config_path, save_config_data)

    def _device_thread_main(
        self,
        device_key: str,
        path: bytes | str,
        label: str,
    ) -> None:
        """
        @brief 单台 Lumina 的 HID 读取线程。
        @param device_key Lumina 设备 key。
        @param path HID 设备路径。
        @param label UI 显示标签。
        @return None
        """

        path_text = decode_hid_text(path)
        last_orientation: str | None = None
        last_lux: float | None = None
        hid_device = None

        try:
            hid_device = open_lumina_hid_device(path)
            logger.info("Lumina [%s] 已连接: %s。", label, path_text)

            while not self._stop_event.is_set():
                report = hid_device.read(LUMINA_HID_REPORT_SIZE, 1000)

                if not report:
                    continue

                event = parse_lumina_hid_report(report)

                if event is None:
                    continue

                stable_device_key = normalize_reported_device_key(
                    event.device_id
                )

                if stable_device_key is not None and stable_device_key != device_key:
                    device_key = self._migrate_device_key(
                        device_key,
                        stable_device_key,
                        label,
                    )

                if event.lux is not None:
                    last_lux = event.lux

                if event.orientation is not None:
                    if event.orientation != last_orientation:
                        last_orientation = event.orientation
                        self._apply_device_orientation(
                            device_key,
                            event.orientation,
                        )

                with self._lock:
                    self._set_device_status_locked(
                        device_key,
                        True,
                        self._get_connected_count_locked(),
                        path_text,
                        last_orientation,
                        last_lux,
                        "已连接",
                    )
        except Exception as error:
            with self._lock:
                self._set_device_status_locked(
                    device_key,
                    False,
                    self._get_connected_count_locked(),
                    None,
                    last_orientation,
                    last_lux,
                    f"重连中: {error}",
                )
            logger.warning("Lumina [%s] 读取线程退出: %s。", label, error)
        finally:
            if hid_device is not None:
                try:
                    hid_device.close()
                except Exception:
                    pass

    def _apply_device_orientation(
        self,
        device_key: str,
        current_orientation: str,
    ) -> None:
        """
        @brief 按指定 Lumina 的绑定关系应用显示方向。
        @param device_key Lumina 设备 key。
        @param current_orientation 当前 Lumina 朝向。
        @return None
        """

        config = self.get_device_config(device_key)

        if not config.enabled:
            return

        apply_lumina_orientation(
            convert_device_to_orientation_config(config),
            current_orientation,
            True,
        )

    def _migrate_device_key(
        self,
        old_device_key: str,
        new_device_key: str,
        label: str,
    ) -> str:
        """
        @brief 将临时 HID 路径 key 迁移为 Lumina 上报的稳定设备 key。
        @param old_device_key 临时设备 key。
        @param new_device_key 稳定设备 key。
        @param label UI 显示标签。
        @return 返回迁移后的设备 key。
        """

        old_key = normalize_device_key(old_device_key)
        new_key = normalize_device_key(new_device_key)

        if old_key == new_key:
            return old_key

        with self._lock:
            path_key = None
            old_path = self._device_paths.get(old_key)

            if old_path is not None:
                path_key = normalize_device_key(decode_hid_text(old_path))

            old_config = self._configs.get(old_key)
            new_config = self._configs.get(new_key)

            if new_config is None and old_config is not None:
                self._configs.pop(old_key, None)
                old_config.device_key = new_key

                if not old_config.label:
                    old_config.label = label

                self._configs[new_key] = old_config
            elif new_config is not None and old_config is not None:
                if not new_config.brightness_display_indexes:
                    new_config.brightness_display_indexes = (
                        old_config.brightness_display_indexes
                    )

                if not new_config.label:
                    new_config.label = old_config.label or label

                self._configs.pop(old_key, None)

            target_config = self._configs.get(new_key)
            target_label = label

            if target_config is not None:
                target_label = target_config.label or label

            if old_key in self._statuses:
                status = self._statuses.pop(old_key)
                status.device_key = new_key
                status.label = target_label
                self._statuses[new_key] = status

            if old_key in self._device_paths:
                self._device_paths[new_key] = self._device_paths.pop(old_key)

            if old_key in self._device_threads:
                self._device_threads[new_key] = self._device_threads.pop(old_key)

            if path_key is not None:
                self._path_device_keys[path_key] = new_key

            self._ensure_unique_labels_locked()
            self._refresh_multi_config_locked()
            save_config_data = self._copy_multi_config_locked()

        save_multi_config(self._config_path, save_config_data)
        logger.info("Lumina 设备 key 已迁移: %s -> %s。", old_key, new_key)
        return new_key

    def _start_device_thread_locked(
        self,
        device_key: str,
        path: bytes | str,
        label: str,
    ) -> None:
        """
        @brief 启动单台 Lumina 的读取线程。
        @param device_key Lumina 设备 key。
        @param path HID 设备路径。
        @param label UI 显示标签。
        @return None
        """

        thread = threading.Thread(
            target=self._device_thread_main,
            args=(device_key, path, label),
            daemon=True,
            name=f"LuminaReader-{label}",
        )
        self._device_threads[device_key] = thread
        thread.start()

    def _mark_all_devices_disconnected(self, message: str) -> None:
        """
        @brief 将所有 Lumina 标记为未连接。
        @param message 状态说明。
        @return None
        """

        with self._lock:
            for config in self._configs.values():
                status = self._statuses.get(config.device_key)
                self._set_device_status_locked(
                    config.device_key,
                    False,
                    0,
                    None,
                    status.current_orientation if status is not None else None,
                    status.current_lux if status is not None else None,
                    message,
                )

    def _get_or_create_config_locked(
        self,
        device_key: str,
        label: str,
    ) -> tuple[LuminaDeviceConfig, bool]:
        """
        @brief 获取或创建指定 Lumina 的配置。
        @param device_key Lumina 设备 key。
        @param label UI 显示标签。
        @return 返回配置对象和配置是否变化。
        """

        normalized_key = normalize_device_key(device_key)

        if normalized_key in self._configs:
            config = self._configs[normalized_key]

            if not config.label:
                config.label = label
                return config, True

            return config, False

        for legacy_key in list(self._configs):
            if legacy_key not in LEGACY_DEVICE_KEYS:
                continue

            config = self._configs.pop(legacy_key)
            config.device_key = normalized_key
            config.label = label
            self._configs[normalized_key] = config
            return config, True

        config = make_default_device_config(normalized_key, label)
        self._configs[normalized_key] = config
        return config, True

    def _get_primary_config_locked(self) -> LuminaDeviceConfig:
        """
        @brief 获取第一台 Lumina 配置。
        @return 返回第一台 Lumina 配置。
        """

        configs = self._get_sorted_configs_locked()

        if configs:
            self._ensure_unique_labels_locked()
            return configs[0]

        config = make_default_device_config()
        self._configs[config.device_key] = config
        self._refresh_multi_config_locked()
        return config

    def _get_sorted_configs_locked(self) -> list[LuminaDeviceConfig]:
        """
        @brief 获取按 UI 标签排序后的 Lumina 配置列表。
        @return 返回 Lumina 配置列表。
        """

        return sorted(
            self._configs.values(),
            key=lambda config: (
                self._get_label_sort_index(config.label),
                config.label,
                config.device_key,
            ),
        )

    def _get_status_for_config_locked(
        self,
        config: LuminaDeviceConfig,
        device_count: int,
    ) -> LuminaDeviceStatus:
        """
        @brief 获取指定配置对应的状态，缺省时创建未连接状态。
        @param config Lumina 配置。
        @param device_count 当前连接的 Lumina 数量。
        @return 返回 Lumina 状态。
        """

        status = self._statuses.get(config.device_key)

        if status is not None:
            status.enabled = config.enabled
            status.label = config.label
            status.device_count = device_count
            return status

        status = LuminaDeviceStatus(
            device_key=config.device_key,
            label=config.label,
            enabled=config.enabled,
            connected=False,
            device_count=device_count,
            port_name=None,
            current_orientation=None,
            current_lux=None,
            message="未连接",
        )
        self._statuses[config.device_key] = status
        return status

    def _set_device_status_locked(
        self,
        device_key: str,
        connected: bool,
        device_count: int,
        port_name: str | None,
        current_orientation: str | None,
        current_lux: float | None,
        message: str,
    ) -> None:
        """
        @brief 更新单台 Lumina 的状态。
        @param device_key Lumina 设备 key。
        @param connected 是否已连接。
        @param device_count 当前连接的 Lumina 数量。
        @param port_name HID 设备路径。
        @param current_orientation 当前朝向。
        @param current_lux 当前环境亮度，单位为 lux。
        @param message 状态说明。
        @return None
        """

        config = self._configs.get(device_key)
        label = config.label if config is not None else device_key
        enabled = config.enabled if config is not None else False
        self._statuses[device_key] = LuminaDeviceStatus(
            device_key=device_key,
            label=label,
            enabled=enabled,
            connected=connected,
            device_count=device_count,
            port_name=port_name,
            current_orientation=current_orientation,
            current_lux=current_lux,
            message=message,
        )

    def _calculate_level_label_locked(
        self,
        config: LuminaDeviceConfig,
        status: LuminaDeviceStatus,
    ) -> str | None:
        """
        @brief 计算单台 Lumina 当前自动亮度档位标签。
        @param config Lumina 配置。
        @param status Lumina 状态。
        @return 返回档位标签，条件不足时返回 None。
        """

        if config.brightness_mode != "auto":
            return None

        if status.current_lux is None:
            return None

        return calculate_brightness_level_label(
            status.current_lux,
            config.brightness_levels,
        )

    def _get_connected_count_locked(self) -> int:
        """
        @brief 获取当前已连接 Lumina 数量。
        @return int 已连接设备数量。
        """

        return sum(
            1
            for status in self._statuses.values()
            if status.connected
        )

    def _make_default_label_locked(self) -> str:
        """
        @brief 生成新的 Lumina 默认 UI 标签。
        @return 返回默认 UI 标签。
        """

        used_indexes = {
            self._get_label_sort_index(config.label)
            for config in self._configs.values()
        }
        next_index = 1

        while next_index in used_indexes:
            next_index += 1

        return f"Lumina#{next_index}"

    def _ensure_unique_labels_locked(self) -> bool:
        """
        @brief 确保所有 Lumina 配置的 UI 标签唯一。
        @return bool 标签发生变化时返回 True。
        @note 该函数只在持有 self._lock 时调用。
        """

        changed = False
        used_labels: set[str] = set()

        for config in sorted(
            self._configs.values(),
            key=lambda item: (
                self._get_label_sort_index(item.label),
                item.label,
                item.device_key,
            ),
        ):
            label = config.label.strip()

            if not label or label in used_labels:
                label = self._make_next_unused_label_locked(used_labels)

                if config.label != label:
                    config.label = label
                    changed = True

            used_labels.add(label)

            status = self._statuses.get(config.device_key)

            if status is not None and status.label != config.label:
                status.label = config.label
                changed = True

        return changed

    def _make_next_unused_label_locked(self, used_labels: set[str]) -> str:
        """
        @brief 根据已占用标签生成下一个可用 Lumina 标签。
        @param used_labels 已占用标签集合。
        @return 返回未被占用的 Lumina#N 标签。
        @note 该函数只在持有 self._lock 时调用。
        """

        next_index = 1

        while f"Lumina#{next_index}" in used_labels:
            next_index += 1

        return f"Lumina#{next_index}"

    def _refresh_multi_config_locked(self) -> None:
        """
        @brief 刷新内存中的多 Lumina 配置对象。
        @return None
        """

        self._multi_config = LuminaMultiConfig(
            devices=[
                self._copy_device_config(config)
                for config in self._get_sorted_configs_locked()
            ]
        )

    def _copy_multi_config_locked(self) -> LuminaMultiConfig:
        """
        @brief 复制多 Lumina 配置对象用于无锁保存。
        @return 返回多 Lumina 配置副本。
        """

        return LuminaMultiConfig(
            devices=[
                self._copy_device_config(config)
                for config in self._get_sorted_configs_locked()
            ]
        )

    @staticmethod
    def _copy_device_config(
        config: LuminaDeviceConfig,
    ) -> LuminaDeviceConfig:
        """
        @brief 复制单台 Lumina 配置。
        @param config Lumina 配置。
        @return 返回配置副本。
        """

        return LuminaDeviceConfig(
            device_key=config.device_key,
            label=config.label,
            display_index=config.display_index,
            home_orientation=config.home_orientation,
            enabled=config.enabled,
            brightness_mode=config.brightness_mode,
            brightness_display_indexes=list(config.brightness_display_indexes),
            brightness_levels=normalize_brightness_levels(
                config.brightness_levels
            ),
        )

    @staticmethod
    def _copy_device_status(
        status: LuminaDeviceStatus,
    ) -> LuminaDeviceStatus:
        """
        @brief 复制单台 Lumina 状态。
        @param status Lumina 状态。
        @return 返回状态副本。
        """

        return LuminaDeviceStatus(
            device_key=status.device_key,
            label=status.label,
            enabled=status.enabled,
            connected=status.connected,
            device_count=status.device_count,
            port_name=status.port_name,
            current_orientation=status.current_orientation,
            current_lux=status.current_lux,
            message=status.message,
        )

    @staticmethod
    def _copy_orientation_status(
        status: LuminaDeviceStatus,
    ) -> LuminaOrientationStatus:
        """
        @brief 将单台 Lumina 状态复制为旧版状态对象。
        @param status Lumina 状态。
        @return 返回旧版 LuminaOrientationStatus。
        """

        return LuminaOrientationStatus(
            enabled=status.enabled,
            connected=status.connected,
            device_count=status.device_count,
            port_name=status.port_name,
            current_orientation=status.current_orientation,
            current_lux=status.current_lux,
            message=status.message,
        )

    @staticmethod
    def _get_label_sort_index(label: str) -> int:
        """
        @brief 从 Lumina#N 标签中提取排序序号。
        @param label UI 标签。
        @return 返回排序序号，无法解析时返回较大值。
        """

        if not label.startswith("Lumina#"):
            return 9999

        try:
            return int(label.split("#", 1)[1])
        except ValueError:
            return 9999


def run_service(arguments: argparse.Namespace) -> None:
    """
    @brief 运行 Lumina 方向监听服务。
    @param arguments 命令行参数对象。
    @return None
    """

    config = load_config(arguments.config)
    last_orientation: str | None = None
    device_path = arguments.path

    if device_path is None:
        device_path = find_lumina_hid_path()

    print(
        f"监听 {decode_hid_text(device_path)}，绑定显示器索引 {config.display_index}，"
        f"正放基准 {config.home_orientation}"
    )

    hid_device = open_lumina_hid_device(device_path)

    try:
        while True:
            report = hid_device.read(LUMINA_HID_REPORT_SIZE, 1000)

            if not report:
                continue

            event = parse_lumina_hid_report(report)

            if event is None:
                continue

            if event.orientation is None:
                continue

            if event.orientation == last_orientation:
                continue

            last_orientation = event.orientation
            apply_lumina_orientation(
                config,
                event.orientation,
                not arguments.no_persist,
            )
            time.sleep(arguments.cooldown)
    finally:
        hid_device.close()


def parse_arguments() -> argparse.Namespace:
    """
    @brief 解析命令行参数。
    @return 返回解析后的命令行参数对象。
    """

    parser = argparse.ArgumentParser(description="Lumina 屏幕方向上位机服务")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="配置文件路径",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ports", help="列出可用 HID 设备")
    subparsers.add_parser("config", help="配置设备绑定的显示器和正放朝向")

    run_parser = subparsers.add_parser("run", help="监听 Lumina 并自动旋转显示器")
    run_parser.add_argument("--path", help="Lumina HID 设备路径；不填写时自动识别")
    run_parser.add_argument("--cooldown", type=float, default=0.5, help="两次旋转之间的冷却秒数")
    run_parser.add_argument("--no-persist", action="store_true", help="不持久化 Windows 显示方向")

    return parser.parse_args()


def main() -> int:
    """
    @brief 程序入口。
    @return 成功返回 0，失败返回 1。
    """

    try:
        arguments = parse_arguments()

        if arguments.command == "ports":
            list_hid_devices()
            return 0

        if arguments.command == "config":
            configure_service(arguments.config)
            return 0

        if arguments.command == "run":
            run_service(arguments)
            return 0

        raise ValueError("未知命令")
    except KeyboardInterrupt:
        print("已退出。")
        return 0
    except Exception as error:
        print(f"执行失败: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
