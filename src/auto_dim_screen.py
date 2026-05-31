# -*- coding: utf-8 -*-
"""
@brief 基于窗口状态与鼠标位置自动调节显示器亮度的命令行工具。
@note 当某块屏幕上没有普通窗口且鼠标也不在该屏幕上时，在条件连续满足一段时间后调暗该屏幕；
      若该屏无窗口但鼠标仍在本屏，则当全局鼠标连续静止时间达到同一阈值后也调暗该屏幕。
"""

from __future__ import annotations

import argparse
import ctypes
import functools
import logging
import math
import os
import queue
import sys
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

from monitor_brightness import (
    MonitorBrightnessInfo,
    close_physical_monitors,
    ensure_windows_platform,
    enumerate_display_monitors,
    get_monitor_brightness_infos,
    open_physical_monitors,
    set_brightness_by_index,
    validate_brightness_percentage,
)
from lumina_orientation_service import (
    LuminaOrientationWorker,
    get_display_choices,
)
from lumina_logging import (
    APPLICATION_NAME,
    add_logging_arguments,
    configure_lumina_logging,
    log_and_print,
)

HRESULT = getattr(wintypes, "HRESULT", ctypes.c_long)

try:
    import pystray
except ImportError:
    pystray = None

try:
    from PIL import Image
except ImportError:
    Image = None

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CHILD = 0x40000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

DWMWA_CLOAKED = 14
MONITORINFOF_PRIMARY = 0x00000001

DEFAULT_DIM_DELAY_SECONDS = 5.0
DEFAULT_TRANSITION_DURATION_SECONDS = 2.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.1
DEFAULT_TRANSITION_TICK_SECONDS = 0.03
# 单屏失败日志输出间隔，单位为秒。
MONITOR_FAILURE_LOG_INTERVAL_SECONDS = 5.0
AUTOSTART_REGISTRY_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = APPLICATION_NAME
APPLICATION_ICON_RELATIVE_PATH = os.path.join("assets", "Lumina.png")
SOURCE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
APPLICATION_DIRECTORY = os.path.dirname(SOURCE_DIRECTORY)
logger = logging.getLogger(__name__)


class POINT(ctypes.Structure):
    """
    @brief 表示屏幕坐标点结构。
    @note 该结构与 Windows POINT 结构保持一致。
    """

    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class RECT(ctypes.Structure):
    """
    @brief 表示矩形区域结构。
    @note 该结构与 Windows RECT 结构保持一致。
    """

    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    """
    @brief 表示 Windows 显示器扩展信息结构。
    @note 该结构用于读取显示器的桌面区域与设备名。
    """

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


@dataclass
class MonitorEvaluationResult:
    """
    @brief 保存单块屏幕当前的窗口与鼠标判定结果。
    @note 该结果用于决定是否需要调暗该屏幕。
    """

    index: int
    window_count: int
    has_mouse: bool
    should_dim: bool
    bypass_stabilization_delay: bool


@dataclass
class MouseIdleTracker:
    """
    @brief 追踪鼠标屏幕坐标上次变化时刻，用于计算全局静止时长。
    @note 任意像素级移动均会重置静止计时。
    """

    last_point: POINT | None = None
    last_moved_at_monotonic: float = 0.0

    def update_and_get_idle_seconds(
        self,
        current_time: float,
        cursor_point: POINT | None,
    ) -> float:
        """
        @brief 根据当前鼠标位置更新上次移动时刻并返回已连续静止的秒数。
        @param current_time 当前单调时钟时间，单位为秒。
        @param cursor_point 当前鼠标坐标；为 None 时表示不可用，返回 0 且不更新状态。
        @return float 鼠标未移动的连续秒数；首次采样或坐标不可用时为 0。
        """

        if cursor_point is None:
            return 0.0

        if self.last_point is None:
            self.last_point = POINT(cursor_point.x, cursor_point.y)
            self.last_moved_at_monotonic = current_time
            return 0.0

        if (
            cursor_point.x != self.last_point.x
            or cursor_point.y != self.last_point.y
        ):
            self.last_point = POINT(cursor_point.x, cursor_point.y)
            self.last_moved_at_monotonic = current_time
            return 0.0

        return current_time - self.last_moved_at_monotonic


@dataclass
class ControlledMonitorState:
    """
    @brief 保存受控显示器的几何信息、亮度状态与渐变状态。
    @note 恢复亮度会在该屏幕稳定处于恢复状态时根据用户手动修改自动更新。
    """

    index: int
    description: str
    monitor_rect: RECT
    device_name: str
    is_primary: bool
    restore_brightness: int
    current_brightness: int
    current_mode: str | None = field(default=None)
    dim_condition_started_at: float | None = field(default=None)
    transition_target_mode: str | None = field(default=None)
    transition_start_time: float | None = field(default=None)
    transition_start_brightness: int | None = field(default=None)
    transition_target_brightness: int | None = field(default=None)
    last_applied_brightness: int | None = field(default=None)
    # 上次读取失败日志时间，单位为秒。
    last_read_failure_logged_at: float | None = field(default=None)
    # 上次写入失败日志时间，单位为秒。
    last_write_failure_logged_at: float | None = field(default=None)


@dataclass
class RuntimeControlState:
    """
    @brief 保存托盘模式下的运行时控制状态。
    @note 该状态用于跨线程协调启停自动调光、立即恢复与程序退出。
    """

    auto_dim_enabled_event: threading.Event = field(
        default_factory=threading.Event
    )
    stop_event: threading.Event = field(default_factory=threading.Event)
    wake_event: threading.Event = field(default_factory=threading.Event)
    restore_requested_event: threading.Event = field(
        default_factory=threading.Event
    )
    manual_brightness_queue: queue.SimpleQueue[tuple[int, int]] = field(
        default_factory=queue.SimpleQueue
    )


user32 = ctypes.WinDLL("user32", use_last_error=True)

try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None


WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.LPARAM,
)

user32.EnumWindows.argtypes = [
    WNDENUMPROC,
    wintypes.LPARAM,
]
user32.EnumWindows.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [
    wintypes.HWND,
]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsIconic.argtypes = [
    wintypes.HWND,
]
user32.IsIconic.restype = wintypes.BOOL

user32.GetShellWindow.argtypes = []
user32.GetShellWindow.restype = wintypes.HWND

user32.GetWindowLongW.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
]
user32.GetWindowLongW.restype = wintypes.LONG

user32.GetClassNameW.argtypes = [
    wintypes.HWND,
    wintypes.LPWSTR,
    ctypes.c_int,
]
user32.GetClassNameW.restype = ctypes.c_int

user32.GetWindowTextLengthW.argtypes = [
    wintypes.HWND,
]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [
    wintypes.HWND,
    wintypes.LPWSTR,
    ctypes.c_int,
]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetWindowRect.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(RECT),
]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetCursorPos.argtypes = [
    ctypes.POINTER(POINT),
]
user32.GetCursorPos.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(MONITORINFOEXW),
]
user32.GetMonitorInfoW.restype = wintypes.BOOL

if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmGetWindowAttribute.restype = HRESULT


def clone_rect(source_rect: RECT) -> RECT:
    """
    @brief 复制一个矩形结构体。
    @param source_rect 源矩形结构体。
    @return RECT 复制后的矩形结构体。
    """

    return RECT(
        source_rect.left,
        source_rect.top,
        source_rect.right,
        source_rect.bottom,
    )


def get_window_class_name(window_handle: int) -> str:
    """
    @brief 获取窗口类名。
    @param window_handle 目标窗口句柄。
    @return str 窗口类名，获取失败时返回空字符串。
    """

    buffer_length = 256
    buffer = ctypes.create_unicode_buffer(buffer_length)
    copied_length = user32.GetClassNameW(window_handle, buffer, buffer_length)

    if copied_length <= 0:
        return ""

    return buffer.value.strip()


def get_window_title(window_handle: int) -> str:
    """
    @brief 获取窗口标题。
    @param window_handle 目标窗口句柄。
    @return str 窗口标题文本，获取失败时返回空字符串。
    """

    title_length = user32.GetWindowTextLengthW(window_handle)

    if title_length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(title_length + 1)
    copied_length = user32.GetWindowTextW(
        window_handle,
        buffer,
        title_length + 1,
    )

    if copied_length <= 0:
        return ""

    return buffer.value.strip()


def get_window_rect(window_handle: int) -> RECT | None:
    """
    @brief 获取窗口矩形区域。
    @param window_handle 目标窗口句柄。
    @return RECT | None 获取成功时返回矩形结构体，否则返回 None。
    """

    rect = RECT()
    result = user32.GetWindowRect(window_handle, ctypes.byref(rect))

    if not result:
        return None

    return rect


def is_window_cloaked(window_handle: int) -> bool:
    """
    @brief 判断窗口是否被系统标记为隐藏代理窗口。
    @param window_handle 目标窗口句柄。
    @return bool 返回 True 表示窗口处于 cloaked 状态。
    @note 当系统不支持 DWM 查询时，该函数始终返回 False。
    """

    if dwmapi is None:
        return False

    cloaked_value = wintypes.DWORD()
    result = dwmapi.DwmGetWindowAttribute(
        window_handle,
        DWMWA_CLOAKED,
        ctypes.byref(cloaked_value),
        ctypes.sizeof(cloaked_value),
    )

    if result != 0:
        return False

    return bool(cloaked_value.value)


def is_rect_valid(target_rect: RECT | None) -> bool:
    """
    @brief 判断矩形区域是否有效。
    @param target_rect 待判断的矩形结构体。
    @return bool 返回 True 表示矩形具有有效宽高。
    """

    if target_rect is None:
        return False

    if target_rect.right <= target_rect.left:
        return False

    if target_rect.bottom <= target_rect.top:
        return False

    return True


def is_normal_window(window_handle: int) -> bool:
    """
    @brief 判断窗口是否属于可见普通窗口。
    @param window_handle 目标窗口句柄。
    @return bool 返回 True 表示该窗口满足普通窗口判定规则。
    """

    if not window_handle:
        return False

    if window_handle == user32.GetShellWindow():
        return False

    if not user32.IsWindowVisible(window_handle):
        return False

    if user32.IsIconic(window_handle):
        return False

    if is_window_cloaked(window_handle):
        return False

    style_value = user32.GetWindowLongW(window_handle, GWL_STYLE)
    exstyle_value = user32.GetWindowLongW(window_handle, GWL_EXSTYLE)
    class_name = get_window_class_name(window_handle)
    title_text = get_window_title(window_handle)
    window_rect = get_window_rect(window_handle)

    if style_value & WS_CHILD:
        return False

    if exstyle_value & WS_EX_NOACTIVATE:
        return False

    if exstyle_value & WS_EX_TOOLWINDOW and not exstyle_value & WS_EX_APPWINDOW:
        return False

    if class_name in {"Progman", "WorkerW", "Shell_TrayWnd"}:
        return False

    if not is_rect_valid(window_rect):
        return False

    if not title_text and not exstyle_value & WS_EX_APPWINDOW:
        return False

    return True


def enumerate_normal_windows() -> list[int]:
    """
    @brief 枚举当前桌面上的所有可见普通窗口。
    @return list[int] 窗口句柄列表。
    """

    window_handles: list[int] = []
    callback_error: Exception | None = None

    @WNDENUMPROC
    def callback(window_handle: int, application_data: int) -> bool:
        """
        @brief 处理 EnumWindows 返回的单个窗口句柄。
        @param window_handle 当前窗口句柄。
        @param application_data 调用方传入的附加参数。
        @return bool 返回 True 表示继续枚举。
        """

        del application_data

        nonlocal callback_error

        try:
            if is_normal_window(window_handle):
                window_handles.append(int(window_handle))
        except Exception as error:
            callback_error = error
            return False

        return True

    if not user32.EnumWindows(callback, 0):
        if callback_error is not None:
            raise callback_error

        error_code = ctypes.get_last_error()

        if error_code == 0:
            return []

        raise OSError(error_code, f"枚举窗口失败。Windows 错误码: {error_code}")

    return window_handles


def get_cursor_point() -> POINT | None:
    """
    @brief 获取鼠标当前所在的屏幕坐标。
    @return POINT | None 获取成功时返回坐标，否则返回 None。
    @note 当当前会话没有交互桌面访问权限时，返回 None。
    """

    point = POINT()

    if not user32.GetCursorPos(ctypes.byref(point)):
        error_code = ctypes.get_last_error()

        if error_code == 5:
            return None

        raise OSError(error_code, f"获取鼠标位置失败。Windows 错误码: {error_code}")

    return point


def get_monitor_info(monitor_handle: wintypes.HANDLE) -> MONITORINFOEXW:
    """
    @brief 获取单个逻辑显示器的扩展信息。
    @param monitor_handle 逻辑显示器句柄。
    @return MONITORINFOEXW 显示器扩展信息结构体。
    """

    monitor_info = MONITORINFOEXW()
    monitor_info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    result = user32.GetMonitorInfoW(
        monitor_handle,
        ctypes.byref(monitor_info),
    )

    if not result:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, f"获取显示器信息失败。Windows 错误码: {error_code}")

    return monitor_info


def get_target_monitor_info_map() -> dict[int, MonitorBrightnessInfo]:
    """
    @brief 获取以亮度索引为键的显示器亮度信息字典。
    @return dict[int, MonitorBrightnessInfo] 显示器亮度信息字典。
    """

    return {
        monitor_info.index: monitor_info
        for monitor_info in get_monitor_brightness_infos()
    }


def build_controlled_monitor_states(
    target_index: int | None,
    target_brightness: int | None,
) -> list[ControlledMonitorState]:
    """
    @brief 构建受控显示器状态列表。
    @param target_index 目标显示器索引，从 1 开始；传入 None 表示控制全部。
    @param target_brightness 初始恢复亮度；传入 None 表示读取显示器当前亮度。
    @return list[ControlledMonitorState] 受控显示器状态列表。
    """

    brightness_info_map = get_target_monitor_info_map()
    controlled_monitor_states: list[ControlledMonitorState] = []
    logical_monitor_handles = enumerate_display_monitors()
    current_index = 1
    target_index_found = False

    for logical_monitor_handle in logical_monitor_handles:
        monitor_info = get_monitor_info(logical_monitor_handle)
        physical_monitor_count, physical_monitor_array = open_physical_monitors(
            logical_monitor_handle
        )

        try:
            for _ in range(physical_monitor_count):
                brightness_info = brightness_info_map.get(current_index)

                if brightness_info is None:
                    raise RuntimeError(
                        f"未找到索引为 {current_index} 的亮度信息。"
                    )

                is_target_monitor = (
                    target_index is None or current_index == target_index
                )

                if target_index is not None and current_index != target_index:
                    current_index += 1
                    continue

                if is_target_monitor:
                    target_index_found = True

                if (
                    not brightness_info.supports_brightness
                    or brightness_info.current_percentage is None
                ):
                    log_and_print(
                        logger,
                        logging.INFO,
                        f"跳过显示器索引 {current_index}: "
                        "不支持当前可用的亮度控制后端。",
                    )
                    current_index += 1
                    continue

                current_brightness = int(brightness_info.current_percentage)
                restore_brightness = target_brightness

                if restore_brightness is None:
                    restore_brightness = current_brightness

                current_mode = None

                if current_brightness == restore_brightness:
                    current_mode = "restore"

                controlled_monitor_states.append(
                    ControlledMonitorState(
                        index=current_index,
                        description=brightness_info.description,
                        monitor_rect=clone_rect(monitor_info.rcMonitor),
                        device_name=str(monitor_info.szDevice).strip(),
                        is_primary=bool(
                            monitor_info.dwFlags & MONITORINFOF_PRIMARY
                        ),
                        restore_brightness=restore_brightness,
                        current_brightness=current_brightness,
                        current_mode=current_mode,
                        last_applied_brightness=current_brightness,
                    )
                )
                current_index += 1
        finally:
            close_physical_monitors(
                physical_monitor_count,
                physical_monitor_array,
            )

    if not controlled_monitor_states:
        if target_index is not None and not target_index_found:
            log_and_print(
                logger,
                logging.WARNING,
                f"未找到索引为 {target_index} 的显示器。",
            )
        else:
            log_and_print(
                logger,
                logging.WARNING,
                "未检测到支持亮度控制的显示器。",
            )

    return controlled_monitor_states


def get_panel_monitor_rows(
    target_index: int | None,
) -> list[tuple[int, str, int]]:
    """
    @brief 获取亮度面板当前可显示的显示器亮度行。
    @param target_index 目标显示器索引；传入 None 表示列出全部支持亮度控制的显示器。
    @return list[tuple[int, str, int]] 每行依次为显示器索引、描述文本、当前亮度百分比。
    """

    monitor_rows: list[tuple[int, str, int]] = []

    for monitor_info in get_monitor_brightness_infos():
        if target_index is not None and monitor_info.index != target_index:
            continue

        if (
            not monitor_info.supports_brightness
            or monitor_info.current_percentage is None
        ):
            continue

        monitor_rows.append(
            (
                monitor_info.index,
                monitor_info.description,
                int(monitor_info.current_percentage),
            )
        )

    return monitor_rows


def format_restore_brightness_summary(
    controlled_monitor_states: list[ControlledMonitorState],
) -> str:
    """
    @brief 格式化受控显示器当前记录的恢复亮度摘要。
    @param controlled_monitor_states 受控显示器状态列表。
    @return str 恢复亮度摘要文本。
    """

    summary_parts: list[str] = []

    for monitor_state in controlled_monitor_states:
        summary_parts.append(
            f"[{monitor_state.index}] {monitor_state.restore_brightness}%"
        )

    return "，".join(summary_parts)


def should_log_monitor_failure(
    last_logged_at: float | None,
    current_time: float,
) -> bool:
    """
    @brief 判断本次单屏失败是否需要输出日志。
    @param last_logged_at 上次输出日志的单调时钟时间，单位为秒。
    @param current_time 当前单调时钟时间，单位为秒。
    @return bool 返回 True 表示需要输出日志。
    """

    if last_logged_at is None:
        return True

    return (
        current_time - last_logged_at
        >= MONITOR_FAILURE_LOG_INTERVAL_SECONDS
    )


def get_controlled_brightness_snapshot(
    controlled_monitor_states: list[ControlledMonitorState],
) -> dict[int, int]:
    """
    @brief 读取当前受控显示器的实时亮度快照。
    @param controlled_monitor_states 受控显示器状态列表。
    @return dict[int, int] 以显示器索引为键、当前亮度为值的字典。
    """

    target_indexes = {
        monitor_state.index
        for monitor_state in controlled_monitor_states
    }
    monitor_state_map = {
        monitor_state.index: monitor_state
        for monitor_state in controlled_monitor_states
    }
    brightness_snapshot: dict[int, int] = {}
    current_time = time.monotonic()

    try:
        monitor_infos = get_monitor_brightness_infos()
    except Exception as error:
        log_and_print(
            logger,
            logging.WARNING,
            f"读取显示器亮度快照失败，本轮跳过同步: {error}",
        )
        return brightness_snapshot

    for monitor_info in monitor_infos:
        if monitor_info.index not in target_indexes:
            continue

        if (
            not monitor_info.supports_brightness
            or monitor_info.current_percentage is None
        ):
            monitor_state = monitor_state_map[monitor_info.index]

            if should_log_monitor_failure(
                monitor_state.last_read_failure_logged_at,
                current_time,
            ):
                log_and_print(
                    logger,
                    logging.WARNING,
                    f"显示器 [{monitor_info.index}] 当前无法读取亮度，"
                    "本轮保留上一次恢复亮度。",
                )
                monitor_state.last_read_failure_logged_at = current_time

            continue

        brightness_snapshot[monitor_info.index] = int(
            monitor_info.current_percentage
        )
        monitor_state_map[
            monitor_info.index
        ].last_read_failure_logged_at = None

    return brightness_snapshot


def get_transition_tick_interval(
    poll_interval: float,
) -> float:
    """
    @brief 获取用于驱动亮度渐变的内部刷新间隔。
    @param poll_interval 外部状态轮询间隔，单位为秒。
    @return float 亮度渐变内部刷新间隔，单位为秒。
    @note 该间隔通常小于窗口状态轮询间隔，以获得更平滑的亮度变化。
    """

    if poll_interval < DEFAULT_TRANSITION_TICK_SECONDS:
        return poll_interval

    return DEFAULT_TRANSITION_TICK_SECONDS


def create_runtime_control_state() -> RuntimeControlState:
    """
    @brief 创建并初始化托盘模式所需的运行时控制状态。
    @return RuntimeControlState 初始化后的运行时控制状态对象。
    """

    runtime_control_state = RuntimeControlState()
    runtime_control_state.auto_dim_enabled_event.set()
    return runtime_control_state


def is_auto_dim_enabled(
    runtime_control_state: RuntimeControlState,
) -> bool:
    """
    @brief 判断自动调光当前是否处于启用状态。
    @param runtime_control_state 运行时控制状态对象。
    @return bool 返回 True 表示自动调光已启用。
    """

    return runtime_control_state.auto_dim_enabled_event.is_set()


def set_auto_dim_enabled(
    runtime_control_state: RuntimeControlState,
    enabled: bool,
) -> None:
    """
    @brief 设置自动调光启用状态。
    @param runtime_control_state 运行时控制状态对象。
    @param enabled 是否启用自动调光。
    @return None
    """

    if enabled:
        runtime_control_state.auto_dim_enabled_event.set()
        logger.info("自动调光已启用。")
    else:
        runtime_control_state.auto_dim_enabled_event.clear()
        runtime_control_state.restore_requested_event.set()
        logger.info("自动调光已暂停，已请求恢复亮度。")

    runtime_control_state.wake_event.set()


def request_restore_now(
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 请求后台线程立即恢复所有受控显示器亮度。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    runtime_control_state.restore_requested_event.set()
    runtime_control_state.wake_event.set()
    logger.info("用户请求立即恢复亮度。")


def consume_restore_request(
    runtime_control_state: RuntimeControlState,
) -> bool:
    """
    @brief 读取并清除一次立即恢复请求。
    @param runtime_control_state 运行时控制状态对象。
    @return bool 返回 True 表示本轮存在立即恢复请求。
    """

    if not runtime_control_state.restore_requested_event.is_set():
        return False

    runtime_control_state.restore_requested_event.clear()
    return True


def request_stop(
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 请求后台线程停止运行。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    runtime_control_state.stop_event.set()
    runtime_control_state.wake_event.set()
    logger.info("请求后台线程停止运行。")


def wait_with_runtime_control(
    runtime_control_state: RuntimeControlState | None,
    timeout_seconds: float,
) -> None:
    """
    @brief 在支持运行时控制的情况下等待指定时间或等待唤醒信号。
    @param runtime_control_state 运行时控制状态对象；传入 None 表示普通睡眠。
    @param timeout_seconds 等待时长，单位为秒。
    @return None
    """

    if timeout_seconds <= 0:
        return

    if runtime_control_state is None:
        time.sleep(timeout_seconds)
        return

    runtime_control_state.wake_event.wait(timeout_seconds)
    runtime_control_state.wake_event.clear()


def quote_command_argument(argument: str) -> str:
    """
    @brief 为命令行参数添加双引号并转义内部双引号。
    @param argument 原始命令行参数文本。
    @return str 适合写入注册表启动项的参数文本。
    """

    escaped_argument = argument.replace('"', r'\"')
    return f'"{escaped_argument}"'


def split_windows_command_line(command: str) -> list[str]:
    """
    @brief 按 Windows 命令行规则拆分命令文本。
    @param command 注册表启动项中的完整命令行。
    @return list[str] 拆分后的参数列表。
    @note CommandLineToArgvW 失败时使用简单降级解析，避免自启动状态判断抛出异常。
    """

    argument_count = ctypes.c_int(0)

    try:
        command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
        command_line_to_argv.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_int),
        ]
        command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)

        argv_pointer = command_line_to_argv(
            command,
            ctypes.byref(argument_count),
        )
        if not argv_pointer:
            return []

        try:
            return [
                argv_pointer[index]
                for index in range(argument_count.value)
            ]
        finally:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [
                ctypes.c_void_p,
            ]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(argv_pointer, ctypes.c_void_p))
    except (AttributeError, OSError):
        stripped_command = command.strip()
        if not stripped_command:
            return []

        if stripped_command.startswith('"'):
            closing_quote_index = stripped_command.find('"', 1)
            if closing_quote_index > 0:
                return [
                    stripped_command[1:closing_quote_index],
                ]

        return [
            stripped_command.split(maxsplit=1)[0],
        ]


def normalize_autostart_path(path_text: str) -> str:
    """
    @brief 标准化自启动命令中的路径。
    @param path_text 命令行中解析出的路径文本。
    @return str 经过环境变量展开和绝对路径转换后的路径。
    """

    return os.path.normcase(
        os.path.abspath(
            os.path.expandvars(path_text),
        )
    )


def get_current_application_entry_path() -> str:
    """
    @brief 获取当前程序对应的自启动入口路径。
    @return str 打包版返回可执行文件路径，源码版返回当前脚本路径。
    """

    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)

    return os.path.abspath(__file__)


def build_autostart_command(arguments: argparse.Namespace) -> str:
    """
    @brief 构建写入注册表的自启动命令行。
    @param arguments 当前解析后的命令行参数对象。
    @return str 完整的自启动命令行文本。
    @note 源码版使用当前 Python 解释器启动脚本，打包版直接启动 Lumina.exe。
    """

    if getattr(sys, "frozen", False):
        command_parts = [
            quote_command_argument(get_current_application_entry_path()),
        ]
    else:
        command_parts = [
            quote_command_argument(os.path.abspath(sys.executable)),
            quote_command_argument(get_current_application_entry_path()),
        ]

    if arguments.target_brightness is not None:
        command_parts.append(str(arguments.target_brightness))

    command_parts.extend(
        [
            "--dim-brightness",
            str(arguments.dim_brightness),
            "--interval",
            str(arguments.interval),
            "--dim-delay",
            str(arguments.dim_delay),
            "--transition-duration",
            str(arguments.transition_duration),
        ]
    )

    if arguments.index is not None:
        command_parts.extend(
            [
                "--index",
                str(arguments.index),
            ]
        )

    if arguments.all:
        command_parts.append("--all")

    if arguments.debug:
        command_parts.append("--debug")

    return " ".join(command_parts)


def is_autostart_command_current(command: str) -> bool:
    """
    @brief 判断注册表启动命令是否指向当前 Lumina 程序。
    @param command 注册表中保存的启动命令。
    @return bool 启动命令可执行且指向当前程序时返回 True。
    """

    command_parts = split_windows_command_line(command)
    if not command_parts:
        return False

    executable_path = normalize_autostart_path(command_parts[0])
    if not os.path.isfile(executable_path):
        logger.warning("自启动命令入口不存在: %s", command_parts[0])
        return False

    current_entry_path = normalize_autostart_path(
        get_current_application_entry_path(),
    )

    if getattr(sys, "frozen", False):
        return executable_path == current_entry_path

    if executable_path == current_entry_path:
        return True

    if len(command_parts) < 2:
        logger.warning("源码版自启动命令缺少脚本路径。")
        return False

    script_path = normalize_autostart_path(command_parts[1])
    if not os.path.isfile(script_path):
        logger.warning("自启动脚本不存在: %s", command_parts[1])
        return False

    return script_path == current_entry_path


def is_autostart_enabled() -> bool:
    """
    @brief 判断当前用户是否已启用 Lumina 自启动。
    @return bool 返回 True 表示当前用户已启用自启动。
    """

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_SUBKEY,
            0,
            winreg.KEY_READ,
        ) as registry_key:
            command, _value_type = winreg.QueryValueEx(
                registry_key,
                AUTOSTART_VALUE_NAME,
            )
            return is_autostart_command_current(str(command))
    except FileNotFoundError:
        return False


def enable_autostart(arguments: argparse.Namespace) -> str:
    """
    @brief 为当前用户启用 Lumina 自启动。
    @param arguments 当前解析后的命令行参数对象。
    @return str 启用自启动后的说明文本。
    """

    autostart_command = build_autostart_command(arguments)

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        AUTOSTART_REGISTRY_SUBKEY,
    ) as registry_key:
        winreg.SetValueEx(
            registry_key,
            AUTOSTART_VALUE_NAME,
            0,
            winreg.REG_SZ,
            autostart_command,
        )

    message = "已为当前用户启用登录后自启动。"
    logger.info(message)
    return message


def disable_autostart() -> str:
    """
    @brief 为当前用户禁用 Lumina 自启动。
    @return str 禁用自启动后的说明文本。
    """

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_SUBKEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as registry_key:
            winreg.DeleteValue(
                registry_key,
                AUTOSTART_VALUE_NAME,
            )
    except FileNotFoundError:
        message = "当前用户尚未启用自启动。"
        logger.info(message)
        return message

    message = "已为当前用户关闭登录后自启动。"
    logger.info(message)
    return message


def has_active_transition(
    monitor_state: ControlledMonitorState,
) -> bool:
    """
    @brief 判断显示器当前是否存在进行中的亮度渐变。
    @param monitor_state 受控显示器状态。
    @return bool 返回 True 表示当前存在进行中的渐变。
    """

    if monitor_state.transition_target_mode is None:
        return False

    return True


def clear_transition_state(
    monitor_state: ControlledMonitorState,
) -> None:
    """
    @brief 清空显示器当前的渐变状态。
    @param monitor_state 受控显示器状态。
    @return None
    """

    monitor_state.transition_target_mode = None
    monitor_state.transition_start_time = None
    monitor_state.transition_start_brightness = None
    monitor_state.transition_target_brightness = None


def get_effective_mode(
    monitor_state: ControlledMonitorState,
) -> str | None:
    """
    @brief 获取显示器当前的目标模式。
    @param monitor_state 受控显示器状态。
    @return str | None 若存在渐变则返回渐变目标模式，否则返回稳定模式。
    """

    if has_active_transition(monitor_state):
        return monitor_state.transition_target_mode

    return monitor_state.current_mode


def apply_ease_in_out(
    transition_ratio: float,
) -> float:
    """
    @brief 对线性进度应用缓入缓出曲线。
    @param transition_ratio 0 到 1 范围内的线性进度。
    @return float 经过缓动处理后的进度值。
    """

    if transition_ratio <= 0:
        return 0.0

    if transition_ratio >= 1:
        return 1.0

    return 0.5 - 0.5 * math.cos(math.pi * transition_ratio)


def set_monitor_brightness_value(
    monitor_state: ControlledMonitorState,
    target_brightness: int,
) -> str | None:
    """
    @brief 设置单块受控显示器的亮度并同步本地状态。
    @param monitor_state 受控显示器状态。
    @param target_brightness 目标亮度百分比。
    @return str | None 成功时返回被设置显示器的名称文本；失败且日志被节流时返回 None。
    """

    try:
        monitor_name = set_brightness_by_index(
            monitor_state.index,
            target_brightness,
        )
    except Exception as error:
        current_time = time.monotonic()
        clear_transition_state(monitor_state)

        if not should_log_monitor_failure(
            monitor_state.last_write_failure_logged_at,
            current_time,
        ):
            return None

        monitor_state.last_write_failure_logged_at = current_time
        raise RuntimeError(
            f"设置显示器 [{monitor_state.index}] 亮度失败: {error}"
        ) from error

    monitor_state.current_brightness = target_brightness
    monitor_state.last_applied_brightness = target_brightness
    monitor_state.last_write_failure_logged_at = None
    return monitor_name


def apply_tray_manual_brightness_to_monitor(
    monitor_state: ControlledMonitorState,
    target_percentage: int,
) -> None:
    """
    @brief 将托盘亮度面板的设置立即应用到单块受控显示器并同步内部状态。
    @param monitor_state 受控显示器状态。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return None
    """

    if target_percentage < 0:
        target_percentage = 0

    if target_percentage > 100:
        target_percentage = 100

    clear_transition_state(monitor_state)
    try:
        monitor_name = set_monitor_brightness_value(
            monitor_state,
            target_percentage,
        )
    except Exception as error:
        log_and_print(
            logger,
            logging.WARNING,
            str(error),
        )
        return

    if monitor_name is None:
        return

    monitor_state.restore_brightness = target_percentage
    monitor_state.current_mode = "restore"
    monitor_state.dim_condition_started_at = None


def apply_tray_manual_brightness_by_index(
    monitor_index: int,
    target_percentage: int,
) -> None:
    """
    @brief 按显示器索引立即应用托盘亮度面板提交的亮度。
    @param monitor_index 显示器索引。
    @param target_percentage 目标亮度百分比，范围为 0 到 100。
    @return None
    @note 用于处理热插拔后不在初始受控列表中的显示器。
    """

    if target_percentage < 0:
        target_percentage = 0

    if target_percentage > 100:
        target_percentage = 100

    set_brightness_by_index(
        monitor_index,
        target_percentage,
    )


def drain_manual_brightness_adjustments(
    runtime_control_state: RuntimeControlState,
    controlled_monitor_states: list[ControlledMonitorState],
) -> None:
    """
    @brief 清空并应用托盘提交的亮度调节队列。
    @param runtime_control_state 运行时控制状态对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @return None
    @note 同一轮内同一显示器只应用最新亮度，避免拖动滑块时旧值排队导致亮度缓慢追赶。
    """

    latest_brightness_map: dict[int, int] = {}

    while True:
        try:
            monitor_index, brightness_percentage = (
                runtime_control_state.manual_brightness_queue.get_nowait()
            )
        except queue.Empty:
            break

        latest_brightness_map[monitor_index] = brightness_percentage

    if not latest_brightness_map:
        return

    for monitor_index, brightness_percentage in latest_brightness_map.items():
        is_applied_to_state = False

        for monitor_state in controlled_monitor_states:
            if monitor_state.index != monitor_index:
                continue

            apply_tray_manual_brightness_to_monitor(
                monitor_state,
                brightness_percentage,
            )
            is_applied_to_state = True
            break

        if is_applied_to_state:
            continue

        try:
            apply_tray_manual_brightness_by_index(
                monitor_index,
                brightness_percentage,
            )
        except Exception as error:
            log_and_print(
                logger,
                logging.WARNING,
                f"设置显示器 [{monitor_index}] 亮度失败: {error}",
            )


def synchronize_restore_brightness(
    controlled_monitor_states: list[ControlledMonitorState],
) -> list[str]:
    """
    @brief 根据当前实时亮度更新恢复亮度记录。
    @param controlled_monitor_states 受控显示器状态列表。
    @return list[str] 本轮发生恢复亮度更新时的说明文本列表。
    @note 该函数只应接收当前稳定处于恢复状态的显示器列表。
    """

    brightness_snapshot = get_controlled_brightness_snapshot(
        controlled_monitor_states
    )
    update_messages: list[str] = []

    for monitor_state in controlled_monitor_states:
        current_brightness = brightness_snapshot.get(monitor_state.index)

        if current_brightness is None:
            continue

        monitor_state.current_brightness = current_brightness
        monitor_state.last_applied_brightness = current_brightness

        if current_brightness == monitor_state.restore_brightness:
            continue

        previous_brightness = monitor_state.restore_brightness
        monitor_state.restore_brightness = current_brightness
        update_messages.append(
            "已更新恢复亮度: "
            f"[{monitor_state.index}] {monitor_state.description} "
            f"{previous_brightness}% -> {current_brightness}%"
        )
        logger.info(update_messages[-1])

    return update_messages


def rects_intersect(first_rect: RECT, second_rect: RECT) -> bool:
    """
    @brief 判断两个矩形区域是否相交。
    @param first_rect 第一个矩形区域。
    @param second_rect 第二个矩形区域。
    @return bool 返回 True 表示两个矩形存在非零面积交集。
    """

    intersection_left = max(first_rect.left, second_rect.left)
    intersection_top = max(first_rect.top, second_rect.top)
    intersection_right = min(first_rect.right, second_rect.right)
    intersection_bottom = min(first_rect.bottom, second_rect.bottom)

    if intersection_right <= intersection_left:
        return False

    if intersection_bottom <= intersection_top:
        return False

    return True


def calculate_intersection_area(
    first_rect: RECT,
    second_rect: RECT,
) -> int:
    """
    @brief 计算两个矩形区域的相交面积。
    @param first_rect 第一个矩形区域。
    @param second_rect 第二个矩形区域。
    @return int 两个矩形的相交面积；若不相交则返回 0。
    """

    intersection_left = max(first_rect.left, second_rect.left)
    intersection_top = max(first_rect.top, second_rect.top)
    intersection_right = min(first_rect.right, second_rect.right)
    intersection_bottom = min(first_rect.bottom, second_rect.bottom)

    if intersection_right <= intersection_left:
        return 0

    if intersection_bottom <= intersection_top:
        return 0

    return (
        (intersection_right - intersection_left)
        * (intersection_bottom - intersection_top)
    )


def is_point_in_rect(point: POINT | None, target_rect: RECT) -> bool:
    """
    @brief 判断坐标点是否位于矩形区域内部。
    @param point 屏幕坐标点；传入 None 表示没有可用鼠标位置。
    @param target_rect 目标矩形区域。
    @return bool 返回 True 表示坐标点位于该矩形内。
    """

    if point is None:
        return False

    if point.x < target_rect.left:
        return False

    if point.x >= target_rect.right:
        return False

    if point.y < target_rect.top:
        return False

    if point.y >= target_rect.bottom:
        return False

    return True


def evaluate_monitors(
    controlled_monitor_states: list[ControlledMonitorState],
    cursor_point: POINT | None,
    mouse_idle_seconds: float,
    dim_delay_seconds: float,
) -> list[MonitorEvaluationResult]:
    """
    @brief 按屏幕分别评估窗口与鼠标状态。
    @param controlled_monitor_states 受控显示器状态列表。
    @param cursor_point 当前鼠标屏幕坐标；与静止计时使用同一次采样结果。
    @param mouse_idle_seconds 全局鼠标已连续静止的秒数。
    @param dim_delay_seconds 触发调暗所需的连续等待秒数阈值。
    @return list[MonitorEvaluationResult] 每块受控屏幕的评估结果列表。
    """

    normal_window_handles = enumerate_normal_windows()
    evaluation_results: list[MonitorEvaluationResult] = []
    window_count_map = {
        monitor_state.index: 0
        for monitor_state in controlled_monitor_states
    }

    for window_handle in normal_window_handles:
        window_rect = get_window_rect(window_handle)

        if not is_rect_valid(window_rect):
            continue

        best_monitor_index: int | None = None
        best_intersection_area = 0

        for monitor_state in controlled_monitor_states:
            intersection_area = calculate_intersection_area(
                window_rect,
                monitor_state.monitor_rect,
            )

            if intersection_area <= 0:
                continue

            if intersection_area > best_intersection_area:
                best_intersection_area = intersection_area
                best_monitor_index = monitor_state.index

        if best_monitor_index is not None:
            window_count_map[best_monitor_index] += 1

    for monitor_state in controlled_monitor_states:
        intersecting_window_count = window_count_map[monitor_state.index]
        has_mouse = is_point_in_rect(
            cursor_point,
            monitor_state.monitor_rect,
        )
        should_dim = False
        bypass_stabilization_delay = False

        if intersecting_window_count == 0 and not has_mouse:
            should_dim = True
        elif (
            intersecting_window_count == 0
            and has_mouse
            and mouse_idle_seconds >= dim_delay_seconds
        ):
            should_dim = True
            bypass_stabilization_delay = True

        evaluation_results.append(
            MonitorEvaluationResult(
                index=monitor_state.index,
                window_count=intersecting_window_count,
                has_mouse=has_mouse,
                should_dim=should_dim,
                bypass_stabilization_delay=bypass_stabilization_delay,
            )
        )

    return evaluation_results


def format_mouse_presence(has_mouse: bool) -> str:
    """
    @brief 将鼠标是否在本屏的布尔值格式化为中文文本。
    @param has_mouse 鼠标是否在本屏。
    @return str 中文格式化结果。
    """

    if has_mouse:
        return "是"

    return "否"


def format_optional_seconds(value: float | None) -> str:
    """
    @brief 将可选秒数格式化为调试输出文本。
    @param value 待格式化的秒数；传入 None 表示当前无有效秒数。
    @return str 格式化后的文本。
    """

    if value is None:
        return "-"

    if value < 0:
        value = 0

    return f"{value:.2f}s"


def format_optional_text(value: str | None) -> str:
    """
    @brief 将可选文本格式化为调试输出文本。
    @param value 待格式化的文本；传入 None 表示当前无有效文本。
    @return str 格式化后的文本。
    """

    if value is None:
        return "-"

    return value


def format_optional_brightness(value: int | None) -> str:
    """
    @brief 将可选亮度值格式化为调试输出文本。
    @param value 待格式化的亮度百分比；传入 None 表示当前无有效亮度值。
    @return str 格式化后的文本。
    """

    if value is None:
        return "-"

    return f"{value}%"


def print_monitor_debug_result(
    evaluation_result: MonitorEvaluationResult,
    monitor_state: ControlledMonitorState,
    desired_mode: str | None,
    current_time: float,
    mouse_idle_seconds: float,
) -> None:
    """
    @brief 输出单块屏幕当前循环中的调试状态。
    @param evaluation_result 单块屏幕的评估结果。
    @param monitor_state 单块屏幕的受控状态。
    @param desired_mode 当前循环计算出的目标模式。
    @param current_time 当前单调时钟时间。
    @param mouse_idle_seconds 全局鼠标已连续静止的秒数。
    @return None
    """

    dim_elapsed_seconds: float | None = None

    if monitor_state.dim_condition_started_at is not None:
        dim_elapsed_seconds = (
            current_time - monitor_state.dim_condition_started_at
        )

    log_and_print(
        logger,
        logging.DEBUG,
        f"[DEBUG][{monitor_state.index}] "
        f"window_count={evaluation_result.window_count} | "
        f"has_mouse={evaluation_result.has_mouse} | "
        f"should_dim={evaluation_result.should_dim} | "
        f"bypass_stabilization_delay="
        f"{evaluation_result.bypass_stabilization_delay} | "
        f"mouse_idle={format_optional_seconds(mouse_idle_seconds)} | "
        f"desired_mode={format_optional_text(desired_mode)} | "
        f"effective_mode={format_optional_text(get_effective_mode(monitor_state))} | "
        f"stable_mode={format_optional_text(monitor_state.current_mode)} | "
        f"dim_elapsed={format_optional_seconds(dim_elapsed_seconds)} | "
        f"transition_active={has_active_transition(monitor_state)} | "
        f"transition_target_mode="
        f"{format_optional_text(monitor_state.transition_target_mode)} | "
        f"current_brightness="
        f"{format_optional_brightness(monitor_state.current_brightness)} | "
        f"restore_brightness="
        f"{format_optional_brightness(monitor_state.restore_brightness)} | "
        f"transition_target_brightness="
        f"{format_optional_brightness(monitor_state.transition_target_brightness)}",
    )


def print_monitor_evaluation_result(
    evaluation_result: MonitorEvaluationResult,
    monitor_state: ControlledMonitorState,
    dim_brightness: int,
) -> None:
    """
    @brief 输出单块屏幕当前的判定结果。
    @param evaluation_result 单块屏幕的评估结果。
    @param monitor_state 单块屏幕的受控状态。
    @param dim_brightness 变暗状态使用的亮度百分比。
    @return None
    """

    action_text = f"恢复到 {monitor_state.restore_brightness}%"

    if evaluation_result.should_dim:
        action_text = f"变暗到 {dim_brightness}%"

    log_and_print(
        logger,
        logging.INFO,
        f"[{monitor_state.index}] 窗口数: {evaluation_result.window_count} | "
        f"鼠标在本屏: {format_mouse_presence(evaluation_result.has_mouse)} | "
        f"当前判定: {action_text}",
    )


def print_monitor_waiting_result(
    evaluation_result: MonitorEvaluationResult,
    monitor_state: ControlledMonitorState,
    dim_brightness: int,
    elapsed_seconds: float,
    delay_seconds: float,
) -> None:
    """
    @brief 输出单块屏幕处于调暗倒计时中的状态。
    @param evaluation_result 单块屏幕的评估结果。
    @param monitor_state 单块屏幕的受控状态。
    @param dim_brightness 变暗状态使用的亮度百分比。
    @param elapsed_seconds 已连续满足调暗条件的时间。
    @param delay_seconds 触发调暗所需的连续时间。
    @return None
    """

    remaining_seconds = delay_seconds - elapsed_seconds

    if remaining_seconds < 0:
        remaining_seconds = 0

    log_and_print(
        logger,
        logging.INFO,
        f"[{monitor_state.index}] 窗口数: {evaluation_result.window_count} | "
        f"鼠标在本屏: {format_mouse_presence(evaluation_result.has_mouse)} | "
        f"当前判定: 保持 {monitor_state.current_brightness}% | "
        f"{remaining_seconds:.1f} 秒后渐变到 {dim_brightness}%",
    )


def start_monitor_transition(
    monitor_state: ControlledMonitorState,
    target_mode: str,
    target_brightness: int,
    transition_duration: float,
) -> str:
    """
    @brief 为单块屏幕启动亮度渐变。
    @param monitor_state 单块屏幕的受控状态。
    @param target_mode 目标模式，仅支持 restore 或 dim。
    @param target_brightness 目标亮度百分比。
    @param transition_duration 渐变持续时间，单位为秒。
    @return str 本次渐变启动的说明文本。
    """

    current_brightness = monitor_state.current_brightness

    if current_brightness == target_brightness:
        monitor_state.current_mode = target_mode
        clear_transition_state(monitor_state)

        if target_mode == "restore":
            return (
                f"显示器 [{monitor_state.index}] {monitor_state.description} "
                f"已处于恢复亮度 {target_brightness}%"
            )

        return (
            f"显示器 [{monitor_state.index}] {monitor_state.description} "
            f"已处于调暗亮度 {target_brightness}%"
        )

    monitor_state.transition_target_mode = target_mode
    monitor_state.transition_start_time = time.monotonic()
    monitor_state.transition_start_brightness = current_brightness
    monitor_state.transition_target_brightness = target_brightness

    if target_mode == "restore":
        return (
            f"开始在 {transition_duration:.1f} 秒内恢复显示器 "
            f"[{monitor_state.index}] {monitor_state.description} 到 "
            f"{target_brightness}%"
        )

    return (
        f"开始在 {transition_duration:.1f} 秒内调暗显示器 "
        f"[{monitor_state.index}] {monitor_state.description} 到 "
        f"{target_brightness}%"
    )


def advance_monitor_transition(
    monitor_state: ControlledMonitorState,
    current_time: float,
    transition_duration: float,
) -> None:
    """
    @brief 推进单块屏幕当前的亮度渐变。
    @param monitor_state 单块屏幕的受控状态。
    @param current_time 当前单调时钟时间。
    @param transition_duration 渐变持续时间，单位为秒。
    @return None
    """

    if not has_active_transition(monitor_state):
        return

    start_time = monitor_state.transition_start_time
    start_brightness = monitor_state.transition_start_brightness
    target_brightness = monitor_state.transition_target_brightness
    target_mode = monitor_state.transition_target_mode

    if (
        start_time is None
        or start_brightness is None
        or target_brightness is None
        or target_mode is None
    ):
        raise RuntimeError("检测到不完整的渐变状态。")

    if transition_duration <= 0:
        transition_ratio = 1.0
    else:
        transition_ratio = (current_time - start_time) / transition_duration

    if transition_ratio < 0:
        transition_ratio = 0

    if transition_ratio > 1:
        transition_ratio = 1

    eased_transition_ratio = apply_ease_in_out(transition_ratio)
    interpolated_brightness = round(
        start_brightness
        + (target_brightness - start_brightness) * eased_transition_ratio
    )

    if monitor_state.last_applied_brightness != interpolated_brightness:
        try:
            monitor_name = set_monitor_brightness_value(
                monitor_state,
                interpolated_brightness,
            )
        except Exception as error:
            log_and_print(
                logger,
                logging.WARNING,
                str(error),
            )
            return

        if monitor_name is None:
            return

    if transition_ratio >= 1:
        monitor_state.current_mode = target_mode
        monitor_state.current_brightness = target_brightness
        monitor_state.last_applied_brightness = target_brightness
        clear_transition_state(monitor_state)


def advance_all_transitions(
    controlled_monitor_states: list[ControlledMonitorState],
    transition_duration: float,
) -> None:
    """
    @brief 推进所有受控屏幕当前的亮度渐变。
    @param controlled_monitor_states 受控显示器状态列表。
    @param transition_duration 渐变持续时间，单位为秒。
    @return None
    """

    current_time = time.monotonic()

    for monitor_state in controlled_monitor_states:
        advance_monitor_transition(
            monitor_state,
            current_time,
            transition_duration,
        )


def restore_all_monitors_on_exit(
    controlled_monitor_states: list[ControlledMonitorState],
    transition_duration: float,
    poll_interval: float,
    runtime_control_state: RuntimeControlState | None = None,
) -> None:
    """
    @brief 在脚本退出前将所有已调暗的屏幕渐变恢复到记录的亮度。
    @param controlled_monitor_states 受控显示器状态列表。
    @param transition_duration 恢复渐变持续时间，单位为秒。
    @param poll_interval 驱动渐变的轮询间隔，单位为秒。
    @param runtime_control_state 运行时控制状态对象；传入 None 表示普通阻塞等待。
    @return None
    """

    restore_required_monitors: list[ControlledMonitorState] = []

    for monitor_state in controlled_monitor_states:
        effective_mode = get_effective_mode(monitor_state)

        if effective_mode == "restore" and not has_active_transition(monitor_state):
            continue

        restore_required_monitors.append(monitor_state)
        message = start_monitor_transition(
            monitor_state,
            "restore",
            monitor_state.restore_brightness,
            transition_duration,
        )
        log_and_print(
            logger,
            logging.INFO,
            f"退出前恢复亮度: {message}",
        )

    if not restore_required_monitors:
        return

    transition_tick_interval = get_transition_tick_interval(poll_interval)

    while True:
        transition_exists = False
        advance_all_transitions(
            restore_required_monitors,
            transition_duration,
        )

        for monitor_state in restore_required_monitors:
            if has_active_transition(monitor_state):
                transition_exists = True
                break

        if not transition_exists:
            return

        wait_with_runtime_control(
            runtime_control_state,
            transition_tick_interval,
        )


def build_tray_icon_pil(icon_size: int = 64) -> object:
    """
    @brief 从应用图标资源创建托盘及可执行文件图标位图。
    @param icon_size 图标位图边长，单位为像素。
    @return object Pillow Image 对象（RGBA 模式）。
    @note 该函数依赖 Pillow；图标资源来自 assets/Lumina.png。
    """

    if Image is None:
        raise RuntimeError("托盘模式需要 Pillow 支持。")

    icon_source_path = get_application_resource_path(APPLICATION_ICON_RELATIVE_PATH)
    source_image = Image.open(icon_source_path).convert("RGBA")
    resampling_filter = get_pillow_lanczos_filter()
    icon_canvas = Image.new(
        "RGBA",
        (
            icon_size,
            icon_size,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )
    source_width, source_height = source_image.size
    scale_factor = min(
        icon_size / source_width,
        icon_size / source_height,
    )
    target_width = max(
        1,
        round(source_width * scale_factor),
    )
    target_height = max(
        1,
        round(source_height * scale_factor),
    )
    resized_image = source_image.resize(
        (
            target_width,
            target_height,
        ),
        resampling_filter,
    )
    offset_x = (icon_size - target_width) // 2
    offset_y = (icon_size - target_height) // 2
    icon_canvas.alpha_composite(
        resized_image,
        (
            offset_x,
            offset_y,
        ),
    )

    return icon_canvas


def get_application_resource_path(relative_path: str) -> str:
    """
    @brief 获取应用资源文件在源码环境或 PyInstaller 环境中的实际路径。
    @param relative_path 相对应用根目录的资源路径。
    @return str 资源文件的绝对路径。
    @note PyInstaller 打包后资源位于 sys._MEIPASS 指向的内部目录。
    """

    if hasattr(sys, "_MEIPASS"):
        base_directory = getattr(sys, "_MEIPASS")
    else:
        base_directory = APPLICATION_DIRECTORY

    return os.path.join(
        base_directory,
        relative_path,
    )


def get_pillow_lanczos_filter() -> object:
    """
    @brief 获取当前 Pillow 版本可用的 Lanczos 重采样滤镜。
    @return object Pillow 重采样滤镜常量。
    @note 兼容 Pillow 新旧版本的常量位置差异。
    """

    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS

    return Image.LANCZOS


def create_tray_icon_image() -> object:
    """
    @brief 创建系统托盘图标所需的位图对象。
    @return object 托盘图标位图对象。
    @note 该函数依赖 Pillow，可在打包后随程序一同分发。
    """

    return build_tray_icon_pil()


def write_tray_icon_to_ico(output_file_path: str) -> None:
    """
    @brief 将应用图标写入 Windows 可用的多尺寸 ICO 文件。
    @param output_file_path 目标 .ico 文件的完整路径。
    @return None
    """

    if Image is None:
        raise RuntimeError("生成 ICO 需要 Pillow 支持。")

    base_image = build_tray_icon_pil(256).convert("RGBA")
    output_directory = os.path.dirname(os.path.abspath(output_file_path))

    if output_directory and not os.path.isdir(output_directory):
        os.makedirs(output_directory, exist_ok=True)

    base_image.save(
        output_file_path,
        format="ICO",
        sizes=[
            (256, 256),
            (128, 128),
            (64, 64),
            (48, 48),
            (32, 32),
            (16, 16),
        ],
    )


def update_tray_icon_title(
    tray_icon: object,
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 根据当前启停状态更新托盘图标标题。
    @param tray_icon 托盘图标对象。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    if is_auto_dim_enabled(runtime_control_state):
        tray_icon.title = f"{APPLICATION_NAME}：自动调光已启用"
    else:
        tray_icon.title = f"{APPLICATION_NAME}：自动调光已暂停"


def get_tray_auto_dim_checked(
    item: object,
    runtime_control_state: RuntimeControlState,
) -> bool:
    """
    @brief 获取托盘菜单中自动调光项的勾选状态。
    @param item 托盘菜单项对象。
    @param runtime_control_state 运行时控制状态对象。
    @return bool 返回 True 表示菜单项应显示为勾选。
    """

    del item
    return is_auto_dim_enabled(runtime_control_state)


def on_toggle_auto_dim_clicked(
    tray_icon: object,
    item: object,
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 处理托盘菜单中自动调光开关项的点击事件。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    del item
    next_enabled_state = not is_auto_dim_enabled(runtime_control_state)
    set_auto_dim_enabled(
        runtime_control_state,
        next_enabled_state,
    )
    update_tray_icon_title(
        tray_icon,
        runtime_control_state,
    )
    tray_icon.update_menu()


def on_brightness_panel_clicked(
    tray_icon: object,
    item: object,
    runtime_control_state: RuntimeControlState,
    controlled_monitor_states: list[ControlledMonitorState],
    panel_controller: object,
    lumina_worker: LuminaOrientationWorker,
    arguments: argparse.Namespace,
) -> None:
    """
    @brief 处理托盘默认项（左键）打开亮度调节面板。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @param runtime_control_state 运行时控制状态对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @param panel_controller 亮度面板控制器。
    @param lumina_worker Lumina 方向监听 worker。
    @param arguments 当前解析后的命令行参数对象。
    @return None
    """

    del item
    monitor_rows = get_panel_monitor_rows(arguments.index)

    if not monitor_rows:
        monitor_rows = [
            (
                monitor_state.index,
                monitor_state.description,
                monitor_state.current_brightness,
            )
            for monitor_state in controlled_monitor_states
        ]

    def get_latest_monitor_rows() -> list[tuple[int, str, int]]:
        """
        @brief 获取亮度面板刷新使用的最新显示器亮度行。
        @return list[tuple[int, str, int]] 每行依次为显示器索引、描述文本、当前亮度百分比。
        """

        return get_panel_monitor_rows(arguments.index)

    def enqueue_brightness_change(
        monitor_index: int,
        brightness_percentage: int,
    ) -> None:
        """
        @brief 将面板上的亮度变更写入队列并唤醒工作线程。
        @param monitor_index 显示器索引。
        @param brightness_percentage 目标亮度百分比。
        @return None
        """

        runtime_control_state.manual_brightness_queue.put(
            (monitor_index, brightness_percentage)
        )
        runtime_control_state.wake_event.set()
        logger.info(
            "托盘面板请求设置显示器 [%s] 亮度为 %s%%。",
            monitor_index,
            brightness_percentage,
        )

    def get_panel_auto_dim_enabled() -> bool:
        """
        @brief 获取亮度面板底部自动调光图案按钮的当前状态。
        @return bool 返回 True 表示自动调光已启用。
        """

        return is_auto_dim_enabled(runtime_control_state)

    def toggle_panel_auto_dim() -> bool:
        """
        @brief 切换自动调光状态并同步托盘菜单与标题。
        @return bool 返回切换后的自动调光启用状态。
        """

        next_enabled_state = not is_auto_dim_enabled(runtime_control_state)
        set_auto_dim_enabled(
            runtime_control_state,
            next_enabled_state,
        )
        update_tray_icon_title(
            tray_icon,
            runtime_control_state,
        )
        tray_icon.update_menu()
        return next_enabled_state

    def get_panel_idle_delay_seconds() -> float:
        """
        @brief 获取亮度面板中的自动暗屏空闲阈值秒数。
        @return float 返回当前空闲阈值秒数。
        """

        return float(arguments.dim_delay)

    def update_panel_idle_delay_seconds(delay_seconds: float) -> None:
        """
        @brief 更新亮度面板中的自动暗屏空闲阈值秒数。
        @param delay_seconds 新的空闲阈值秒数。
        @return None
        """

        if delay_seconds < 0:
            delay_seconds = 0.0

        arguments.dim_delay = delay_seconds
        runtime_control_state.wake_event.set()
        logger.info("自动暗屏空闲阈值已更新为 %.2f 秒。", delay_seconds)

    def get_panel_autostart_enabled() -> bool:
        """
        @brief 获取亮度面板底部自启动图案按钮的当前状态。
        @return bool 返回 True 表示自启动已启用。
        """

        return is_autostart_enabled()

    def toggle_panel_autostart() -> bool:
        """
        @brief 切换自启动状态并同步托盘菜单。
        @return bool 返回切换后的自启动启用状态。
        """

        if is_autostart_enabled():
            log_and_print(
                logger,
                logging.INFO,
                disable_autostart(),
            )
            tray_icon.update_menu()
            return False

        log_and_print(
            logger,
            logging.INFO,
            enable_autostart(arguments),
        )
        tray_icon.update_menu()
        return True

    def update_lumina_device_config(
        device_key: str,
        display_index: int,
        home_orientation: str,
        enabled: bool,
        brightness_mode: str,
        brightness_levels: list[dict[str, float | int | None]],
    ) -> None:
        """
        @brief 更新指定 Lumina 自动旋转与亮度配置。
        @param device_key Lumina 设备 key。
        @param display_index 绑定的显示器索引。
        @param home_orientation 屏幕正放时 Lumina 的朝向。
        @param enabled 是否启用自动旋转。
        @param brightness_mode 亮度调节模式。
        @param brightness_levels 自动亮度档位配置。
        @return None
        """

        lumina_worker.update_device_config(
            device_key,
            display_index,
            home_orientation,
            enabled,
            brightness_mode,
            brightness_levels,
        )
        logger.info(
            "Lumina [%s] 配置已更新: display_index=%s, home_orientation=%s, "
            "enabled=%s, brightness_mode=%s。",
            device_key,
            display_index,
            home_orientation,
            enabled,
            brightness_mode,
        )

    def update_monitor_lumina_binding(
        monitor_index: int,
        device_key: str | None,
    ) -> None:
        """
        @brief 更新显示器与 Lumina 自动亮度绑定关系。
        @param monitor_index 显示器索引。
        @param device_key Lumina 设备 key；传入 None 表示手动模式。
        @return None
        """

        lumina_worker.update_brightness_binding(
            monitor_index,
            device_key,
        )
        logger.info(
            "显示器 [%s] 自动亮度绑定已更新为 %s。",
            monitor_index,
            device_key or "手动",
        )

    panel_controller.show_multi_lumina_brightness_panel(
        monitor_rows,
        get_latest_monitor_rows,
        enqueue_brightness_change,
        get_panel_auto_dim_enabled,
        toggle_panel_auto_dim,
        get_panel_idle_delay_seconds,
        update_panel_idle_delay_seconds,
        get_panel_autostart_enabled,
        toggle_panel_autostart,
        lumina_worker.get_device_snapshots(),
        lumina_worker.get_device_snapshots,
        get_display_choices(),
        update_lumina_device_config,
        update_monitor_lumina_binding,
    )


def on_restore_now_clicked(
    tray_icon: object,
    item: object,
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 处理托盘菜单中立即恢复亮度项的点击事件。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    del tray_icon
    del item
    request_restore_now(runtime_control_state)


def on_exit_clicked(
    tray_icon: object,
    item: object,
    runtime_control_state: RuntimeControlState,
) -> None:
    """
    @brief 处理托盘菜单中退出项的点击事件。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @param runtime_control_state 运行时控制状态对象。
    @return None
    """

    del item
    request_stop(runtime_control_state)
    tray_icon.stop()


def get_tray_autostart_checked(item: object) -> bool:
    """
    @brief 获取托盘菜单中自启动项的勾选状态。
    @param item 托盘菜单项对象。
    @return bool 返回 True 表示当前用户已启用自启动。
    """

    del item
    return is_autostart_enabled()


def on_enable_autostart_clicked(
    tray_icon: object,
    item: object,
    arguments: argparse.Namespace,
) -> None:
    """
    @brief 处理托盘菜单中开启自启动项的点击事件。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @param arguments 当前解析后的命令行参数对象。
    @return None
    """

    del item
    message = enable_autostart(arguments)
    log_and_print(
        logger,
        logging.INFO,
        message,
    )
    tray_icon.update_menu()


def on_disable_autostart_clicked(
    tray_icon: object,
    item: object,
) -> None:
    """
    @brief 处理托盘菜单中关闭自启动项的点击事件。
    @param tray_icon 托盘图标对象。
    @param item 托盘菜单项对象。
    @return None
    """

    del item
    message = disable_autostart()
    log_and_print(
        logger,
        logging.INFO,
        message,
    )
    tray_icon.update_menu()


def create_tray_menu(
    runtime_control_state: RuntimeControlState,
    arguments: argparse.Namespace,
    controlled_monitor_states: list[ControlledMonitorState],
    panel_controller: object,
    lumina_worker: LuminaOrientationWorker,
) -> object:
    """
    @brief 创建系统托盘右键菜单。
    @param runtime_control_state 运行时控制状态对象。
    @param arguments 当前解析后的命令行参数对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @param panel_controller 亮度面板控制器。
    @param lumina_worker Lumina 方向监听 worker。
    @return object 托盘菜单对象。
    """

    if pystray is None:
        raise RuntimeError("托盘模式需要 pystray 支持。")

    return pystray.Menu(
        pystray.MenuItem(
            "亮度调节",
            functools.partial(
                on_brightness_panel_clicked,
                runtime_control_state=runtime_control_state,
                controlled_monitor_states=controlled_monitor_states,
                panel_controller=panel_controller,
                lumina_worker=lumina_worker,
                arguments=arguments,
            ),
            default=True,
        ),
        pystray.MenuItem(
            "启用自动调光",
            functools.partial(
                on_toggle_auto_dim_clicked,
                runtime_control_state=runtime_control_state,
            ),
            checked=functools.partial(
                get_tray_auto_dim_checked,
                runtime_control_state=runtime_control_state,
            ),
        ),
        pystray.MenuItem(
            "立即恢复亮度",
            functools.partial(
                on_restore_now_clicked,
                runtime_control_state=runtime_control_state,
            ),
        ),
        pystray.MenuItem(
            "开启自启动",
            functools.partial(
                on_enable_autostart_clicked,
                arguments=arguments,
            ),
            checked=get_tray_autostart_checked,
        ),
        pystray.MenuItem(
            "关闭自启动",
            on_disable_autostart_clicked,
        ),
        pystray.MenuItem(
            "退出",
            functools.partial(
                on_exit_clicked,
                runtime_control_state=runtime_control_state,
            ),
        ),
    )


def run_tray_icon_loop(
    arguments: argparse.Namespace,
    runtime_control_state: RuntimeControlState,
    controlled_monitor_states: list[ControlledMonitorState],
    panel_controller: object,
    lumina_worker: LuminaOrientationWorker,
) -> None:
    """
    @brief 启动并运行系统托盘图标主循环。
    @param arguments 当前解析后的命令行参数对象。
    @param runtime_control_state 运行时控制状态对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @param panel_controller 亮度面板控制器。
    @param lumina_worker Lumina 方向监听 worker。
    @return None
    """

    if pystray is None:
        raise RuntimeError("托盘模式需要先安装 pystray。")

    tray_icon = pystray.Icon(
        APPLICATION_NAME,
        create_tray_icon_image(),
        f"{APPLICATION_NAME}：自动调光已启用",
        create_tray_menu(
            runtime_control_state,
            arguments,
            controlled_monitor_states,
            panel_controller,
            lumina_worker,
        ),
    )
    update_tray_icon_title(
        tray_icon,
        runtime_control_state,
    )
    logger.info("系统托盘主循环启动。")
    tray_icon.run()


def monitor_worker_entry(
    arguments: argparse.Namespace,
    controlled_monitor_states: list[ControlledMonitorState],
    runtime_control_state: RuntimeControlState,
    lumina_worker: LuminaOrientationWorker,
) -> None:
    """
    @brief 后台监控线程入口函数。
    @param arguments 解析后的命令行参数对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @param runtime_control_state 运行时控制状态对象。
    @param lumina_worker Lumina 方向与亮度 worker。
    @return None
    """

    try:
        monitor_and_adjust_brightness(
            arguments,
            controlled_monitor_states,
            runtime_control_state,
            lumina_worker,
        )
    except Exception as error:
        log_and_print(
            logger,
            logging.ERROR,
            f"后台监控线程异常退出: {error}",
        )
        request_stop(runtime_control_state)


def run_with_system_tray(
    arguments: argparse.Namespace,
    controlled_monitor_states: list[ControlledMonitorState],
) -> int:
    """
    @brief 以系统托盘模式启动自动调光程序。
    @param arguments 解析后的命令行参数对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @return int 返回进程退出码，0 表示成功。
    """

    if pystray is None or Image is None:
        raise RuntimeError(
            "托盘模式依赖 pystray 与 Pillow，请先安装这两个库。"
        )

    try:
        from brightness_tray_panel import BrightnessTrayPanelController as TrayPanel
    except ImportError as import_error:
        raise RuntimeError(
            "托盘模式需要亮度面板模块 brightness_tray_panel 与 tkinter，请检查程序文件"
            "及 Python 安装是否完整。"
        ) from import_error

    runtime_control_state = create_runtime_control_state()
    panel_controller = TrayPanel()
    lumina_worker = LuminaOrientationWorker()
    panel_controller.start()
    lumina_worker.start()
    logger.info("托盘模式启动，Lumina worker 与亮度面板线程已启动。")
    worker_thread = threading.Thread(
        target=monitor_worker_entry,
        args=(
            arguments,
            controlled_monitor_states,
            runtime_control_state,
            lumina_worker,
        ),
        daemon=True,
        name=f"{APPLICATION_NAME}Worker",
    )
    worker_thread.start()

    try:
        run_tray_icon_loop(
            arguments,
            runtime_control_state,
            controlled_monitor_states,
            panel_controller,
            lumina_worker,
        )
    finally:
        request_stop(runtime_control_state)
        lumina_worker.stop()
        worker_thread.join(timeout=10.0)

    return 0


def parse_arguments() -> argparse.Namespace:
    """
    @brief 解析命令行参数。
    @return argparse.Namespace 解析后的命令行参数对象。
    """

    parser = argparse.ArgumentParser(
        description="根据每块屏幕上的窗口状态与鼠标位置自动调节显示器亮度。",
    )
    parser.add_argument(
        "target_brightness",
        type=int,
        nargs="?",
        default=None,
        help=(
            "可选：指定初始恢复亮度百分比；不传时启动后读取当前亮度"
            "作为各显示器的初始恢复值。"
        ),
    )
    parser.add_argument(
        "--dim-brightness",
        type=int,
        default=0,
        help="需要变暗时设置的亮度百分比，默认值为 0。",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="仅控制指定索引的显示器；默认控制全部支持 DDC/CI 的显示器。",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="显式指定控制全部支持 DDC/CI 的显示器；默认行为也是全部控制。",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help=(
            "轮询间隔，单位为秒，默认值为 "
            f"{DEFAULT_POLL_INTERVAL_SECONDS}。"
        ),
    )
    parser.add_argument(
        "--dim-delay",
        type=float,
        default=DEFAULT_DIM_DELAY_SECONDS,
        help=(
            "单块屏幕连续满足调暗条件后开始调暗的延迟时间，"
            "无窗且鼠标不在该屏时从条件满足起计时；"
            "无窗但鼠标在该屏时从全局鼠标静止起计时至该阈值后直接调暗；"
            f"默认值为 {DEFAULT_DIM_DELAY_SECONDS} 秒。"
        ),
    )
    parser.add_argument(
        "--transition-duration",
        type=float,
        default=DEFAULT_TRANSITION_DURATION_SECONDS,
        help=(
            "变亮与变暗的渐变持续时间，单位为秒，默认值为 "
            f"{DEFAULT_TRANSITION_DURATION_SECONDS} 秒。"
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="仅执行一次状态判断与亮度切换，不进入持续监控。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出当前判定结果，不真正修改亮度。",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出每轮每块屏幕的详细判定状态，便于排查调暗逻辑。",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="禁用系统托盘模式，使用当前命令行会话直接运行。",
    )
    add_logging_arguments(parser)
    return parser.parse_args()


def validate_arguments(arguments: argparse.Namespace) -> None:
    """
    @brief 校验命令行参数是否合法。
    @param arguments 解析后的命令行参数对象。
    @return None
    """

    validate_brightness_percentage(arguments.dim_brightness)

    if arguments.target_brightness is not None:
        validate_brightness_percentage(arguments.target_brightness)

    if arguments.index is not None and arguments.index <= 0:
        raise ValueError("显示器索引必须大于 0。")

    if arguments.index is not None and arguments.all:
        raise ValueError("`--index` 与 `--all` 不能同时使用。")

    if arguments.interval <= 0:
        raise ValueError("轮询间隔必须大于 0。")

    if arguments.dim_delay < 0:
        raise ValueError("调暗延迟不能小于 0。")

    if arguments.transition_duration <= 0:
        raise ValueError("渐变持续时间必须大于 0。")


def monitor_and_adjust_brightness(
    arguments: argparse.Namespace,
    controlled_monitor_states: list[ControlledMonitorState],
    runtime_control_state: RuntimeControlState | None = None,
    lumina_worker: LuminaOrientationWorker | None = None,
) -> int:
    """
    @brief 持续监控各屏幕状态并按需分别调整亮度。
    @param arguments 解析后的命令行参数对象。
    @param controlled_monitor_states 受控显示器状态列表。
    @param runtime_control_state 运行时控制状态对象；传入 None 表示普通命令行模式。
    @param lumina_worker Lumina 方向与亮度 worker；传入 None 表示不使用环境光自动亮度。
    @return int 返回进程退出码，0 表示成功。
    """

    transition_tick_interval = get_transition_tick_interval(
        arguments.interval
    )
    next_evaluation_time = 0.0
    mouse_idle_tracker = MouseIdleTracker()

    try:
        while True:
            if (
                runtime_control_state is not None
                and runtime_control_state.stop_event.is_set()
            ):
                return 0

            if not controlled_monitor_states:
                if runtime_control_state is None or arguments.once:
                    return 0

                wait_with_runtime_control(
                    runtime_control_state,
                    arguments.interval,
                )
                continue

            if runtime_control_state is not None:
                drain_manual_brightness_adjustments(
                    runtime_control_state,
                    controlled_monitor_states,
                )

            if not arguments.dry_run:
                advance_all_transitions(
                    controlled_monitor_states,
                    arguments.transition_duration,
                )

            current_time = time.monotonic()

            if current_time < next_evaluation_time:
                wait_with_runtime_control(
                    runtime_control_state,
                    transition_tick_interval,
                )
                continue

            next_evaluation_time = current_time + arguments.interval
            stable_restore_monitors = [
                monitor_state
                for monitor_state in controlled_monitor_states
                if monitor_state.current_mode == "restore"
                and not has_active_transition(monitor_state)
            ]

            if stable_restore_monitors:
                update_messages = synchronize_restore_brightness(
                    stable_restore_monitors
                )

                for update_message in update_messages:
                    log_and_print(
                        logger,
                        logging.INFO,
                        update_message,
                    )

            auto_dim_enabled = True
            restore_requested = False
            auto_brightness_targets: dict[int, int] = {}

            if runtime_control_state is not None:
                auto_dim_enabled = is_auto_dim_enabled(
                    runtime_control_state
                )
                restore_requested = consume_restore_request(
                    runtime_control_state
                )

            if lumina_worker is not None:
                auto_brightness_targets = (
                    lumina_worker.get_auto_brightness_targets_by_display()
                )

            if auto_brightness_targets:
                for monitor_state in controlled_monitor_states:
                    auto_brightness_target = auto_brightness_targets.get(
                        monitor_state.index
                    )

                    if auto_brightness_target is None:
                        continue

                    if monitor_state.restore_brightness == auto_brightness_target:
                        continue

                    if get_effective_mode(monitor_state) == "restore":
                        clear_transition_state(monitor_state)

                        if not arguments.dry_run:
                            try:
                                monitor_name = set_monitor_brightness_value(
                                    monitor_state,
                                    auto_brightness_target,
                                )
                            except Exception as error:
                                log_and_print(
                                    logger,
                                    logging.WARNING,
                                    str(error),
                                )
                                continue

                            if monitor_name is None:
                                continue

                    monitor_state.restore_brightness = auto_brightness_target
                    logger.info(
                        "Lumina 自动亮度目标更新: 显示器 [%s] %s -> %s%%。",
                        monitor_state.index,
                        monitor_state.description,
                        auto_brightness_target,
                    )

            if restore_requested or not auto_dim_enabled:
                for monitor_state in controlled_monitor_states:
                    monitor_state.dim_condition_started_at = None

                    if get_effective_mode(monitor_state) == "restore":
                        continue

                    if arguments.dry_run:
                        continue

                    message = start_monitor_transition(
                        monitor_state,
                        "restore",
                        monitor_state.restore_brightness,
                        arguments.transition_duration,
                    )
                    log_and_print(
                        logger,
                        logging.INFO,
                        message,
                    )

                wait_with_runtime_control(
                    runtime_control_state,
                    transition_tick_interval,
                )
                continue

            cursor_point = get_cursor_point()
            mouse_idle_seconds = (
                mouse_idle_tracker.update_and_get_idle_seconds(
                    current_time,
                    cursor_point,
                )
            )
            evaluation_results = evaluate_monitors(
                controlled_monitor_states,
                cursor_point,
                mouse_idle_seconds,
                arguments.dim_delay,
            )
            evaluation_result_map = {
                evaluation_result.index: evaluation_result
                for evaluation_result in evaluation_results
            }

            for monitor_state in controlled_monitor_states:
                evaluation_result = evaluation_result_map[monitor_state.index]
                effective_mode = get_effective_mode(monitor_state)
                desired_mode: str | None = None

                if evaluation_result.should_dim:
                    if effective_mode == "dim":
                        monitor_state.dim_condition_started_at = None
                        desired_mode = "dim"
                    elif evaluation_result.bypass_stabilization_delay:
                        monitor_state.dim_condition_started_at = None
                        desired_mode = "dim"
                    else:
                        if monitor_state.dim_condition_started_at is None:
                            monitor_state.dim_condition_started_at = current_time

                            if not arguments.dry_run and not arguments.once:
                                log_and_print(
                                    logger,
                                    logging.INFO,
                                    f"[{monitor_state.index}] 条件满足，连续 "
                                    f"{arguments.dim_delay:.1f} 秒后开始调暗。",
                                )

                        elapsed_seconds = (
                            current_time - monitor_state.dim_condition_started_at
                        )

                        if elapsed_seconds >= arguments.dim_delay:
                            desired_mode = "dim"
                        elif arguments.dry_run or arguments.once:
                            print_monitor_waiting_result(
                                evaluation_result,
                                monitor_state,
                                arguments.dim_brightness,
                                elapsed_seconds,
                                arguments.dim_delay,
                            )
                else:
                    monitor_state.dim_condition_started_at = None
                    desired_mode = "restore"

                if desired_mode is None:
                    if arguments.debug:
                        print_monitor_debug_result(
                            evaluation_result,
                            monitor_state,
                            desired_mode,
                            current_time,
                            mouse_idle_seconds,
                        )
                    continue

                target_brightness = monitor_state.restore_brightness

                if desired_mode == "dim":
                    target_brightness = arguments.dim_brightness

                if desired_mode != effective_mode:
                    if arguments.dry_run:
                        if desired_mode == "restore":
                            log_and_print(
                                logger,
                                logging.INFO,
                                f"模拟执行: 将在 {arguments.transition_duration:.1f} "
                                f"秒内恢复显示器 [{monitor_state.index}] 到 "
                                f"{monitor_state.restore_brightness}%",
                            )
                        else:
                            log_and_print(
                                logger,
                                logging.INFO,
                                f"模拟执行: 将在 {arguments.transition_duration:.1f} "
                                f"秒内调暗显示器 [{monitor_state.index}] 到 "
                                f"{arguments.dim_brightness}%",
                            )
                    else:
                        message = start_monitor_transition(
                            monitor_state,
                            desired_mode,
                            target_brightness,
                            arguments.transition_duration,
                        )
                        log_and_print(
                            logger,
                            logging.INFO,
                            message,
                        )
                elif arguments.dry_run or arguments.once:
                    print_monitor_evaluation_result(
                        evaluation_result,
                        monitor_state,
                        arguments.dim_brightness,
                    )

                if arguments.debug:
                    print_monitor_debug_result(
                        evaluation_result,
                        monitor_state,
                        desired_mode,
                        current_time,
                        mouse_idle_seconds,
                    )

            if arguments.once:
                return 0

            wait_with_runtime_control(
                runtime_control_state,
                transition_tick_interval,
            )
    finally:
        if not arguments.once and not arguments.dry_run:
            restore_all_monitors_on_exit(
                controlled_monitor_states,
                arguments.transition_duration,
                arguments.interval,
                runtime_control_state,
            )


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
    logger.info(
        "%s 启动，日志文件: %s，参数: %s",
        APPLICATION_NAME,
        log_file_path,
        vars(arguments),
    )

    try:
        validate_arguments(arguments)
        controlled_monitor_states = build_controlled_monitor_states(
            arguments.index,
            arguments.target_brightness,
        )

        if controlled_monitor_states:
            log_and_print(
                logger,
                logging.INFO,
                "初始恢复亮度: "
                f"{format_restore_brightness_summary(controlled_monitor_states)}",
            )
        else:
            log_and_print(
                logger,
                logging.WARNING,
                "当前没有可调亮度显示器，程序将继续运行 Lumina 与托盘功能。",
            )

        if (
            not arguments.no_tray
            and not arguments.once
            and not arguments.dry_run
        ):
            return run_with_system_tray(
                arguments,
                controlled_monitor_states,
            )

        return monitor_and_adjust_brightness(
            arguments,
            controlled_monitor_states,
        )
    except KeyboardInterrupt:
        log_and_print(
            logger,
            logging.INFO,
            "已收到中断信号，脚本退出。",
        )
        return 0
    except Exception as error:
        log_and_print(
            logger,
            logging.ERROR,
            f"执行失败: {error}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
