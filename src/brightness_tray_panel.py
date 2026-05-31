# -*- coding: utf-8 -*-
"""
@brief 托盘模式下用于手动调节亮度的简易 Tk 面板。
@note 在独立线程中运行 Tk 主循环，通过回调将亮度变更提交给后台工作线程。
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes
from tkinter import messagebox
from typing import Callable

from lumina_logging import APPLICATION_NAME

ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19
TRANSPARENT_COLOR = "#010101"
PANEL_BACKGROUND = "#1f232b"
PANEL_SURFACE = "#252b35"
PANEL_BORDER = "#3a4352"
TEXT_PRIMARY = "#f4f7fb"
TEXT_SECONDARY = "#aab4c3"
ACCENT_COLOR = "#ffc43d"
APPLICATION_ICON_RELATIVE_PATH = os.path.join("assets", "Lumina.png")
SOURCE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
APPLICATION_DIRECTORY = os.path.dirname(SOURCE_DIRECTORY)


class ACCENT_POLICY(ctypes.Structure):
    """
    @brief Windows 窗口组合管理器的 Accent 策略结构。
    @note 该结构用于请求 Windows 为 Tk 顶层窗口启用亚克力模糊效果。
    """

    _fields_ = [
        ("AccentState", wintypes.DWORD),
        ("AccentFlags", wintypes.DWORD),
        ("GradientColor", wintypes.DWORD),
        ("AnimationId", wintypes.DWORD),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    """
    @brief Windows 窗口组合属性数据结构。
    @note 该结构用于向 SetWindowCompositionAttribute 传递 Accent 策略。
    """

    _fields_ = [
        ("Attribute", wintypes.DWORD),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def convert_rgba_to_abgr_color(
    red_value: int,
    green_value: int,
    blue_value: int,
    alpha_value: int,
) -> int:
    """
    @brief 将 RGBA 通道值转换为 Windows Acrylic 使用的 ABGR 整数。
    @param red_value 红色通道值。
    @param green_value 绿色通道值。
    @param blue_value 蓝色通道值。
    @param alpha_value 透明度通道值。
    @return int 转换后的 ABGR 整数。
    """

    return (
        (alpha_value << 24)
        | (blue_value << 16)
        | (green_value << 8)
        | red_value
    )


def enable_window_acrylic(window_handle: int) -> None:
    """
    @brief 尝试为指定窗口启用 Windows 亚克力磨砂背景。
    @param window_handle Tk 顶层窗口的原生窗口句柄。
    @return None
    @note 不支持该接口的系统会自动跳过，保留半透明深色窗口效果。
    """

    if os.name != "nt":
        return

    set_window_composition_attribute = getattr(
        ctypes.windll.user32,
        "SetWindowCompositionAttribute",
        None,
    )

    if set_window_composition_attribute is None:
        return

    accent_policy = ACCENT_POLICY()
    accent_policy.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent_policy.AccentFlags = 2
    accent_policy.GradientColor = convert_rgba_to_abgr_color(
        31,
        35,
        43,
        210,
    )
    accent_policy.AnimationId = 0

    composition_data = WINDOWCOMPOSITIONATTRIBDATA()
    composition_data.Attribute = WCA_ACCENT_POLICY
    composition_data.Data = ctypes.cast(
        ctypes.pointer(accent_policy),
        ctypes.c_void_p,
    )
    composition_data.SizeOfData = ctypes.sizeof(accent_policy)
    set_window_composition_attribute(
        window_handle,
        ctypes.byref(composition_data),
    )


def draw_rounded_rectangle(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    **kwargs: object,
) -> int:
    """
    @brief 在 Canvas 上绘制平滑圆角矩形。
    @param canvas 目标 Canvas 控件。
    @param x1 左上角横坐标。
    @param y1 左上角纵坐标。
    @param x2 右下角横坐标。
    @param y2 右下角纵坐标。
    @param radius 圆角半径。
    @return int Canvas 图形对象标识。
    """

    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=24,
        **kwargs,
    )


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


def get_default_panel_brightness_levels() -> list[dict[str, float | int | None]]:
    """
    @brief 获取面板使用的默认五档自动亮度配置。
    @return list[dict[str, float | int | None]] 返回五档亮度配置副本。
    """

    return [
        {"min_lux": 0.0, "max_lux": 10.0, "brightness": 0},
        {"min_lux": 10.0, "max_lux": 30.0, "brightness": 25},
        {"min_lux": 30.0, "max_lux": 60.0, "brightness": 50},
        {"min_lux": 60.0, "max_lux": 100.0, "brightness": 75},
        {"min_lux": 100.0, "max_lux": None, "brightness": 100},
    ]


def format_panel_lux_value(value: float | int | None) -> str:
    """
    @brief 格式化面板中的 lux 数值。
    @param value lux 数值。
    @return str 返回适合输入框和提示显示的文本。
    """

    if value is None:
        return ""

    lux_value = float(value)

    if lux_value.is_integer():
        return str(int(lux_value))

    return f"{lux_value:g}"


def normalize_panel_brightness_percentage(value: object) -> int:
    """
    @brief 标准化面板中的亮度百分比。
    @param value 输入亮度值。
    @return int 返回 0 到 100 范围内的亮度百分比。
    """

    try:
        percentage = int(round(float(value)))
    except (TypeError, ValueError):
        percentage = 0

    if percentage < 0:
        return 0

    if percentage > 100:
        return 100

    return percentage


def normalize_panel_level_list(
    raw_levels: object,
) -> list[dict[str, float | int | None]]:
    """
    @brief 标准化面板中的五档自动亮度配置。
    @param raw_levels Lumina 配置中的档位列表。
    @return list[dict[str, float | int | None]] 返回连续且固定为五档的配置。
    """

    default_levels = get_default_panel_brightness_levels()

    if not isinstance(raw_levels, list) or len(raw_levels) != 5:
        return default_levels

    brightness_values: list[int] = []

    for level_index, default_level in enumerate(default_levels):
        raw_level = raw_levels[level_index]

        if not isinstance(raw_level, dict):
            brightness_values.append(int(default_level["brightness"]))
            continue

        brightness_values.append(
            normalize_panel_brightness_percentage(
                raw_level.get("brightness", default_level["brightness"])
            )
        )

    breakpoints: list[float] = []
    previous_breakpoint = 0.0

    for level_index, default_level in enumerate(default_levels[:4]):
        raw_level = raw_levels[level_index]
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

    return build_panel_levels_from_breakpoints(
        brightness_values,
        breakpoints,
    )


def extract_panel_level_breakpoints(
    levels: list[dict[str, float | int | None]],
) -> list[float]:
    """
    @brief 从五档配置中提取四个 lux 分界点。
    @param levels 五档自动亮度配置。
    @return list[float] 返回四个分界点。
    """

    normalized_levels = normalize_panel_level_list(levels)
    breakpoints: list[float] = []

    for level in normalized_levels[:4]:
        max_lux = level.get("max_lux")

        if max_lux is None:
            continue

        breakpoints.append(float(max_lux))

    return breakpoints[:4]


def build_panel_levels_from_breakpoints(
    brightness_values: list[int],
    breakpoints: list[float],
) -> list[dict[str, float | int | None]]:
    """
    @brief 根据亮度值和四个分界点生成连续五档配置。
    @param brightness_values 五个亮度百分比。
    @param breakpoints 四个递增 lux 分界点。
    @return list[dict[str, float | int | None]] 返回五档自动亮度配置。
    """

    levels: list[dict[str, float | int | None]] = []

    for level_index in range(5):
        if level_index == 0:
            min_lux = 0.0
        else:
            min_lux = float(breakpoints[level_index - 1])

        max_lux: float | None = None

        if level_index < len(breakpoints):
            max_lux = float(breakpoints[level_index])

        brightness_value = 0

        if level_index < len(brightness_values):
            brightness_value = normalize_panel_brightness_percentage(
                brightness_values[level_index]
            )

        levels.append(
            {
                "min_lux": min_lux,
                "max_lux": max_lux,
                "brightness": brightness_value,
            }
        )

    return levels


def format_panel_level_range(
    level: dict[str, float | int | None],
) -> str:
    """
    @brief 格式化单个自动亮度档位的范围。
    @param level 自动亮度档位配置。
    @return str 返回带 lux 单位的范围文本。
    """

    min_lux = level.get("min_lux", 0.0)
    max_lux = level.get("max_lux")
    min_text = format_panel_lux_value(min_lux)

    if max_lux is None:
        return f"{min_text} lux 以上"

    return f"{min_text}~{format_panel_lux_value(max_lux)} lux"


def configure_panel_entry_focus(entry_widget: tk.Entry) -> None:
    """
    @brief 配置无边框透明面板中的输入框焦点与选中样式。
    @param entry_widget 需要配置的输入框控件。
    @return None
    @note Windows 透明无边框窗口中，Canvas 内嵌输入框有时不会自动显示光标。
    """

    def focus_entry_on_mouse_press(event: tk.Event) -> None:
        """
        @brief 鼠标按下输入框时显式激活输入焦点。
        @param event Tk 鼠标事件。
        @return None
        """

        widget = event.widget

        if not isinstance(widget, tk.Entry):
            return

        try:
            widget.focus_force()
        except tk.TclError:
            return

    entry_widget.configure(
        takefocus=True,
        insertwidth=2,
        selectbackground=ACCENT_COLOR,
        selectforeground="#151922",
    )
    entry_widget.bind(
        "<ButtonPress-1>",
        focus_entry_on_mouse_press,
        add="+",
    )


class BrightnessRangeEditor(tk.Toplevel):
    """
    @brief 自动亮度档位范围编辑浮窗。
    @note 该窗口只编辑 4 个分界点，保存时生成固定五档范围。
    """

    def __init__(
        self,
        parent: tk.Toplevel,
        levels: list[dict[str, float | int | None]],
        on_saved: Callable[[list[float]], None],
    ) -> None:
        """
        @brief 初始化自动亮度档位范围编辑浮窗。
        @param parent 父级 Tk 顶层窗口。
        @param levels 当前五档自动亮度配置。
        @param on_saved 保存分界点时调用的回调。
        @return None
        """

        super().__init__(parent)
        self._on_saved = on_saved
        self._value_vars: list[tk.StringVar] = []
        self._entry_widgets: list[tk.Entry] = []
        self._preview_labels: list[tk.Label] = []
        self._error_label: tk.Label | None = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.title("档位范围")
        self.transient(parent)
        self.overrideredirect(True)
        self.resizable(False, False)
        self.configure(bg=TRANSPARENT_COLOR)

        try:
            self.attributes("-alpha", 0.96)
            self.attributes("-transparentcolor", TRANSPARENT_COLOR)
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self._build_widgets(levels)
        self._position_near_parent(parent)
        self.after_idle(self._activate_window)

    def _build_widgets(
        self,
        levels: list[dict[str, float | int | None]],
    ) -> None:
        """
        @brief 创建范围编辑浮窗控件。
        @param levels 当前五档自动亮度配置。
        @return None
        """

        normalized_levels = normalize_panel_level_list(levels)
        breakpoints = extract_panel_level_breakpoints(normalized_levels)
        title_font = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
        panel_width = 356
        panel_height = 238
        canvas = tk.Canvas(
            self,
            width=panel_width,
            height=panel_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        draw_rounded_rectangle(
            canvas,
            6,
            6,
            panel_width - 6,
            panel_height - 6,
            18,
            fill=PANEL_BACKGROUND,
            outline=PANEL_BORDER,
            width=1,
        )
        title_label = tk.Label(
            self,
            text="档位范围",
            bg=PANEL_BACKGROUND,
            fg=TEXT_PRIMARY,
            font=title_font,
            anchor=tk.W,
        )
        canvas.create_window(
            24,
            18,
            window=title_label,
            anchor=tk.NW,
        )
        close_button = tk.Button(
            self,
            text="×",
            command=self.destroy,
            bg=PANEL_BACKGROUND,
            fg=TEXT_SECONDARY,
            activebackground="#2a313d",
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=6,
            pady=0,
            font=title_font,
        )
        canvas.create_window(
            panel_width - 30,
            16,
            window=close_button,
            anchor=tk.NW,
        )
        captions = ["0/1", "1/2", "2/3", "3/4"]
        left_x = 24
        value_x = 64
        unit_x = 128
        first_row_y = 54
        row_step = 30
        preview_x = 188

        for index, caption in enumerate(captions):
            row_y = first_row_y + index * row_step
            caption_label = tk.Label(
                self,
                text=caption,
                bg=PANEL_BACKGROUND,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                left_x,
                row_y + 3,
                window=caption_label,
                anchor=tk.NW,
            )
            value_var = tk.StringVar(
                value=format_panel_lux_value(breakpoints[index])
            )
            value_var.trace_add("write", lambda *_args: self._refresh_preview())
            self._value_vars.append(value_var)
            value_entry = tk.Entry(
                self,
                textvariable=value_var,
                width=7,
                bg="#151922",
                fg=TEXT_PRIMARY,
                insertbackground=TEXT_PRIMARY,
                justify=tk.CENTER,
                font=small_font,
                bd=0,
                highlightthickness=1,
                highlightbackground=PANEL_BORDER,
                highlightcolor=ACCENT_COLOR,
            )
            configure_panel_entry_focus(value_entry)
            canvas.create_window(
                value_x,
                row_y,
                window=value_entry,
                anchor=tk.NW,
            )
            value_entry.bind("<Return>", lambda _event: self._save())
            self._entry_widgets.append(value_entry)
            unit_label = tk.Label(
                self,
                text="lux",
                bg=PANEL_BACKGROUND,
                fg=TEXT_SECONDARY,
                font=small_font,
            )
            canvas.create_window(
                unit_x,
                row_y + 3,
                window=unit_label,
                anchor=tk.NW,
            )

        preview_title = tk.Label(
            self,
            text="预览",
            bg=PANEL_BACKGROUND,
            fg=TEXT_PRIMARY,
            font=title_font,
            anchor=tk.W,
        )
        canvas.create_window(
            preview_x,
            54,
            window=preview_title,
            anchor=tk.NW,
        )

        for index in range(5):
            preview_label = tk.Label(
                self,
                text="",
                bg=PANEL_BACKGROUND,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                preview_x,
                80 + index * 20,
                window=preview_label,
                anchor=tk.NW,
            )
            self._preview_labels.append(preview_label)

        self._error_label = tk.Label(
            self,
            text="",
            bg=PANEL_BACKGROUND,
            fg="#ff7a7a",
            font=small_font,
            anchor=tk.W,
        )
        canvas.create_window(
            24,
            panel_height - 66,
            window=self._error_label,
            anchor=tk.NW,
        )
        button_frame = tk.Frame(self, bg=PANEL_BACKGROUND)
        canvas.create_window(
            panel_width // 2,
            panel_height - 48,
            window=button_frame,
            anchor=tk.N,
        )
        cancel_button = tk.Button(
            button_frame,
            text="取消",
            command=self.destroy,
            bg="#2a313d",
            fg=TEXT_PRIMARY,
            activebackground="#343d4b",
            activeforeground=TEXT_PRIMARY,
            bd=0,
            padx=12,
            pady=4,
            font=small_font,
        )
        cancel_button.pack(side=tk.LEFT, padx=(0, 8))
        save_button = tk.Button(
            button_frame,
            text="确定",
            command=self._save,
            bg=ACCENT_COLOR,
            fg="#151922",
            activebackground="#ffd873",
            activeforeground="#151922",
            bd=0,
            padx=12,
            pady=4,
            font=small_font,
        )
        save_button.pack(side=tk.LEFT)
        self._bind_window_drag(canvas)
        self._bind_window_drag(title_label)
        self._refresh_preview()

    def _bind_window_drag(self, widget: tk.Widget) -> None:
        """
        @brief 为范围编辑浮窗绑定拖拽移动行为。
        @param widget 接收拖拽事件的控件。
        @return None
        """

        def on_drag_start(event: tk.Event) -> None:
            """
            @brief 记录拖拽起点。
            @param event Tk 鼠标事件。
            @return None
            """

            self._drag_start_x = event.x_root - self.winfo_x()
            self._drag_start_y = event.y_root - self.winfo_y()

        def on_drag_motion(event: tk.Event) -> None:
            """
            @brief 根据鼠标位置移动范围编辑浮窗。
            @param event Tk 鼠标事件。
            @return None
            """

            next_x = event.x_root - self._drag_start_x
            next_y = event.y_root - self._drag_start_y
            self.geometry(f"+{next_x}+{next_y}")

        widget.bind("<ButtonPress-1>", on_drag_start)
        widget.bind("<B1-Motion>", on_drag_motion)

    def _activate_window(self) -> None:
        """
        @brief 在窗口完成创建后激活范围编辑浮窗。
        @return None
        """

        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

        try:
            enable_window_acrylic(int(self.winfo_id()))
        except Exception:
            pass

    def _position_near_parent(self, parent: tk.Toplevel) -> None:
        """
        @brief 将范围编辑浮窗定位到父窗口中间。
        @param parent 父级 Tk 顶层窗口。
        @return None
        """

        self.update_idletasks()
        parent.update_idletasks()
        position_x = parent.winfo_rootx() + max(
            0,
            (parent.winfo_width() - self.winfo_width()) // 2,
        )
        position_y = parent.winfo_rooty() + max(
            0,
            (parent.winfo_height() - self.winfo_height()) // 2,
        )
        self.geometry(f"+{position_x}+{position_y}")

    def _parse_breakpoints(self) -> tuple[list[float], str | None]:
        """
        @brief 解析并验证 4 个 lux 分界点。
        @return tuple[list[float], str | None] 返回分界点和错误信息。
        """

        breakpoints: list[float] = []
        previous_value = 0.0

        for entry_index, value_var in enumerate(self._value_vars):
            raw_text = value_var.get().strip()

            try:
                next_value = float(raw_text)
            except ValueError:
                return [], "请输入数字"

            if not math.isfinite(next_value):
                return [], "请输入有限数字"

            if next_value <= 0:
                return [], "分界点必须大于 0"

            if next_value <= previous_value:
                return [], "分界点必须从小到大"

            breakpoints.append(next_value)
            previous_value = next_value

            if entry_index < len(self._entry_widgets):
                self._entry_widgets[entry_index].configure(
                    highlightbackground=PANEL_BORDER
                )

        return breakpoints, None

    def _refresh_preview(self) -> None:
        """
        @brief 根据当前输入刷新五档范围预览。
        @return None
        """

        breakpoints, error_text = self._parse_breakpoints()

        if error_text is not None:
            if self._error_label is not None:
                self._error_label.configure(text=error_text)

            for entry_widget in self._entry_widgets:
                entry_widget.configure(highlightbackground="#ff7a7a")

            return

        if self._error_label is not None:
            self._error_label.configure(text="")

        preview_levels = build_panel_levels_from_breakpoints(
            [0, 25, 50, 75, 100],
            breakpoints,
        )

        for index, preview_label in enumerate(self._preview_labels):
            preview_label.configure(
                text=f"{index}档: {format_panel_level_range(preview_levels[index])}"
            )

    def _save(self) -> None:
        """
        @brief 保存分界点并关闭范围编辑浮窗。
        @return None
        """

        breakpoints, error_text = self._parse_breakpoints()

        if error_text is not None:
            if self._error_label is not None:
                self._error_label.configure(text=error_text)

            return

        self._on_saved(breakpoints)
        self.destroy()


class BrightnessTrayPanelController:
    """
    @brief 管理 Tk 根窗口与亮度调节面板的显示。
    @note 所有对 Tk 的创建与修改均应在该控制器所属的 UI 线程中执行。
    """

    def __init__(self) -> None:
        """
        @brief 初始化控制器状态。
        @return None
        """

        self._root: tk.Tk | None = None
        self._panel_window: tk.Toplevel | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._last_sent_values: dict[int, int] = {}
        self._icon_photo: tk.PhotoImage | None = None
        self._range_editor_window: BrightnessRangeEditor | None = None
        self._panel_position: tuple[int, int] | None = None

    def start(self) -> None:
        """
        @brief 启动 Tk 事件循环线程；若已启动则直接返回。
        @return None
        """

        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._tk_thread_main,
            daemon=True,
            name="BrightnessTrayTk",
        )
        self._thread.start()
        self._ready.wait(timeout=15.0)

    def _tk_thread_main(self) -> None:
        """
        @brief 在后台线程中创建隐藏根窗口并进入 mainloop。
        @return None
        """

        root = tk.Tk()
        root.withdraw()
        root.title(APPLICATION_NAME)
        root.configure(bg=TRANSPARENT_COLOR)
        self._apply_window_icon(root)
        self._root = root
        self._ready.set()
        root.mainloop()

    def _apply_window_icon(
        self,
        window: tk.Tk | tk.Toplevel,
    ) -> None:
        """
        @brief 为 Tk 根窗口或顶层窗口设置应用图标。
        @param window 需要设置图标的 Tk 窗口对象。
        @return None
        @note 图标资源缺失时保持默认窗口图标，避免影响主功能。
        """

        try:
            if self._icon_photo is None:
                icon_path = get_application_resource_path(APPLICATION_ICON_RELATIVE_PATH)
                self._icon_photo = tk.PhotoImage(file=icon_path)

            window.iconphoto(
                True,
                self._icon_photo,
            )
        except tk.TclError:
            return

    def show_multi_lumina_brightness_panel(
        self,
        monitor_rows: list[tuple[int, str, int]],
        get_monitor_rows: Callable[[], list[tuple[int, str, int]]],
        enqueue_brightness_change: Callable[[int, int], None],
        is_auto_dim_active: Callable[[], bool],
        toggle_auto_dim: Callable[[], bool],
        get_idle_delay_seconds: Callable[[], float],
        update_idle_delay_seconds: Callable[[float], None],
        is_autostart_active: Callable[[], bool],
        toggle_autostart: Callable[[], bool],
        lumina_snapshots: list[object],
        get_lumina_snapshots: Callable[[], list[object]],
        lumina_display_choices: list[tuple[int, str]],
        update_lumina_device_config: Callable[
            [str, int, str, bool, str, list[dict[str, float | int | None]]],
            None,
        ],
        update_monitor_lumina_binding: Callable[[int, str | None], None],
    ) -> None:
        """
        @brief 请求在 UI 线程中打开多 Lumina 亮度调节面板。
        @param monitor_rows 每行依次为显示器索引、描述文本、当前亮度百分比。
        @param get_monitor_rows 获取最新显示器亮度行的回调。
        @param enqueue_brightness_change 将索引与目标亮度百分比提交给工作线程的回调。
        @param is_auto_dim_active 获取自动调光当前启用状态的回调。
        @param toggle_auto_dim 切换自动调光状态并返回新状态的回调。
        @param get_idle_delay_seconds 获取自动暗屏空闲阈值秒数的回调。
        @param update_idle_delay_seconds 更新自动暗屏空闲阈值秒数的回调。
        @param is_autostart_active 获取自启动当前启用状态的回调。
        @param toggle_autostart 切换自启动状态并返回新状态的回调。
        @param lumina_snapshots Lumina 设备快照列表。
        @param get_lumina_snapshots 获取最新 Lumina 设备快照的回调。
        @param lumina_display_choices Lumina 可绑定显示器列表。
        @param update_lumina_device_config 更新指定 Lumina 配置的回调。
        @param update_monitor_lumina_binding 更新显示器自动亮度绑定的回调。
        @return None
        """

        if self._root is None:
            return

        def build_panel() -> None:
            """
            @brief 在 Tk 线程中构建或替换多 Lumina 亮度调节窗口。
            @return None
            """

            try:
                self._build_multi_lumina_panel_widgets(
                    monitor_rows,
                    get_monitor_rows,
                    enqueue_brightness_change,
                    is_auto_dim_active,
                    toggle_auto_dim,
                    get_idle_delay_seconds,
                    update_idle_delay_seconds,
                    is_autostart_active,
                    toggle_autostart,
                    lumina_snapshots,
                    get_lumina_snapshots,
                    lumina_display_choices,
                    update_lumina_device_config,
                    update_monitor_lumina_binding,
                )
            except Exception as error:
                messagebox.showerror(
                    APPLICATION_NAME,
                    f"亮度调节窗口创建失败：{error}",
                )

        self._root.after(0, build_panel)

    def _build_multi_lumina_panel_widgets(
        self,
        monitor_rows: list[tuple[int, str, int]],
        get_monitor_rows: Callable[[], list[tuple[int, str, int]]],
        enqueue_brightness_change: Callable[[int, int], None],
        is_auto_dim_active: Callable[[], bool],
        toggle_auto_dim: Callable[[], bool],
        get_idle_delay_seconds: Callable[[], float],
        update_idle_delay_seconds: Callable[[float], None],
        is_autostart_active: Callable[[], bool],
        toggle_autostart: Callable[[], bool],
        lumina_snapshots: list[object],
        get_lumina_snapshots: Callable[[], list[object]],
        lumina_display_choices: list[tuple[int, str]],
        update_lumina_device_config: Callable[
            [str, int, str, bool, str, list[dict[str, float | int | None]]],
            None,
        ],
        update_monitor_lumina_binding: Callable[[int, str | None], None],
    ) -> None:
        """
        @brief 在 Tk 线程中创建多 Lumina 亮度调节窗口。
        @param monitor_rows 每行依次为显示器索引、描述文本、当前亮度百分比。
        @param get_monitor_rows 获取最新显示器亮度行的回调。
        @param enqueue_brightness_change 将索引与目标亮度百分比提交给工作线程的回调。
        @param is_auto_dim_active 获取自动调光当前启用状态的回调。
        @param toggle_auto_dim 切换自动调光状态并返回新状态的回调。
        @param get_idle_delay_seconds 获取自动暗屏空闲阈值秒数的回调。
        @param update_idle_delay_seconds 更新自动暗屏空闲阈值秒数的回调。
        @param is_autostart_active 获取自启动当前启用状态的回调。
        @param toggle_autostart 切换自启动状态并返回新状态的回调。
        @param lumina_snapshots Lumina 设备快照列表。
        @param get_lumina_snapshots 获取最新 Lumina 设备快照的回调。
        @param lumina_display_choices Lumina 可绑定显示器列表。
        @param update_lumina_device_config 更新指定 Lumina 配置的回调。
        @param update_monitor_lumina_binding 更新显示器自动亮度绑定的回调。
        @return None
        """

        snapshots = list(lumina_snapshots)[:3]
        visible_monitor_rows = list(monitor_rows)[:3]
        device_count = len(snapshots)
        content_left = 22
        content_gap = 14
        lumina_card_min_width = 270
        brightness_area_width = 386
        lumina_area_width = 0

        if device_count > 0:
            lumina_area_width = (
                device_count * lumina_card_min_width
                + (device_count - 1) * content_gap
            )

        panel_width = (
            content_left * 2
            + brightness_area_width
            + (
                lumina_area_width + content_gap
                if device_count > 0
                else 0
            )
        )
        content_width = panel_width - content_left * 2
        lumina_card_height = 238
        top_section_height = 238
        brightness_row_height = 58
        brightness_card_height = (
            56
            + max(1, len(visible_monitor_rows)) * brightness_row_height
            + 18
        )
        brightness_card_height = max(top_section_height, brightness_card_height)
        bottom_section_height = 96
        lumina_card_width = 0

        if device_count > 0:
            lumina_card_width = (
                lumina_area_width - (device_count - 1) * content_gap
            ) // device_count

        brightness_card_left = content_left

        if device_count > 0:
            brightness_card_left = content_left + lumina_area_width + content_gap

        brightness_card_right = panel_width - content_left
        brightness_content_width = brightness_card_right - brightness_card_left
        panel_height = (
            22
            + brightness_card_height
            + bottom_section_height
        )
        content_right = panel_width - content_left
        monitor_rows_signature = self._make_monitor_rows_signature(
            visible_monitor_rows
        )
        lumina_signature = self._make_lumina_snapshot_signature(snapshots)

        if self._panel_window is not None:
            try:
                if self._panel_window.winfo_exists():
                    self._remember_panel_position(self._panel_window)
                    self._panel_window.destroy()
            except tk.TclError:
                pass

        self._panel_window = tk.Toplevel(self._root)
        win = self._panel_window
        win.title(f"{APPLICATION_NAME} 亮度")
        self._apply_window_icon(win)
        win.overrideredirect(True)
        win.resizable(False, False)
        win.configure(bg=TRANSPARENT_COLOR)
        win.attributes("-alpha", 0.94)
        win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        win.attributes("-topmost", True)

        canvas = tk.Canvas(
            win,
            width=panel_width,
            height=panel_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        draw_rounded_rectangle(
            canvas,
            10,
            10,
            panel_width - 10,
            panel_height - 10,
            36,
            fill=PANEL_BACKGROUND,
            outline=PANEL_BORDER,
            width=1,
        )

        row_title_font = tkfont.Font(
            family="Microsoft YaHei UI",
            size=10,
            weight="bold",
        )
        small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
        tiny_font = tkfont.Font(family="Microsoft YaHei UI", size=8)
        value_font = tkfont.Font(
            family="Microsoft YaHei UI",
            size=10,
            weight="bold",
        )
        monitor_scale_windows: dict[int, int] = {}
        monitor_binding_keys: dict[int, str] = {}
        lumina_auto_modes: dict[str, bool] = {}
        status_labels: dict[str, tk.Label] = {}
        orientation_labels: dict[str, tk.Label] = {}
        lux_labels: dict[str, tk.Label] = {}
        bottom_status_label: tk.Label | None = None

        def open_brightness_range_editor(
            parent_window: tk.Toplevel,
            levels: list[dict[str, float | int | None]],
            on_saved: Callable[[list[float]], None],
        ) -> None:
            """
            @brief 打开并持有自动亮度档位范围编辑浮窗。
            @param parent_window 父级面板窗口。
            @param levels 当前五档自动亮度配置。
            @param on_saved 保存分界点时调用的回调。
            @return None
            """

            try:
                if (
                    self._range_editor_window is not None
                    and self._range_editor_window.winfo_exists()
                ):
                    self._range_editor_window.destroy()
            except tk.TclError:
                pass

            self._range_editor_window = BrightnessRangeEditor(
                parent_window,
                levels,
                on_saved,
            )

        def configure_panel_menu(
            menu_widget: tk.OptionMenu,
            width: int,
        ) -> None:
            """
            @brief 统一配置面板下拉菜单样式。
            @param menu_widget 需要配置的下拉菜单。
            @param width 菜单文本宽度。
            @return None
            """

            menu_widget.configure(
                bg="#151922",
                fg=TEXT_PRIMARY,
                activebackground="#343d4b",
                activeforeground=TEXT_PRIMARY,
                highlightthickness=0,
                bd=0,
                font=small_font,
                width=width,
                padx=4,
                pady=3,
            )

        def set_monitor_scale_visible(is_visible: bool) -> None:
            """
            @brief 设置显示器手动亮度滑条是否可见。
            @param is_visible 是否显示手动亮度滑条。
            @return None
            """

            state = tk.NORMAL if is_visible else tk.HIDDEN

            for scale_window in monitor_scale_windows.values():
                canvas.itemconfigure(scale_window, state=state)

        def sync_brightness_binding_state(source_snapshots: list[object]) -> None:
            """
            @brief 从 Lumina 快照同步本地亮度绑定状态。
            @param source_snapshots Lumina 快照列表。
            @return None
            @note 该状态只用于面板内即时判断每块显示器的手动亮度滑条是否可见。
            """

            monitor_binding_keys.clear()
            lumina_auto_modes.clear()

            for snapshot in source_snapshots:
                config, _status, _level_label = get_snapshot_parts(snapshot)
                device_key = str(getattr(config, "device_key", ""))

                if not device_key:
                    continue

                lumina_auto_modes[device_key] = (
                    str(getattr(config, "brightness_mode", "manual")) == "auto"
                )
                display_indexes = getattr(
                    config,
                    "brightness_display_indexes",
                    [],
                )

                for display_index in display_indexes:
                    try:
                        monitor_binding_keys[int(display_index)] = device_key
                    except (TypeError, ValueError):
                        continue

        def is_monitor_auto_brightness_active(monitor_index: int) -> bool:
            """
            @brief 判断指定显示器是否正由开启自动亮度的 Lumina 接管。
            @param monitor_index 显示器索引。
            @return bool 若显示器已绑定且对应 Lumina 自动亮度开启则返回 True。
            """

            device_key = monitor_binding_keys.get(monitor_index)

            if device_key is None:
                return False

            return bool(lumina_auto_modes.get(device_key, False))

        def refresh_monitor_scale_visibility() -> None:
            """
            @brief 按显示器绑定关系刷新手动亮度滑条可见性。
            @return None
            @note 只有显示器绑定的 Lumina 已开启自动亮度时，才隐藏该显示器的手动滑条。
            """

            for monitor_index, scale_window in monitor_scale_windows.items():
                if is_monitor_auto_brightness_active(monitor_index):
                    state = tk.HIDDEN
                else:
                    state = tk.NORMAL

                canvas.itemconfigure(scale_window, state=state)

        def make_scale_callback(
            idx: int,
            label_widget: tk.Label,
        ) -> Callable[[str], None]:
            """
            @brief 为指定显示器索引生成 Scale 的 command 回调。
            @param idx 显示器索引。
            @param label_widget 用于显示当前百分比的标签控件。
            @return Callable[[str], None] 供 Scale 绑定的回调函数。
            """

            def on_scale_change(raw_value: str) -> None:
                """
                @brief 在滑块数值变化时更新标签并提交亮度。
                @param raw_value Scale 传入的字符串形式数值。
                @return None
                """

                percentage = int(round(float(raw_value)))
                percentage = max(0, min(100, percentage))
                label_widget.configure(text=f"{percentage}%")

                if self._last_sent_values.get(idx) == percentage:
                    return

                self._last_sent_values[idx] = percentage
                enqueue_brightness_change(idx, percentage)

            return on_scale_change

        def format_lumina_status_text(status: object) -> str:
            """
            @brief 格式化 Lumina 连接状态文本。
            @param status Lumina 状态快照对象。
            @return str 用于显示的连接状态文本。
            """

            if bool(getattr(status, "connected", False)):
                return "已连接"

            return "未连接"

        def format_lumina_orientation_text(status: object) -> str:
            """
            @brief 格式化 Lumina 当前朝向文本。
            @param status Lumina 状态快照对象。
            @return str 用于显示的当前朝向文本。
            """

            current_orientation = getattr(status, "current_orientation", None)

            if current_orientation is None:
                return "当前: --"

            return f"当前: {current_orientation}"

        def format_lumina_brightness_text(
            status: object,
            level_label: str | None,
        ) -> str:
            """
            @brief 格式化 Lumina 自动亮度状态文本。
            @param status Lumina 状态快照对象。
            @param level_label 当前自动亮度档位标签。
            @return str 用于显示的档位与 lux 文本。
            """

            current_lux_value = getattr(status, "current_lux", None)

            if current_lux_value is None:
                return f"档位: {level_label or '--'} | lux: --"

            return (
                f"档位: {level_label or '--'} | "
                f"lux: {float(current_lux_value):.1f}"
            )

        def get_snapshot_parts(snapshot: object) -> tuple[object, object, str | None]:
            """
            @brief 从 Lumina 快照对象中拆出配置、状态和档位标签。
            @param snapshot Lumina 快照对象。
            @return tuple[object, object, str | None] 配置、状态和档位标签。
            """

            config = getattr(snapshot, "config")
            status = getattr(snapshot, "status")
            level_label = getattr(snapshot, "brightness_level_label", None)
            return config, status, level_label

        def get_snapshot_by_key(
            source_snapshots: list[object],
            device_key: str,
        ) -> object | None:
            """
            @brief 按设备 key 查找 Lumina 快照。
            @param source_snapshots Lumina 快照列表。
            @param device_key Lumina 设备 key。
            @return 找到时返回快照，否则返回 None。
            """

            for snapshot in source_snapshots:
                config, _status, _level_label = get_snapshot_parts(snapshot)

                if str(getattr(config, "device_key", "")) == device_key:
                    return snapshot

            return None

        tooltip_rect = canvas.create_rectangle(
            0,
            0,
            0,
            0,
            fill="#343d4b",
            outline=PANEL_BORDER,
            state=tk.HIDDEN,
        )
        tooltip_label = canvas.create_text(
            0,
            0,
            text="",
            fill=TEXT_PRIMARY,
            font=small_font,
            state=tk.HIDDEN,
        )

        def show_tooltip(
            tooltip_text: str,
            center_x: int,
            center_y: int,
        ) -> None:
            """
            @brief 显示图案按钮或档位标签的功能提示。
            @param tooltip_text 提示文本。
            @param center_x 提示文本中心横坐标。
            @param center_y 提示文本中心纵坐标。
            @return None
            """

            canvas.itemconfigure(tooltip_label, text=tooltip_text, state=tk.NORMAL)
            canvas.coords(tooltip_label, center_x, center_y)
            text_bounds = canvas.bbox(tooltip_label)

            if text_bounds is None:
                return

            left, top, right, bottom = text_bounds
            canvas.coords(
                tooltip_rect,
                left - 8,
                top - 5,
                right + 8,
                bottom + 5,
            )
            canvas.itemconfigure(tooltip_rect, state=tk.NORMAL)
            canvas.tag_raise(tooltip_rect)
            canvas.tag_raise(tooltip_label)

        def hide_tooltip() -> None:
            """
            @brief 隐藏图案按钮或档位标签的功能提示。
            @return None
            """

            canvas.itemconfigure(tooltip_rect, state=tk.HIDDEN)
            canvas.itemconfigure(tooltip_label, state=tk.HIDDEN)

        display_label_by_index = {
            index: label
            for index, label in lumina_display_choices
        }
        display_index_by_label = {
            label: index
            for index, label in lumina_display_choices
        }
        display_labels = list(display_index_by_label.keys())

        if not display_labels:
            display_labels = ["无显示器"]

        def draw_lumina_card(
            snapshot: object,
            card_index: int,
            card_left: int,
            card_top: int,
        ) -> None:
            """
            @brief 绘制单张 Lumina 设备卡片。
            @param snapshot Lumina 快照对象。
            @param card_index 卡片序号。
            @param card_left 卡片左上角横坐标。
            @param card_top 卡片左上角纵坐标。
            @return None
            """

            config, status, level_label = get_snapshot_parts(snapshot)
            device_key = str(getattr(config, "device_key", f"device-{card_index}"))
            label_text = str(getattr(config, "label", f"Lumina#{card_index}"))
            card_right = card_left + lumina_card_width
            card_bottom = card_top + lumina_card_height
            draw_rounded_rectangle(
                canvas,
                card_left,
                card_top,
                card_right,
                card_bottom,
                24,
                fill=PANEL_SURFACE,
                outline="#323b49",
                width=1,
            )

            title_label = tk.Label(
                win,
                text=label_text,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=row_title_font,
                anchor=tk.W,
            )
            canvas.create_window(
                card_left + 18,
                card_top + 14,
                window=title_label,
                anchor=tk.NW,
            )

            status_label = tk.Label(
                win,
                text=format_lumina_status_text(status),
                bg=PANEL_SURFACE,
                fg=ACCENT_COLOR if getattr(status, "connected", False) else TEXT_SECONDARY,
                font=tiny_font,
                anchor=tk.E,
            )
            status_labels[device_key] = status_label
            canvas.create_window(
                card_right - 18,
                card_top + 15,
                window=status_label,
                anchor=tk.NE,
            )

            enabled_var = tk.BooleanVar(
                value=bool(getattr(config, "enabled", False))
            )
            brightness_mode_var = tk.StringVar(
                value=str(getattr(config, "brightness_mode", "manual"))
            )
            auto_brightness_var = tk.BooleanVar(
                value=brightness_mode_var.get() == "auto"
            )
            home_orientation_var = tk.StringVar(
                value=str(getattr(config, "home_orientation", "X+"))
            )
            current_display_index = int(getattr(config, "display_index", 1))
            current_display_label = display_label_by_index.get(
                current_display_index,
                display_labels[0],
            )
            display_var = tk.StringVar(value=current_display_label)
            levels = normalize_panel_level_list(
                getattr(config, "brightness_levels", None)
            )

            if len(levels) != 5:
                levels = normalize_panel_level_list(None)

            level_vars = [
                tk.StringVar(value=str(int(level.get("brightness", 0))))
                for level in levels
            ]
            level_submit_after_id: str | None = None

            def cancel_device_config_later() -> None:
                """
                @brief 取消当前卡片控件值的延迟提交。
                @return None
                """

                nonlocal level_submit_after_id

                if level_submit_after_id is None:
                    return

                try:
                    win.after_cancel(level_submit_after_id)
                except tk.TclError:
                    pass

                level_submit_after_id = None

            def sync_level_vars_from_levels() -> None:
                """
                @brief 将当前档位配置中的亮度值同步到输入框变量。
                @return None
                @note 范围编辑保存后调用，避免旧输入框状态覆盖新的档位配置。
                """

                for level_index, level in enumerate(levels):
                    if level_index >= len(level_vars):
                        continue

                    level_vars[level_index].set(
                        str(int(level.get("brightness", 0)))
                    )

            def get_level_value(level_index: int) -> int:
                """
                @brief 获取并限制指定自动亮度档位输入值。
                @param level_index 自动亮度档位索引。
                @return int 返回 0 到 100 范围内的亮度百分比。
                """

                try:
                    level_value = int(level_vars[level_index].get())
                except (tk.TclError, ValueError):
                    level_value = 0

                if level_value < 0:
                    level_value = 0

                if level_value > 100:
                    level_value = 100

                level_vars[level_index].set(level_value)
                return level_value

            def submit_device_config_later() -> None:
                """
                @brief 延迟提交当前卡片控件值。
                @return None
                @note 用于档位输入框停止输入后自动保存，避免每个按键都写配置。
                """

                nonlocal level_submit_after_id

                cancel_device_config_later()

                level_submit_after_id = win.after(
                    500,
                    submit_device_config_from_delay,
                )

            def submit_device_config_from_delay() -> None:
                """
                @brief 处理档位输入框延迟提交回调。
                @return None
                """

                nonlocal level_submit_after_id

                level_submit_after_id = None
                submit_device_config()

            def submit_device_config_now() -> None:
                """
                @brief 立即提交当前卡片控件值并取消待执行的延迟提交。
                @return None
                """

                nonlocal level_submit_after_id

                cancel_device_config_later()

                submit_device_config()

            def submit_device_config() -> None:
                """
                @brief 将当前卡片控件值提交到后台 Lumina 服务。
                @return None
                """

                display_label = display_var.get()
                display_index = display_index_by_label.get(
                    display_label,
                    current_display_index,
                )
                next_brightness_mode = (
                    "auto" if auto_brightness_var.get() else "manual"
                )
                brightness_mode_var.set(next_brightness_mode)
                lumina_auto_modes[device_key] = next_brightness_mode == "auto"
                next_levels: list[dict[str, float | int | None]] = []

                for level_index, level in enumerate(levels):
                    next_levels.append(
                        {
                            "min_lux": level.get("min_lux"),
                            "max_lux": level.get("max_lux"),
                            "brightness": get_level_value(level_index),
                        }
                    )

                levels[:] = next_levels
                update_lumina_device_config(
                    device_key,
                    display_index,
                    home_orientation_var.get(),
                    enabled_var.get(),
                    next_brightness_mode,
                    next_levels,
                )
                refresh_monitor_scale_visibility()

            def get_brightness_values() -> list[int]:
                """
                @brief 获取当前五档亮度百分比。
                @return list[int] 返回五个亮度百分比。
                """

                return [
                    get_level_value(level_index)
                    for level_index in range(len(level_vars))
                ]

            def open_range_editor() -> None:
                """
                @brief 打开自动亮度档位范围编辑浮窗。
                @return None
                """

                def on_range_saved(breakpoints: list[float]) -> None:
                    """
                    @brief 保存范围编辑器返回的分界点。
                    @param breakpoints 四个 lux 分界点。
                    @return None
                    """

                    cancel_device_config_later()
                    next_levels = build_panel_levels_from_breakpoints(
                        get_brightness_values(),
                        breakpoints,
                    )
                    levels[:] = next_levels
                    sync_level_vars_from_levels()
                    submit_device_config()

                open_brightness_range_editor(
                    win,
                    levels,
                    on_range_saved,
                )

            rotate_label = tk.Label(
                win,
                text="自动旋转",
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                card_left + 18,
                card_top + 48,
                window=rotate_label,
                anchor=tk.NW,
            )

            enabled_check = tk.Checkbutton(
                win,
                text="",
                variable=enabled_var,
                command=submit_device_config,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                activebackground=PANEL_SURFACE,
                activeforeground=TEXT_PRIMARY,
                selectcolor="#151922",
                font=small_font,
                bd=0,
                highlightthickness=0,
            )
            canvas.create_window(
                card_left + 86,
                card_top + 44,
                window=enabled_check,
                anchor=tk.NW,
            )

            orientation_label = tk.Label(
                win,
                text=format_lumina_orientation_text(status),
                bg=PANEL_SURFACE,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            orientation_labels[device_key] = orientation_label
            canvas.create_window(
                card_left + 116,
                card_top + 48,
                window=orientation_label,
                anchor=tk.NW,
            )

            display_menu = tk.OptionMenu(
                win,
                display_var,
                *display_labels,
                command=lambda _value: submit_device_config(),
            )
            configure_panel_menu(
                display_menu,
                max(14, min(22, lumina_card_width // 12)),
            )
            canvas.create_window(
                card_left + 18,
                card_top + 74,
                window=display_menu,
                anchor=tk.NW,
            )

            orientation_menu = tk.OptionMenu(
                win,
                home_orientation_var,
                "X+",
                "X-",
                "Y+",
                "Y-",
                command=lambda _value: submit_device_config(),
            )
            configure_panel_menu(orientation_menu, 4)
            canvas.create_window(
                card_right - 80,
                card_top + 74,
                window=orientation_menu,
                anchor=tk.NW,
            )

            brightness_label = tk.Label(
                win,
                text="自动亮度",
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                card_left + 18,
                card_top + 118,
                window=brightness_label,
                anchor=tk.NW,
            )

            auto_brightness_check = tk.Checkbutton(
                win,
                text="",
                variable=auto_brightness_var,
                command=submit_device_config,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                activebackground=PANEL_SURFACE,
                activeforeground=TEXT_PRIMARY,
                selectcolor="#151922",
                font=small_font,
                bd=0,
                highlightthickness=0,
            )
            canvas.create_window(
                card_left + 86,
                card_top + 114,
                window=auto_brightness_check,
                anchor=tk.NW,
            )

            lux_label = tk.Label(
                win,
                text=format_lumina_brightness_text(status, level_label),
                bg=PANEL_SURFACE,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            lux_labels[device_key] = lux_label
            canvas.create_window(
                card_left + 116,
                card_top + 118,
                window=lux_label,
                anchor=tk.NW,
            )

            level_title = tk.Label(
                win,
                text="亮度档位",
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=row_title_font,
                anchor=tk.W,
            )
            canvas.create_window(
                card_left + 18,
                card_top + 152,
                window=level_title,
                anchor=tk.NW,
            )

            level_labels = ["0档", "1档", "2档", "3档", "4档"]
            level_column_width = max(44, (lumina_card_width - 36) // 5)
            level_label_y = card_top + 180
            level_entry_y = card_top + 202

            for level_index, label_text in enumerate(level_labels):
                label_x = card_left + 18 + level_index * level_column_width
                level_label = tk.Label(
                    win,
                    text=label_text,
                    bg=PANEL_SURFACE,
                    fg=TEXT_SECONDARY,
                    font=tiny_font,
                    anchor=tk.W,
                    cursor="hand2",
                )
                canvas.create_window(
                    label_x,
                    level_label_y,
                    window=level_label,
                    anchor=tk.NW,
                )
                level_label.bind(
                    "<Enter>",
                    lambda event, target_index=level_index: show_tooltip(
                        format_panel_level_range(levels[target_index]),
                        event.x_root - win.winfo_rootx() + 42,
                        level_entry_y + 34,
                    ),
                )
                level_label.bind("<Leave>", lambda _event: hide_tooltip())
                level_label.bind("<Button-1>", lambda _event: open_range_editor())

                level_entry = tk.Entry(
                    win,
                    textvariable=level_vars[level_index],
                    width=4,
                    bg="#151922",
                    fg=TEXT_PRIMARY,
                    insertbackground=TEXT_PRIMARY,
                    justify=tk.CENTER,
                    font=tiny_font,
                    bd=0,
                    highlightthickness=0,
                )
                configure_panel_entry_focus(level_entry)
                level_entry.bind(
                    "<KeyRelease>",
                    lambda _event: submit_device_config_later(),
                )
                level_entry.bind(
                    "<FocusOut>",
                    lambda _event: submit_device_config_now(),
                )
                level_entry.bind(
                    "<Return>",
                    lambda _event: submit_device_config_now(),
                )
                canvas.create_window(
                    label_x,
                    level_entry_y,
                    window=level_entry,
                    anchor=tk.NW,
                )

        card_top = 22

        for index, snapshot in enumerate(snapshots, start=1):
            card_left = content_left + (index - 1) * (
                lumina_card_width + content_gap
            )
            draw_lumina_card(
                snapshot,
                index,
                card_left,
                card_top,
            )

        brightness_card_top = card_top
        brightness_card_bottom = brightness_card_top + brightness_card_height
        draw_rounded_rectangle(
            canvas,
            brightness_card_left,
            brightness_card_top,
            brightness_card_right,
            brightness_card_bottom,
            24,
            fill=PANEL_SURFACE,
            outline="#323b49",
            width=1,
        )

        brightness_title = tk.Label(
            win,
            text="显示屏亮度",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=row_title_font,
            anchor=tk.W,
        )
        canvas.create_window(
            brightness_card_left + 18,
            brightness_card_top + 14,
            window=brightness_title,
            anchor=tk.NW,
        )

        lumina_choice_labels = ["手动"]
        lumina_choice_key_map: dict[str, str | None] = {
            "手动": None,
        }

        for snapshot in snapshots:
            config, _status, _level_label = get_snapshot_parts(snapshot)
            label_text = str(getattr(config, "label", "Lumina"))
            lumina_choice_labels.append(label_text)
            lumina_choice_key_map[label_text] = str(getattr(config, "device_key", ""))

        sync_brightness_binding_state(snapshots)

        def get_bound_lumina_label(monitor_index: int) -> str:
            """
            @brief 获取显示器当前绑定的 Lumina 标签。
            @param monitor_index 显示器索引。
            @return str 返回绑定标签，未绑定时返回手动。
            """

            for snapshot in snapshots:
                config, _status, _level_label = get_snapshot_parts(snapshot)
                display_indexes = getattr(
                    config,
                    "brightness_display_indexes",
                    [],
                )

                if monitor_index in display_indexes:
                    return str(getattr(config, "label", "Lumina"))

            return "手动"

        row_top = brightness_card_top + 54
        scale_length = max(170, min(260, brightness_content_width - 210))

        if not visible_monitor_rows:
            empty_label = tk.Label(
                win,
                text="未检测到可调亮度显示器",
                bg=PANEL_SURFACE,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                brightness_card_left + 18,
                row_top + 10,
                window=empty_label,
                anchor=tk.NW,
            )

        for monitor_index, description_text, current_percentage in visible_monitor_rows:
            header = f"[{monitor_index}] {description_text}"
            monitor_label = tk.Label(
                win,
                text=header,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=row_title_font,
                width=30,
                anchor=tk.W,
            )
            canvas.create_window(
                brightness_card_left + 18,
                row_top + 2,
                window=monitor_label,
                anchor=tk.NW,
            )

            value_label = tk.Label(
                win,
                text=f"{current_percentage}%",
                bg=PANEL_SURFACE,
                fg=ACCENT_COLOR,
                font=value_font,
                width=5,
                anchor=tk.E,
            )
            canvas.create_window(
                brightness_card_right - 182,
                row_top + 2,
                window=value_label,
                anchor=tk.NW,
            )

            binding_var = tk.StringVar(
                value=get_bound_lumina_label(monitor_index)
            )

            def submit_binding(
                selected_label: str,
                target_monitor_index: int = monitor_index,
            ) -> None:
                """
                @brief 提交显示器到 Lumina 的自动亮度绑定。
                @param selected_label 选中的 Lumina 标签。
                @param target_monitor_index 目标显示器索引。
                @return None
                """

                update_monitor_lumina_binding(
                    target_monitor_index,
                    lumina_choice_key_map.get(selected_label),
                )
                selected_key = lumina_choice_key_map.get(selected_label)

                if selected_key is None:
                    monitor_binding_keys.pop(target_monitor_index, None)
                else:
                    monitor_binding_keys[target_monitor_index] = selected_key

                refresh_monitor_scale_visibility()

            binding_menu = tk.OptionMenu(
                win,
                binding_var,
                *lumina_choice_labels,
                command=submit_binding,
            )
            configure_panel_menu(binding_menu, 8)
            canvas.create_window(
                brightness_card_right - 106,
                row_top - 2,
                window=binding_menu,
                anchor=tk.NW,
            )

            brightness_scale = tk.Scale(
                win,
                from_=0,
                to=100,
                orient=tk.HORIZONTAL,
                length=scale_length,
                tickinterval=0,
                resolution=1,
                showvalue=False,
                bd=0,
                highlightthickness=0,
                sliderlength=18,
                width=12,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                troughcolor="#151922",
                activebackground=ACCENT_COLOR,
            )
            brightness_scale.set(current_percentage)
            self._last_sent_values[monitor_index] = current_percentage
            brightness_scale.configure(
                command=make_scale_callback(monitor_index, value_label)
            )
            scale_window = canvas.create_window(
                brightness_card_left + 18,
                row_top + 28,
                window=brightness_scale,
                anchor=tk.NW,
            )
            monitor_scale_windows[monitor_index] = scale_window
            row_top += brightness_row_height

        refresh_monitor_scale_visibility()

        idle_delay_var = tk.StringVar(value=f"{get_idle_delay_seconds():.1f}")
        idle_delay_submit_after_id: str | None = None

        def cancel_idle_delay_later() -> None:
            """
            @brief 取消自动暗屏空闲阈值的延迟提交。
            @return None
            """

            nonlocal idle_delay_submit_after_id

            if idle_delay_submit_after_id is None:
                return

            try:
                win.after_cancel(idle_delay_submit_after_id)
            except tk.TclError:
                pass

            idle_delay_submit_after_id = None

        def submit_idle_delay_later() -> None:
            """
            @brief 延迟提交自动暗屏空闲阈值。
            @return None
            @note 用于输入停止后自动保存空闲阈值。
            """

            nonlocal idle_delay_submit_after_id

            cancel_idle_delay_later()
            idle_delay_submit_after_id = win.after(
                700,
                submit_idle_delay_from_delay,
            )

        def submit_idle_delay_from_delay() -> None:
            """
            @brief 处理自动暗屏空闲阈值延迟提交回调。
            @return None
            """

            nonlocal idle_delay_submit_after_id

            idle_delay_submit_after_id = None
            submit_idle_delay()

        def submit_idle_delay_now() -> None:
            """
            @brief 立即提交自动暗屏空闲阈值并取消待执行的延迟提交。
            @return None
            """

            cancel_idle_delay_later()
            submit_idle_delay()

        def submit_idle_delay() -> None:
            """
            @brief 提交自动暗屏空闲阈值。
            @return None
            """

            try:
                delay_seconds = float(idle_delay_var.get())
            except ValueError:
                delay_seconds = get_idle_delay_seconds()

            if delay_seconds < 0:
                delay_seconds = 0.0

            idle_delay_var.set(f"{delay_seconds:g}")
            update_idle_delay_seconds(delay_seconds)

        bottom_center_y = panel_height - 58
        bottom_button_radius = 18
        auto_center_x = panel_width // 2 - 66
        close_center_x = panel_width // 2
        autostart_center_x = panel_width // 2 + 66
        idle_delay_entry_x = auto_center_x - bottom_button_radius - 42
        auto_icon_color = ACCENT_COLOR if is_auto_dim_active() else TEXT_SECONDARY

        def create_button_circle(
            center_x: int,
            center_y: int,
        ) -> int:
            """
            @brief 绘制底部图案按钮的圆形底座。
            @param center_x 圆心横坐标。
            @param center_y 圆心纵坐标。
            @return int Canvas 圆形对象标识。
            """

            return canvas.create_oval(
                center_x - bottom_button_radius,
                center_y - bottom_button_radius,
                center_x + bottom_button_radius,
                center_y + bottom_button_radius,
                fill="#2a313d",
                outline=PANEL_BORDER,
                width=1,
            )

        def set_icon_items_color(
            item_ids: list[int],
            target_color: str,
        ) -> None:
            """
            @brief 设置一组 Canvas 图案对象颜色。
            @param item_ids Canvas 图案对象列表。
            @param target_color 目标颜色。
            @return None
            """

            for item_id in item_ids:
                try:
                    canvas.itemconfigure(item_id, fill=target_color)
                except tk.TclError:
                    pass

                try:
                    canvas.itemconfigure(item_id, outline=target_color)
                except tk.TclError:
                    pass

        def bind_icon_button(
            item_ids: list[int],
            on_clicked: Callable[[], None],
            tooltip_text: str,
            tooltip_center_x: int,
        ) -> None:
            """
            @brief 为一组 Canvas 图案对象绑定按钮事件。
            @param item_ids 组成按钮的 Canvas 图案对象标识列表。
            @param on_clicked 点击按钮时执行的回调。
            @param tooltip_text 鼠标悬停提示文本。
            @param tooltip_center_x 提示文本中心横坐标。
            @return None
            """

            def on_button_enter(event: tk.Event) -> None:
                """
                @brief 处理按钮鼠标进入事件。
                @param event Tk 鼠标事件。
                @return None
                """

                del event
                canvas.configure(cursor="hand2")
                show_tooltip(
                    tooltip_text,
                    tooltip_center_x,
                    bottom_center_y - 44,
                )

            def on_button_leave(event: tk.Event) -> None:
                """
                @brief 处理按钮鼠标离开事件。
                @param event Tk 鼠标事件。
                @return None
                """

                del event
                canvas.configure(cursor="")
                hide_tooltip()

            for item_id in item_ids:
                canvas.tag_bind(item_id, "<Button-1>", lambda _event: on_clicked())
                canvas.tag_bind(item_id, "<Enter>", on_button_enter)
                canvas.tag_bind(item_id, "<Leave>", on_button_leave)

        auto_circle = create_button_circle(auto_center_x, bottom_center_y)
        auto_icon_ids = [
            canvas.create_oval(
                auto_center_x - 9,
                bottom_center_y - 10,
                auto_center_x + 9,
                bottom_center_y + 10,
                outline=auto_icon_color,
                fill=auto_icon_color,
                width=2,
            ),
            canvas.create_oval(
                auto_center_x - 2,
                bottom_center_y - 12,
                auto_center_x + 13,
                bottom_center_y + 7,
                outline="#2a313d",
                fill="#2a313d",
                width=2,
            ),
        ]

        close_circle = create_button_circle(close_center_x, bottom_center_y)
        close_icon_ids = [
            canvas.create_line(
                close_center_x - 7,
                bottom_center_y - 7,
                close_center_x + 7,
                bottom_center_y + 7,
                fill=TEXT_SECONDARY,
                width=2,
                capstyle=tk.ROUND,
            ),
            canvas.create_line(
                close_center_x + 7,
                bottom_center_y - 7,
                close_center_x - 7,
                bottom_center_y + 7,
                fill=TEXT_SECONDARY,
                width=2,
                capstyle=tk.ROUND,
            ),
        ]

        autostart_circle = create_button_circle(
            autostart_center_x,
            bottom_center_y,
        )
        autostart_color = ACCENT_COLOR if is_autostart_active() else TEXT_SECONDARY
        autostart_icon_ids = [
            canvas.create_line(
                autostart_center_x - 5,
                bottom_center_y - 8,
                autostart_center_x + 11,
                bottom_center_y,
                autostart_center_x - 5,
                bottom_center_y + 8,
                autostart_center_x - 5,
                bottom_center_y - 8,
                fill=autostart_color,
                width=2,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            ),
        ]

        def update_auto_button_state(is_active: bool) -> None:
            """
            @brief 根据自动调光启用状态刷新月亮图案颜色。
            @param is_active 自动调光是否启用。
            @return None
            """

            icon_color = ACCENT_COLOR if is_active else TEXT_SECONDARY
            set_icon_items_color([auto_icon_ids[0]], icon_color)
            set_icon_items_color([auto_icon_ids[1]], "#2a313d")

        def update_autostart_button_state(is_active: bool) -> None:
            """
            @brief 根据自启动启用状态刷新三角形图案颜色。
            @param is_active 自启动是否启用。
            @return None
            """

            icon_color = ACCENT_COLOR if is_active else TEXT_SECONDARY
            set_icon_items_color(autostart_icon_ids, icon_color)

        def on_auto_button_clicked() -> None:
            """
            @brief 切换自动调光状态并刷新图案按钮。
            @return None
            """

            update_auto_button_state(toggle_auto_dim())

        def on_autostart_button_clicked() -> None:
            """
            @brief 切换自启动状态并刷新图案按钮。
            @return None
            """

            update_autostart_button_state(toggle_autostart())

        idle_delay_entry = tk.Entry(
            win,
            textvariable=idle_delay_var,
            width=4,
            bg="#151922",
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            justify=tk.CENTER,
            font=small_font,
            bd=0,
            highlightthickness=0,
        )
        configure_panel_entry_focus(idle_delay_entry)
        idle_delay_entry.bind(
            "<KeyRelease>",
            lambda _event: submit_idle_delay_later(),
        )
        idle_delay_entry.bind(
            "<FocusOut>",
            lambda _event: submit_idle_delay_now(),
        )
        idle_delay_entry.bind(
            "<Return>",
            lambda _event: submit_idle_delay_now(),
        )
        idle_delay_entry.bind(
            "<Enter>",
            lambda _event: show_tooltip(
                "空闲时间阈值（秒）",
                idle_delay_entry_x + 16,
                bottom_center_y - 44,
            ),
        )
        idle_delay_entry.bind("<Leave>", lambda _event: hide_tooltip())
        canvas.create_window(
            idle_delay_entry_x,
            bottom_center_y,
            window=idle_delay_entry,
            anchor=tk.W,
        )

        def format_bottom_status_text(source_snapshots: list[object]) -> str:
            """
            @brief 格式化面板右下角 Lumina 总状态。
            @param source_snapshots Lumina 快照列表。
            @return str 返回总状态文本。
            """

            connected_count = 0

            for snapshot in source_snapshots:
                _config, status, _level_label = get_snapshot_parts(snapshot)

                if getattr(status, "connected", False):
                    connected_count += 1

            if connected_count > 0:
                return f"已连接 {connected_count}"

            return "未连接"

        def has_connected_lumina(source_snapshots: list[object]) -> bool:
            """
            @brief 判断快照列表中是否存在已连接 Lumina。
            @param source_snapshots Lumina 快照列表。
            @return bool 存在已连接 Lumina 时返回 True。
            """

            for snapshot in source_snapshots:
                _config, status, _level_label = get_snapshot_parts(snapshot)

                if getattr(status, "connected", False):
                    return True

            return False

        bottom_status_label = tk.Label(
            win,
            text=format_bottom_status_text(snapshots),
            bg=PANEL_BACKGROUND,
            fg=ACCENT_COLOR if has_connected_lumina(snapshots) else TEXT_SECONDARY,
            font=small_font,
            anchor=tk.CENTER,
        )
        canvas.create_window(
            content_right - 6,
            panel_height - 26,
            window=bottom_status_label,
            anchor=tk.SE,
        )

        author_text_id = canvas.create_text(
            content_left + 6,
            panel_height - 26,
            text="化学制品 | 1.1",
            fill=TEXT_SECONDARY,
            font=tiny_font,
            anchor=tk.SW,
        )

        def on_author_enter(event: tk.Event) -> None:
            """
            @brief 处理底部作者文字鼠标进入事件。
            @param event Tk 鼠标事件。
            @return None
            """

            del event
            canvas.configure(cursor="hand2")
            show_tooltip(
                "1324146673@qq.com",
                content_left + 74,
                bottom_center_y - 44,
            )

        def on_author_leave(event: tk.Event) -> None:
            """
            @brief 处理底部作者文字鼠标离开事件。
            @param event Tk 鼠标事件。
            @return None
            """

            del event
            canvas.configure(cursor="")
            hide_tooltip()

        canvas.tag_bind(author_text_id, "<Enter>", on_author_enter)
        canvas.tag_bind(author_text_id, "<Leave>", on_author_leave)

        bind_icon_button(
            [auto_circle] + auto_icon_ids,
            on_auto_button_clicked,
            "启用/暂停自动暗屏",
            auto_center_x,
        )
        bind_icon_button(
            [close_circle] + close_icon_ids,
            win.destroy,
            "关闭面板",
            close_center_x,
        )
        bind_icon_button(
            [autostart_circle] + autostart_icon_ids,
            on_autostart_button_clicked,
            "开启/关闭自启动",
            autostart_center_x,
        )

        def refresh_lumina_status_labels() -> None:
            """
            @brief 定时刷新多 Lumina 状态标签与显示器列表。
            @return None
            """

            try:
                if not win.winfo_exists():
                    return

                latest_snapshots = list(get_lumina_snapshots())
                latest_monitor_rows = list(get_monitor_rows())[:3]
                sync_brightness_binding_state(latest_snapshots)
                refresh_monitor_scale_visibility()

                if (
                    self._make_monitor_rows_signature(latest_monitor_rows)
                    != monitor_rows_signature
                    or self._make_lumina_snapshot_signature(latest_snapshots)
                    != lumina_signature
                ):
                    self.show_multi_lumina_brightness_panel(
                        latest_monitor_rows,
                        get_monitor_rows,
                        enqueue_brightness_change,
                        is_auto_dim_active,
                        toggle_auto_dim,
                        get_idle_delay_seconds,
                        update_idle_delay_seconds,
                        is_autostart_active,
                        toggle_autostart,
                        latest_snapshots,
                        get_lumina_snapshots,
                        lumina_display_choices,
                        update_lumina_device_config,
                        update_monitor_lumina_binding,
                    )
                    return

                for device_key, status_label in status_labels.items():
                    latest_snapshot = get_snapshot_by_key(
                        latest_snapshots,
                        device_key,
                    )

                    if latest_snapshot is None:
                        continue

                    _config, status, level_label = get_snapshot_parts(
                        latest_snapshot
                    )
                    latest_connected = bool(getattr(status, "connected", False))
                    status_label.configure(
                        text=format_lumina_status_text(status),
                        fg=ACCENT_COLOR if latest_connected else TEXT_SECONDARY,
                    )

                    if device_key in orientation_labels:
                        orientation_labels[device_key].configure(
                            text=format_lumina_orientation_text(status)
                        )

                    if device_key in lux_labels:
                        lux_labels[device_key].configure(
                            text=format_lumina_brightness_text(
                                status,
                                level_label,
                            )
                        )

                if bottom_status_label is not None:
                    bottom_status_color = (
                        ACCENT_COLOR
                        if has_connected_lumina(latest_snapshots)
                        else TEXT_SECONDARY
                    )
                    bottom_status_label.configure(
                        text=format_bottom_status_text(latest_snapshots),
                        fg=bottom_status_color,
                    )

                win.after(1000, refresh_lumina_status_labels)
            except tk.TclError:
                return

        win.after(1000, refresh_lumina_status_labels)
        self._bind_window_drag(win, canvas)

        win.update_idletasks()
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        position_x, position_y = self._get_panel_position(
            screen_width,
            screen_height,
            panel_width,
            panel_height,
        )
        win.geometry(f"{panel_width}x{panel_height}+{position_x}+{position_y}")
        self._panel_position = (
            position_x,
            position_y,
        )
        win.after(200, lambda: win.attributes("-topmost", False))
        enable_window_acrylic(int(win.winfo_id()))

    def show_brightness_panel(
        self,
        monitor_rows: list[tuple[int, str, int]],
        get_monitor_rows: Callable[[], list[tuple[int, str, int]]],
        enqueue_brightness_change: Callable[[int, int], None],
        is_auto_dim_active: Callable[[], bool],
        toggle_auto_dim: Callable[[], bool],
        get_idle_delay_seconds: Callable[[], float],
        update_idle_delay_seconds: Callable[[float], None],
        is_autostart_active: Callable[[], bool],
        toggle_autostart: Callable[[], bool],
        lumina_config: object,
        lumina_status: object,
        lumina_brightness_level_label: str | None,
        get_lumina_status: Callable[[], object],
        get_lumina_brightness_level_label: Callable[[], str | None],
        lumina_display_choices: list[tuple[int, str]],
        update_lumina_config: Callable[[int, str, bool, str, list[dict[str, float | int | None]]], None],
    ) -> None:
        """
        @brief 请求在 UI 线程中打开或刷新亮度调节面板。
        @param monitor_rows 每行依次为显示器索引、描述文本、当前亮度百分比。
        @param get_monitor_rows 获取最新显示器亮度行的回调。
        @param enqueue_brightness_change 将索引与目标亮度百分比提交给工作线程的回调。
        @param is_auto_dim_active 获取自动调光当前启用状态的回调。
        @param toggle_auto_dim 切换自动调光状态并返回新状态的回调。
        @param get_idle_delay_seconds 获取自动暗屏空闲阈值秒数的回调。
        @param update_idle_delay_seconds 更新自动暗屏空闲阈值秒数的回调。
        @param is_autostart_active 获取自启动当前启用状态的回调。
        @param toggle_autostart 切换自启动状态并返回新状态的回调。
        @param lumina_config Lumina 当前配置对象。
        @param lumina_status Lumina 当前状态对象。
        @param lumina_brightness_level_label Lumina 当前自动亮度档位标签。
        @param get_lumina_status 获取 Lumina 最新状态快照的回调。
        @param get_lumina_brightness_level_label 获取 Lumina 最新自动亮度档位标签的回调。
        @param lumina_display_choices Lumina 可绑定显示器列表。
        @param update_lumina_config 更新 Lumina 配置的回调。
        @return None
        """

        if self._root is None:
            return

        def build_panel() -> None:
            """
            @brief 在 Tk 线程中构建或替换亮度调节窗口。
            @return None
            """

            try:
                self._build_panel_widgets(
                    monitor_rows,
                    get_monitor_rows,
                    enqueue_brightness_change,
                    is_auto_dim_active,
                    toggle_auto_dim,
                    get_idle_delay_seconds,
                    update_idle_delay_seconds,
                    is_autostart_active,
                    toggle_autostart,
                    lumina_config,
                    lumina_status,
                    lumina_brightness_level_label,
                    get_lumina_status,
                    get_lumina_brightness_level_label,
                    lumina_display_choices,
                    update_lumina_config,
                )
            except Exception as error:
                messagebox.showerror(
                    APPLICATION_NAME,
                    f"亮度调节窗口创建失败：{error}",
                )

        self._root.after(0, build_panel)

    def _build_panel_widgets(
        self,
        monitor_rows: list[tuple[int, str, int]],
        get_monitor_rows: Callable[[], list[tuple[int, str, int]]],
        enqueue_brightness_change: Callable[[int, int], None],
        is_auto_dim_active: Callable[[], bool],
        toggle_auto_dim: Callable[[], bool],
        get_idle_delay_seconds: Callable[[], float],
        update_idle_delay_seconds: Callable[[float], None],
        is_autostart_active: Callable[[], bool],
        toggle_autostart: Callable[[], bool],
        lumina_config: object,
        lumina_status: object,
        lumina_brightness_level_label: str | None,
        get_lumina_status: Callable[[], object],
        get_lumina_brightness_level_label: Callable[[], str | None],
        lumina_display_choices: list[tuple[int, str]],
        update_lumina_config: Callable[[int, str, bool, str, list[dict[str, float | int | None]]], None],
    ) -> None:
        """
        @brief 在 Tk 线程中创建亮度调节面板控件。
        @param monitor_rows 每行依次为显示器索引、描述文本、当前亮度百分比。
        @param get_monitor_rows 获取最新显示器亮度行的回调。
        @param enqueue_brightness_change 将索引与目标亮度百分比提交给工作线程的回调。
        @param is_auto_dim_active 获取自动调光当前启用状态的回调。
        @param toggle_auto_dim 切换自动调光状态并返回新状态的回调。
        @param get_idle_delay_seconds 获取自动暗屏空闲阈值秒数的回调。
        @param update_idle_delay_seconds 更新自动暗屏空闲阈值秒数的回调。
        @param is_autostart_active 获取自启动当前启用状态的回调。
        @param toggle_autostart 切换自启动状态并返回新状态的回调。
        @param lumina_config Lumina 当前配置对象。
        @param lumina_status Lumina 当前状态对象。
        @param lumina_brightness_level_label Lumina 当前自动亮度档位标签。
        @param get_lumina_status 获取 Lumina 最新状态快照的回调。
        @param get_lumina_brightness_level_label 获取 Lumina 最新自动亮度档位标签的回调。
        @param lumina_display_choices Lumina 可绑定显示器列表。
        @param update_lumina_config 更新 Lumina 配置的回调。
        @return None
        """

        panel_width = 820
        initial_brightness_mode = str(getattr(lumina_config, "brightness_mode", "manual"))

        if initial_brightness_mode not in ("manual", "auto"):
            initial_brightness_mode = "manual"

        is_auto_brightness_layout = initial_brightness_mode == "auto"
        content_left = 22
        content_right = panel_width - 22
        top_card_gap = 14
        lumina_card_width = 386
        lumina_card_left = content_left
        lumina_card_right = lumina_card_left + lumina_card_width
        brightness_card_left = lumina_card_right + top_card_gap
        brightness_card_right = content_right
        lumina_row_height = 238
        manual_monitor_row_height = 74
        auto_monitor_row_height = 46

        if is_auto_brightness_layout:
            row_height = auto_monitor_row_height
        else:
            row_height = manual_monitor_row_height

        brightness_card_header_height = 44
        brightness_card_height = max(
            lumina_row_height,
            brightness_card_header_height + max(1, len(monitor_rows)) * row_height + 14,
        )
        top_section_height = max(lumina_row_height, brightness_card_height)
        row_step = row_height
        bottom_button_radius = 18
        bottom_section_height = 96
        monitor_rows_signature = self._make_monitor_rows_signature(monitor_rows)

        panel_height = (
            22
            + top_section_height
            + bottom_section_height
        )

        if self._panel_window is not None:
            try:
                if self._panel_window.winfo_exists():
                    self._remember_panel_position(self._panel_window)
                    self._panel_window.destroy()
            except tk.TclError:
                pass

        self._panel_window = tk.Toplevel(self._root)
        win = self._panel_window
        win.title(f"{APPLICATION_NAME} 亮度")
        self._apply_window_icon(win)
        win.overrideredirect(True)
        win.resizable(False, False)
        win.configure(bg=TRANSPARENT_COLOR)
        win.attributes("-alpha", 0.94)
        win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        win.attributes("-topmost", True)

        canvas = tk.Canvas(
            win,
            width=panel_width,
            height=panel_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        draw_rounded_rectangle(
            canvas,
            10,
            10,
            panel_width - 10,
            panel_height - 10,
            36,
            fill=PANEL_BACKGROUND,
            outline=PANEL_BORDER,
            width=1,
        )

        row_title_font = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
        value_font = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        button_font = tkfont.Font(family="Microsoft YaHei UI", size=12, weight="bold")
        monitor_scale_windows: dict[int, int] = {}

        def open_brightness_range_editor(
            parent_window: tk.Toplevel,
            levels: list[dict[str, float | int | None]],
            on_saved: Callable[[list[float]], None],
        ) -> None:
            """
            @brief 打开并持有单 Lumina 自动亮度档位范围编辑浮窗。
            @param parent_window 父级面板窗口。
            @param levels 当前五档自动亮度配置。
            @param on_saved 保存分界点时调用的回调。
            @return None
            """

            try:
                if (
                    self._range_editor_window is not None
                    and self._range_editor_window.winfo_exists()
                ):
                    self._range_editor_window.destroy()
            except tk.TclError:
                pass

            self._range_editor_window = BrightnessRangeEditor(
                parent_window,
                levels,
                on_saved,
            )

        def set_monitor_scale_visible(is_visible: bool) -> None:
            """
            @brief 设置显示器手动亮度滑条是否可见。
            @param is_visible 是否显示手动亮度滑条。
            @return None
            """

            state = tk.NORMAL if is_visible else tk.HIDDEN

            for scale_window in monitor_scale_windows.values():
                canvas.itemconfigure(scale_window, state=state)

        def get_bound_brightness_display_indexes() -> set[int]:
            """
            @brief 获取当前 Lumina 已绑定的自动亮度显示器索引集合。
            @return set[int] 已绑定显示器索引集合。
            """

            indexes: set[int] = set()

            for display_index in getattr(
                lumina_config,
                "brightness_display_indexes",
                [],
            ):
                try:
                    indexes.add(int(display_index))
                except (TypeError, ValueError):
                    continue

            return indexes

        def refresh_monitor_scale_visibility() -> None:
            """
            @brief 按当前 Lumina 自动亮度状态刷新手动亮度滑条可见性。
            @return None
            @note 只有显示器绑定到当前 Lumina 且自动亮度开启时才隐藏滑条。
            """

            bound_display_indexes = get_bound_brightness_display_indexes()
            is_auto_brightness_active = brightness_mode_var.get() == "auto"

            for monitor_index, scale_window in monitor_scale_windows.items():
                if is_auto_brightness_active and monitor_index in bound_display_indexes:
                    state = tk.HIDDEN
                else:
                    state = tk.NORMAL

                canvas.itemconfigure(scale_window, state=state)

        def make_scale_callback(
            idx: int,
            label_widget: tk.Label,
        ) -> Callable[[str], None]:
            """
            @brief 为指定显示器索引生成 Scale 的 command 回调。
            @param idx 显示器索引。
            @param label_widget 用于显示当前百分比的标签控件。
            @return Callable[[str], None] 供 Scale 绑定的回调函数。
            """

            def on_scale_change(raw_value: str) -> None:
                """
                @brief 在滑块数值变化时更新标签并提交亮度。
                @param raw_value Scale 传入的字符串形式数值。
                @return None
                """

                percentage = int(round(float(raw_value)))
                percentage = max(0, min(100, percentage))
                label_widget.configure(text=f"{percentage}%")

                if self._last_sent_values.get(idx) == percentage:
                    return

                self._last_sent_values[idx] = percentage
                enqueue_brightness_change(idx, percentage)

            return on_scale_change

        row_top = 22
        lumina_bottom = row_top + lumina_row_height
        brightness_card_bottom = row_top + brightness_card_height
        draw_rounded_rectangle(
            canvas,
            lumina_card_left,
            row_top,
            lumina_card_right,
            lumina_bottom,
            27,
            fill=PANEL_SURFACE,
            outline="#323b49",
            width=1,
        )
        draw_rounded_rectangle(
            canvas,
            brightness_card_left,
            row_top,
            brightness_card_right,
            brightness_card_bottom,
            27,
            fill=PANEL_SURFACE,
            outline="#323b49",
            width=1,
        )

        lumina_enabled_var = tk.BooleanVar(
            value=bool(getattr(lumina_config, "enabled", False))
        )
        lumina_display_map = {
            label: index for index, label in lumina_display_choices
        }
        lumina_display_labels = list(lumina_display_map.keys())
        current_display_index = int(getattr(lumina_config, "display_index", 1))
        current_display_label = ""

        for label, index in lumina_display_map.items():
            if index == current_display_index:
                current_display_label = label
                break

        if not current_display_label and lumina_display_labels:
            current_display_label = lumina_display_labels[0]

        lumina_display_var = tk.StringVar(value=current_display_label)
        lumina_orientation_var = tk.StringVar(
            value=str(getattr(lumina_config, "home_orientation", "X+"))
        )
        brightness_mode_var = tk.StringVar(
            value=initial_brightness_mode
        )
        brightness_levels = normalize_panel_level_list(
            getattr(lumina_config, "brightness_levels", None)
        )

        brightness_level_vars: list[tk.StringVar] = []
        for level in brightness_levels:
            brightness_level_vars.append(
                tk.StringVar(value=str(int(level.get("brightness", 0))))
            )
        brightness_level_submit_after_id: str | None = None

        def cancel_lumina_config_later() -> None:
            """
            @brief 取消 Lumina 配置控件值的延迟提交。
            @return None
            """

            nonlocal brightness_level_submit_after_id

            if brightness_level_submit_after_id is None:
                return

            try:
                win.after_cancel(brightness_level_submit_after_id)
            except tk.TclError:
                pass

            brightness_level_submit_after_id = None

        def sync_brightness_level_vars_from_levels() -> None:
            """
            @brief 将当前档位配置中的亮度值同步到输入框变量。
            @return None
            @note 范围编辑保存后调用，避免旧输入框状态覆盖新的档位配置。
            """

            for level_index, level in enumerate(brightness_levels):
                if level_index >= len(brightness_level_vars):
                    continue

                brightness_level_vars[level_index].set(
                    str(int(level.get("brightness", 0)))
                )

        def get_brightness_level_value(level_index: int) -> int:
            """
            @brief 获取并限制指定自动亮度档位输入值。
            @param level_index 自动亮度档位索引。
            @return int 返回 0 到 100 范围内的亮度百分比。
            """

            try:
                level_value = int(brightness_level_vars[level_index].get())
            except (tk.TclError, ValueError):
                level_value = 0

            if level_value < 0:
                level_value = 0

            if level_value > 100:
                level_value = 100

            brightness_level_vars[level_index].set(level_value)

            return level_value

        def submit_lumina_config_later() -> None:
            """
            @brief 延迟提交 Lumina 配置控件中的值。
            @return None
            @note 用于档位输入框停止输入后自动保存，避免每个按键都写配置。
            """

            nonlocal brightness_level_submit_after_id

            cancel_lumina_config_later()

            brightness_level_submit_after_id = win.after(
                500,
                submit_lumina_config_from_delay,
            )

        def submit_lumina_config_from_delay() -> None:
            """
            @brief 处理亮度档位输入框延迟提交回调。
            @return None
            """

            nonlocal brightness_level_submit_after_id

            brightness_level_submit_after_id = None
            submit_lumina_config()

        def submit_lumina_config_now() -> None:
            """
            @brief 立即提交 Lumina 配置控件中的值并取消待执行的延迟提交。
            @return None
            """

            nonlocal brightness_level_submit_after_id

            cancel_lumina_config_later()

            submit_lumina_config()

        def get_brightness_level_values() -> list[int]:
            """
            @brief 获取当前五档亮度百分比。
            @return list[int] 返回五个亮度百分比。
            """

            return [
                get_brightness_level_value(level_index)
                for level_index in range(len(brightness_level_vars))
            ]

        def open_range_editor() -> None:
            """
            @brief 打开自动亮度档位范围编辑浮窗。
            @return None
            """

            def on_range_saved(breakpoints: list[float]) -> None:
                """
                @brief 保存范围编辑器返回的分界点。
                @param breakpoints 四个 lux 分界点。
                @return None
                """

                cancel_lumina_config_later()
                next_levels = build_panel_levels_from_breakpoints(
                    get_brightness_level_values(),
                    breakpoints,
                )
                brightness_levels[:] = next_levels
                sync_brightness_level_vars_from_levels()
                submit_lumina_config()

            open_brightness_range_editor(
                win,
                brightness_levels,
                on_range_saved,
            )

        idle_delay_var = tk.StringVar(value=f"{get_idle_delay_seconds():.1f}")
        idle_delay_submit_after_id: str | None = None

        def cancel_idle_delay_later() -> None:
            """
            @brief 取消自动暗屏空闲阈值的延迟提交。
            @return None
            """

            nonlocal idle_delay_submit_after_id

            if idle_delay_submit_after_id is None:
                return

            try:
                win.after_cancel(idle_delay_submit_after_id)
            except tk.TclError:
                pass

            idle_delay_submit_after_id = None

        def submit_idle_delay_later() -> None:
            """
            @brief 延迟提交自动暗屏空闲阈值。
            @return None
            @note 用于输入停止后自动保存空闲阈值。
            """

            nonlocal idle_delay_submit_after_id

            cancel_idle_delay_later()
            idle_delay_submit_after_id = win.after(
                700,
                submit_idle_delay_from_delay,
            )

        def submit_idle_delay_from_delay() -> None:
            """
            @brief 处理自动暗屏空闲阈值延迟提交回调。
            @return None
            """

            nonlocal idle_delay_submit_after_id

            idle_delay_submit_after_id = None
            submit_idle_delay()

        def submit_idle_delay_now() -> None:
            """
            @brief 立即提交自动暗屏空闲阈值并取消待执行的延迟提交。
            @return None
            """

            cancel_idle_delay_later()
            submit_idle_delay()

        def submit_idle_delay() -> None:
            """
            @brief 提交自动暗屏空闲阈值输入框中的值。
            @return None
            """

            try:
                delay_seconds = float(idle_delay_var.get())
            except ValueError:
                delay_seconds = get_idle_delay_seconds()

            if delay_seconds < 0:
                delay_seconds = 0.0

            idle_delay_var.set(f"{delay_seconds:g}")
            update_idle_delay_seconds(delay_seconds)

        def submit_lumina_config() -> None:
            """
            @brief 将 Lumina 配置控件中的值提交到后台服务。
            @return None
            """

            display_label = lumina_display_var.get()
            display_index = lumina_display_map.get(display_label, current_display_index)
            next_orientation = lumina_orientation_var.get()
            next_enabled = lumina_enabled_var.get()
            next_brightness_mode = brightness_mode_var.get()
            next_levels: list[dict[str, float | int | None]] = []

            for level_index, level in enumerate(brightness_levels):
                next_levels.append(
                    {
                        "min_lux": level.get("min_lux"),
                        "max_lux": level.get("max_lux"),
                        "brightness": get_brightness_level_value(level_index),
                    }
                )

            brightness_levels[:] = next_levels
            update_lumina_config(
                display_index,
                next_orientation,
                next_enabled,
                next_brightness_mode,
                next_levels,
            )
            lumina_config.display_index = display_index
            lumina_config.home_orientation = next_orientation
            lumina_config.enabled = next_enabled
            lumina_config.brightness_mode = next_brightness_mode
            lumina_config.brightness_levels = next_levels

        lumina_title = tk.Label(
            win,
            text="Lumina",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=row_title_font,
            anchor=tk.W,
        )
        canvas.create_window(lumina_card_left + 20, row_top + 14, window=lumina_title, anchor=tk.NW)

        def format_lumina_status_text(status: object) -> str:
            """
            @brief 格式化 Lumina 连接状态文本。
            @param status Lumina 状态快照对象。
            @return str 返回用于显示的连接状态文本。
            """

            device_count = int(getattr(status, "device_count", 0) or 0)

            if bool(getattr(status, "connected", False)):
                return f"已连接 | {max(device_count, 1)}"

            return "未连接"

        def format_lumina_orientation_text(status: object) -> str:
            """
            @brief 格式化 Lumina 当前朝向文本。
            @param status Lumina 状态快照对象。
            @return str 返回用于显示的当前朝向文本。
            """

            next_orientation = getattr(status, "current_orientation", None)

            if next_orientation is None:
                return "当前: --"

            return f"当前: {next_orientation}"

        def format_lumina_brightness_text(
            status: object,
            level_label: str | None,
        ) -> str:
            """
            @brief 格式化 Lumina 自动亮度状态文本。
            @param status Lumina 状态快照对象。
            @param level_label 当前自动亮度档位标签。
            @return str 返回用于显示的档位与 lux 文本。
            """

            current_lux_value = getattr(status, "current_lux", None)

            if current_lux_value is None:
                return f"档位: {level_label or '--'} | lux: --"

            return (
                f"档位: {level_label or '--'} | "
                f"lux: {float(current_lux_value):.1f}"
            )

        orientation_text = format_lumina_orientation_text(lumina_status)

        rotate_label = tk.Label(
            win,
            text="自动旋转",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=small_font,
            anchor=tk.W,
        )
        canvas.create_window(lumina_card_left + 20, row_top + 48, window=rotate_label, anchor=tk.NW)

        lumina_enabled_check = tk.Checkbutton(
            win,
            text="",
            variable=lumina_enabled_var,
            command=submit_lumina_config,
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            activebackground=PANEL_SURFACE,
            activeforeground=TEXT_PRIMARY,
            selectcolor="#151922",
            font=small_font,
            bd=0,
            highlightthickness=0,
        )
        canvas.create_window(lumina_card_left + 90, row_top + 44, window=lumina_enabled_check, anchor=tk.NW)

        orientation_status_label = tk.Label(
            win,
            text=orientation_text,
            bg=PANEL_SURFACE,
            fg=TEXT_SECONDARY,
            font=small_font,
            anchor=tk.W,
        )
        canvas.create_window(lumina_card_left + 120, row_top + 48, window=orientation_status_label, anchor=tk.NW)

        display_menu = tk.OptionMenu(
            win,
            lumina_display_var,
            *lumina_display_labels,
            command=lambda _value: submit_lumina_config(),
        )
        display_menu.configure(
            bg="#151922",
            fg=TEXT_PRIMARY,
            activebackground="#343d4b",
            activeforeground=TEXT_PRIMARY,
            highlightthickness=0,
            bd=0,
            font=small_font,
            width=24,
            padx=4,
            pady=3,
        )
        canvas.create_window(lumina_card_left + 20, row_top + 72, window=display_menu, anchor=tk.NW)

        orientation_menu = tk.OptionMenu(
            win,
            lumina_orientation_var,
            "X+",
            "X-",
            "Y+",
            "Y-",
            command=lambda _value: submit_lumina_config(),
        )
        orientation_menu.configure(
            bg="#151922",
            fg=TEXT_PRIMARY,
            activebackground="#343d4b",
            activeforeground=TEXT_PRIMARY,
            highlightthickness=0,
            bd=0,
            font=small_font,
            width=5,
            padx=4,
            pady=3,
        )
        canvas.create_window(lumina_card_right - 112, row_top + 72, window=orientation_menu, anchor=tk.NW)

        auto_brightness_var = tk.BooleanVar(value=brightness_mode_var.get() == "auto")

        def submit_brightness_enabled() -> None:
            """
            @brief 根据自动亮度勾选状态更新亮度模式。
            @return None
            """

            if auto_brightness_var.get():
                brightness_mode_var.set("auto")
            else:
                brightness_mode_var.set("manual")

            submit_lumina_config()
            refresh_monitor_scale_visibility()

        brightness_label = tk.Label(
            win,
            text="自动亮度",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=small_font,
            anchor=tk.W,
        )
        canvas.create_window(lumina_card_left + 20, row_top + 120, window=brightness_label, anchor=tk.NW)

        auto_brightness_check = tk.Checkbutton(
            win,
            text="",
            variable=auto_brightness_var,
            command=submit_brightness_enabled,
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            activebackground=PANEL_SURFACE,
            activeforeground=TEXT_PRIMARY,
            selectcolor="#151922",
            font=small_font,
            bd=0,
            highlightthickness=0,
        )
        canvas.create_window(lumina_card_left + 90, row_top + 116, window=auto_brightness_check, anchor=tk.NW)

        auto_brightness_text = format_lumina_brightness_text(
            lumina_status,
            lumina_brightness_level_label,
        )

        lux_label = tk.Label(
            win,
            text=auto_brightness_text,
            bg=PANEL_SURFACE,
            fg=TEXT_SECONDARY,
            font=small_font,
            anchor=tk.W,
        )
        canvas.create_window(lumina_card_left + 120, row_top + 120, window=lux_label, anchor=tk.NW)

        def refresh_lumina_status_labels() -> None:
            """
            @brief 定时刷新面板中的 Lumina 状态标签与显示器列表。
            @return None
            """

            try:
                if not win.winfo_exists():
                    return

                latest_status = get_lumina_status()
                latest_level_label = get_lumina_brightness_level_label()
                latest_connected = bool(getattr(latest_status, "connected", False))

                lumina_status_label.configure(
                    text=format_lumina_status_text(latest_status),
                    fg=ACCENT_COLOR if latest_connected else TEXT_SECONDARY,
                )
                orientation_status_label.configure(
                    text=format_lumina_orientation_text(latest_status)
                )
                lux_label.configure(
                    text=format_lumina_brightness_text(
                        latest_status,
                        latest_level_label,
                    )
                )

                try:
                    latest_monitor_rows = get_monitor_rows()
                except Exception:
                    latest_monitor_rows = monitor_rows

                if (
                    self._make_monitor_rows_signature(latest_monitor_rows)
                    != monitor_rows_signature
                ):
                    self.show_brightness_panel(
                        latest_monitor_rows,
                        get_monitor_rows,
                        enqueue_brightness_change,
                        is_auto_dim_active,
                        toggle_auto_dim,
                        get_idle_delay_seconds,
                        update_idle_delay_seconds,
                        is_autostart_active,
                        toggle_autostart,
                        lumina_config,
                        latest_status,
                        latest_level_label,
                        get_lumina_status,
                        get_lumina_brightness_level_label,
                        lumina_display_choices,
                        update_lumina_config,
                    )
                    return

                win.after(1000, refresh_lumina_status_labels)
            except tk.TclError:
                return

        win.after(1000, refresh_lumina_status_labels)

        tooltip_rect = canvas.create_rectangle(
            0,
            0,
            0,
            0,
            fill="#343d4b",
            outline=PANEL_BORDER,
            state=tk.HIDDEN,
        )
        tooltip_label = canvas.create_text(
            0,
            0,
            text="",
            fill=TEXT_PRIMARY,
            font=tkfont.Font(family="Microsoft YaHei UI", size=9),
            state=tk.HIDDEN,
        )

        def show_tooltip(
            tooltip_text: str,
            center_x: int,
            center_y: int,
        ) -> None:
            """
            @brief 显示图案按钮或档位标签的功能提示。
            @param tooltip_text 提示文本。
            @param center_x 提示文本中心横坐标。
            @param center_y 提示文本中心纵坐标。
            @return None
            """

            canvas.itemconfigure(tooltip_label, text=tooltip_text, state=tk.NORMAL)
            canvas.coords(tooltip_label, center_x, center_y)
            text_bounds = canvas.bbox(tooltip_label)

            if text_bounds is None:
                return

            left, top, right, bottom = text_bounds
            canvas.coords(
                tooltip_rect,
                left - 8,
                top - 5,
                right + 8,
                bottom + 5,
            )
            canvas.itemconfigure(tooltip_rect, state=tk.NORMAL)
            canvas.tag_raise(tooltip_rect)
            canvas.tag_raise(tooltip_label)

        def hide_tooltip() -> None:
            """
            @brief 隐藏图案按钮或档位标签的功能提示。
            @return None
            """

            canvas.itemconfigure(tooltip_rect, state=tk.HIDDEN)
            canvas.itemconfigure(tooltip_label, state=tk.HIDDEN)

        brightness_title = tk.Label(
            win,
            text="显示屏亮度",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=row_title_font,
            anchor=tk.W,
        )
        canvas.create_window(
            brightness_card_left + 20,
            row_top + 14,
            window=brightness_title,
            anchor=tk.NW,
        )

        monitor_row_top = row_top + brightness_card_header_height
        monitor_label_width = 28
        monitor_scale_length = 260

        if not monitor_rows:
            empty_monitor_label = tk.Label(
                win,
                text="未检测到可调亮度显示器",
                bg=PANEL_SURFACE,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
            )
            canvas.create_window(
                brightness_card_left + 20,
                monitor_row_top + 10,
                window=empty_monitor_label,
                anchor=tk.NW,
            )

        for monitor_index, description_text, current_percentage in monitor_rows:
            header = f"[{monitor_index}] {description_text}"
            monitor_label = tk.Label(
                win,
                text=header,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                font=row_title_font,
                width=monitor_label_width,
                anchor=tk.W,
            )
            canvas.create_window(
                brightness_card_left + 20,
                monitor_row_top + 10,
                window=monitor_label,
                anchor=tk.NW,
            )

            value_label = tk.Label(
                win,
                text=f"{current_percentage}%",
                bg=PANEL_SURFACE,
                fg=ACCENT_COLOR,
                font=value_font,
                width=5,
                anchor=tk.E,
            )
            canvas.create_window(
                brightness_card_right - 72,
                monitor_row_top + 10,
                window=value_label,
                anchor=tk.NW,
            )

            brightness_scale = tk.Scale(
                win,
                from_=0,
                to=100,
                orient=tk.HORIZONTAL,
                length=monitor_scale_length,
                tickinterval=0,
                resolution=1,
                showvalue=False,
                bd=0,
                highlightthickness=0,
                sliderlength=18,
                width=12,
                bg=PANEL_SURFACE,
                fg=TEXT_PRIMARY,
                troughcolor="#151922",
                activebackground=ACCENT_COLOR,
            )
            brightness_scale.set(current_percentage)
            self._last_sent_values[monitor_index] = current_percentage
            brightness_scale.configure(
                command=make_scale_callback(monitor_index, value_label)
            )
            scale_window = canvas.create_window(
                brightness_card_left + 20,
                monitor_row_top + 38,
                window=brightness_scale,
                anchor=tk.NW,
            )
            monitor_scale_windows[monitor_index] = scale_window
            monitor_row_top += row_step

        refresh_monitor_scale_visibility()

        level_card_title = tk.Label(
            win,
            text="亮度档位",
            bg=PANEL_SURFACE,
            fg=TEXT_PRIMARY,
            font=row_title_font,
            anchor=tk.W,
        )
        canvas.create_window(
            lumina_card_left + 20,
            row_top + 154,
            window=level_card_title,
            anchor=tk.NW,
        )
        level_labels = ["0档", "1档", "2档", "3档", "4档"]
        level_label_y = row_top + 182
        level_entry_y = row_top + 204
        level_column_width = 68

        for level_index, label_text in enumerate(level_labels):
            label_x = lumina_card_left + 20 + level_index * level_column_width
            level_label = tk.Label(
                win,
                text=label_text,
                bg=PANEL_SURFACE,
                fg=TEXT_SECONDARY,
                font=small_font,
                anchor=tk.W,
                cursor="hand2",
            )
            canvas.create_window(
                label_x,
                level_label_y,
                window=level_label,
                anchor=tk.NW,
            )
            level_label.bind(
                "<Enter>",
                lambda event, target_index=level_index: show_tooltip(
                    format_panel_level_range(brightness_levels[target_index]),
                    event.x_root - win.winfo_rootx() + 52,
                    level_entry_y + 34,
                ),
            )
            level_label.bind("<Leave>", lambda _event: hide_tooltip())
            level_label.bind("<Button-1>", lambda _event: open_range_editor())

            level_entry = tk.Entry(
                win,
                textvariable=brightness_level_vars[level_index],
                width=5,
                bg="#151922",
                fg=TEXT_PRIMARY,
                insertbackground=TEXT_PRIMARY,
                justify=tk.CENTER,
                font=small_font,
                bd=0,
                highlightthickness=0,
            )
            configure_panel_entry_focus(level_entry)
            level_entry.bind(
                "<KeyRelease>",
                lambda _event: submit_lumina_config_later(),
            )
            level_entry.bind(
                "<FocusOut>",
                lambda _event: submit_lumina_config_now(),
            )
            level_entry.bind(
                "<Return>",
                lambda _event: submit_lumina_config_now(),
            )
            canvas.create_window(
                label_x,
                level_entry_y,
                window=level_entry,
                anchor=tk.NW,
            )

        bottom_center_y = panel_height - 58

        def bind_icon_button(
            item_ids: list[int],
            set_hovered: Callable[[bool], None],
            on_clicked: Callable[[], None],
            tooltip_text: str,
            tooltip_center_x: int,
        ) -> None:
            """
            @brief 为一组 Canvas 图形对象绑定按钮事件。
            @param item_ids 组成按钮的 Canvas 图形对象标识列表。
            @param set_hovered 设置悬停样式的回调。
            @param on_clicked 点击按钮时执行的回调。
            @param tooltip_text 鼠标悬停时显示的提示文本。
            @param tooltip_center_x 提示文本的水平中心坐标。
            @return None
            """

            def on_button_enter(event: tk.Event) -> None:
                """
                @brief 处理按钮鼠标进入事件，显示悬停样式和提示。
                @param event Tk 鼠标事件。
                @return None
                """

                del event
                set_hovered(True)
                show_tooltip(
                    tooltip_text,
                    tooltip_center_x,
                    bottom_center_y - 44,
                )

            def on_button_leave(event: tk.Event) -> None:
                """
                @brief 处理按钮鼠标离开事件，隐藏悬停样式和提示。
                @param event Tk 鼠标事件。
                @return None
                """

                del event
                set_hovered(False)
                hide_tooltip()

            for item_id in item_ids:
                canvas.tag_bind(item_id, "<Button-1>", lambda _event: on_clicked())
                canvas.tag_bind(item_id, "<Enter>", on_button_enter)
                canvas.tag_bind(item_id, "<Leave>", on_button_leave)

        def create_button_circle(
            center_x: int,
            center_y: int,
        ) -> int:
            """
            @brief 绘制底部图案按钮的圆形底座。
            @param center_x 圆心横坐标。
            @param center_y 圆心纵坐标。
            @return int Canvas 圆形对象标识。
            """

            return canvas.create_oval(
                center_x - bottom_button_radius,
                center_y - bottom_button_radius,
                center_x + bottom_button_radius,
                center_y + bottom_button_radius,
                fill="#2a313d",
                outline=PANEL_BORDER,
                width=1,
            )

        def set_button_hovered(
            circle_id: int,
            icon_ids: list[int],
            icon_color: str,
            is_hovered: bool,
        ) -> None:
            """
            @brief 切换底部图案按钮悬停样式。
            @param circle_id 圆形底座对象标识。
            @param icon_ids 图案线条对象标识列表。
            @param icon_color 非悬停状态下的图案颜色。
            @param is_hovered 是否处于悬停状态。
            @return None
            """

            def configure_icon_color(
                item_id: int,
                target_color: str,
            ) -> None:
                """
                @brief 兼容不同 Canvas 图形对象的颜色属性。
                @param item_id Canvas 图形对象标识。
                @param target_color 目标颜色。
                @return None
                """

                try:
                    canvas.itemconfigure(item_id, fill=target_color)
                except tk.TclError:
                    pass

                try:
                    canvas.itemconfigure(item_id, outline=target_color)
                except tk.TclError:
                    pass

            if is_hovered:
                canvas.configure(cursor="hand2")
                canvas.itemconfigure(circle_id, fill="#343d4b")

                for icon_id in icon_ids:
                    configure_icon_color(icon_id, "#ffffff")

                if circle_id == auto_circle and len(icon_ids) > 1:
                    canvas.itemconfigure(
                        icon_ids[1],
                        fill="#343d4b",
                        outline="#343d4b",
                    )

                return

            canvas.configure(cursor="")
            canvas.itemconfigure(circle_id, fill="#2a313d")

            for icon_id in icon_ids:
                configure_icon_color(icon_id, icon_color)

            if circle_id == auto_circle and len(icon_ids) > 1:
                canvas.itemconfigure(
                    icon_ids[1],
                    fill="#2a313d",
                    outline="#2a313d",
                )

        auto_center_x = panel_width // 2 - 66
        close_center_x = panel_width // 2
        autostart_center_x = panel_width // 2 + 66
        idle_delay_entry_x = auto_center_x - bottom_button_radius - 42
        auto_icon_color = ACCENT_COLOR if is_auto_dim_active() else TEXT_SECONDARY

        auto_circle = create_button_circle(auto_center_x, bottom_center_y)
        auto_icon_ids = [
            canvas.create_oval(
                auto_center_x - 9,
                bottom_center_y - 10,
                auto_center_x + 9,
                bottom_center_y + 10,
                outline=auto_icon_color,
                fill=auto_icon_color,
                width=2,
            ),
            canvas.create_oval(
                auto_center_x - 2,
                bottom_center_y - 12,
                auto_center_x + 13,
                bottom_center_y + 7,
                outline="#2a313d",
                fill="#2a313d",
                width=2,
            ),
        ]

        close_circle = create_button_circle(close_center_x, bottom_center_y)
        close_icon_ids = [
            canvas.create_line(
                close_center_x - 7,
                bottom_center_y - 7,
                close_center_x + 7,
                bottom_center_y + 7,
                fill=TEXT_SECONDARY,
                width=2,
                capstyle=tk.ROUND,
            ),
            canvas.create_line(
                close_center_x + 7,
                bottom_center_y - 7,
                close_center_x - 7,
                bottom_center_y + 7,
                fill=TEXT_SECONDARY,
                width=2,
                capstyle=tk.ROUND,
            ),
        ]

        autostart_circle = create_button_circle(autostart_center_x, bottom_center_y)
        autostart_color = ACCENT_COLOR if is_autostart_active() else TEXT_SECONDARY
        autostart_icon_ids = [
            canvas.create_line(
                autostart_center_x - 5,
                bottom_center_y - 8,
                autostart_center_x + 11,
                bottom_center_y,
                autostart_center_x - 5,
                bottom_center_y + 8,
                autostart_center_x - 5,
                bottom_center_y - 8,
                fill=autostart_color,
                width=2,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            ),
        ]

        def update_auto_button_state(is_active: bool) -> None:
            """
            @brief 根据自动调光启用状态刷新月亮图案颜色。
            @param is_active 自动调光是否启用。
            @return None
            """

            icon_color = ACCENT_COLOR if is_active else TEXT_SECONDARY

            for icon_index, icon_id in enumerate(auto_icon_ids):
                if icon_index == 1:
                    canvas.itemconfigure(
                        icon_id,
                        fill="#2a313d",
                        outline="#2a313d",
                    )
                    continue

                try:
                    canvas.itemconfigure(icon_id, fill=icon_color)
                except tk.TclError:
                    pass

                try:
                    canvas.itemconfigure(icon_id, outline=icon_color)
                except tk.TclError:
                    pass

        def update_autostart_button_state(is_active: bool) -> None:
            """
            @brief 根据自启动启用状态刷新三角形图案颜色。
            @param is_active 自启动是否启用。
            @return None
            """

            icon_color = ACCENT_COLOR if is_active else TEXT_SECONDARY

            for icon_id in autostart_icon_ids:
                try:
                    canvas.itemconfigure(icon_id, fill=icon_color)
                except tk.TclError:
                    pass

                try:
                    canvas.itemconfigure(icon_id, outline=icon_color)
                except tk.TclError:
                    pass

        def on_auto_button_clicked() -> None:
            """
            @brief 切换自动调光状态并刷新左侧图案按钮。
            @return None
            """

            update_auto_button_state(toggle_auto_dim())

        def on_autostart_button_clicked() -> None:
            """
            @brief 切换自启动状态并刷新右侧图案按钮。
            @return None
            """

            update_autostart_button_state(toggle_autostart())

        idle_delay_entry = tk.Entry(
            win,
            textvariable=idle_delay_var,
            width=4,
            bg="#151922",
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            justify=tk.CENTER,
            font=small_font,
            bd=0,
            highlightthickness=0,
        )
        configure_panel_entry_focus(idle_delay_entry)
        idle_delay_entry.bind(
            "<KeyRelease>",
            lambda _event: submit_idle_delay_later(),
        )
        idle_delay_entry.bind(
            "<FocusOut>",
            lambda _event: submit_idle_delay_now(),
        )
        idle_delay_entry.bind(
            "<Return>",
            lambda _event: submit_idle_delay_now(),
        )
        idle_delay_entry.bind(
            "<Enter>",
            lambda _event: show_tooltip(
                "空闲时间阈值（秒）",
                idle_delay_entry_x + 16,
                bottom_center_y - 44,
            ),
        )
        idle_delay_entry.bind("<Leave>", lambda _event: hide_tooltip())
        canvas.create_window(
            idle_delay_entry_x,
            bottom_center_y,
            window=idle_delay_entry,
            anchor=tk.W,
        )

        lumina_status_label = tk.Label(
            win,
            text=format_lumina_status_text(lumina_status),
            bg=PANEL_BACKGROUND,
            fg=ACCENT_COLOR if getattr(lumina_status, "connected", False) else TEXT_SECONDARY,
            font=small_font,
            anchor=tk.CENTER,
        )
        canvas.create_window(
            content_right - 6,
            panel_height - 26,
            window=lumina_status_label,
            anchor=tk.SE,
        )

        author_text_id = canvas.create_text(
            content_left + 6,
            panel_height - 26,
            text="化学制品 | 1.1",
            fill=TEXT_SECONDARY,
            font=small_font,
            anchor=tk.SW,
        )

        def on_author_enter(event: tk.Event) -> None:
            """
            @brief 处理底部作者文字鼠标进入事件。
            @param event Tk 鼠标事件。
            @return None
            """

            del event
            canvas.configure(cursor="hand2")
            show_tooltip(
                "1324146673@qq.com",
                content_left + 74,
                bottom_center_y - 44,
            )

        def on_author_leave(event: tk.Event) -> None:
            """
            @brief 处理底部作者文字鼠标离开事件。
            @param event Tk 鼠标事件。
            @return None
            """

            del event
            canvas.configure(cursor="")
            hide_tooltip()

        canvas.tag_bind(author_text_id, "<Enter>", on_author_enter)
        canvas.tag_bind(author_text_id, "<Leave>", on_author_leave)

        bind_icon_button(
            [auto_circle] + auto_icon_ids,
            lambda is_hovered: set_button_hovered(
                auto_circle,
                auto_icon_ids,
                ACCENT_COLOR if is_auto_dim_active() else TEXT_SECONDARY,
                is_hovered,
            ),
            on_auto_button_clicked,
            "启用/暂停自动暗屏",
            auto_center_x,
        )
        bind_icon_button(
            [close_circle] + close_icon_ids,
            lambda is_hovered: set_button_hovered(
                close_circle,
                close_icon_ids,
                TEXT_SECONDARY,
                is_hovered,
            ),
            win.destroy,
            "关闭面板",
            close_center_x,
        )
        bind_icon_button(
            [autostart_circle] + autostart_icon_ids,
            lambda is_hovered: set_button_hovered(
                autostart_circle,
                autostart_icon_ids,
                ACCENT_COLOR if is_autostart_active() else TEXT_SECONDARY,
                is_hovered,
            ),
            on_autostart_button_clicked,
            "开启/关闭自启动",
            autostart_center_x,
        )

        self._bind_window_drag(win, canvas)

        win.update_idletasks()
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        position_x, position_y = self._get_panel_position(
            screen_width,
            screen_height,
            panel_width,
            panel_height,
        )
        win.geometry(f"{panel_width}x{panel_height}+{position_x}+{position_y}")
        self._panel_position = (
            position_x,
            position_y,
        )
        win.after(200, lambda: win.attributes("-topmost", False))
        enable_window_acrylic(int(win.winfo_id()))

    def _make_monitor_rows_signature(
        self,
        monitor_rows: list[tuple[int, str, int]],
    ) -> tuple[tuple[int, str], ...]:
        """
        @brief 生成显示器亮度行签名。
        @param monitor_rows 每行依次为显示器索引、描述文本、当前亮度百分比。
        @return tuple[tuple[int, str], ...] 可比较的显示器列表签名。
        """

        return tuple(
            (
                monitor_index,
                description_text,
            )
            for monitor_index, description_text, current_percentage in monitor_rows
        )

    def _make_lumina_snapshot_signature(
        self,
        lumina_snapshots: list[object],
    ) -> tuple[tuple[str, str], ...]:
        """
        @brief 生成 Lumina 设备快照签名。
        @param lumina_snapshots Lumina 设备快照列表。
        @return tuple[tuple[str, str], ...] 可比较的设备列表签名。
        @note 仅包含影响面板布局的字段，避免绑定等普通交互触发窗口重建。
        """

        signature_items: list[tuple[str, str]] = []

        for snapshot in lumina_snapshots:
            config = getattr(snapshot, "config", None)

            if config is None:
                continue

            signature_items.append(
                (
                    str(getattr(config, "device_key", "")),
                    str(getattr(config, "label", "")),
                )
            )

        return tuple(signature_items)

    def _remember_panel_position(
        self,
        window: tk.Toplevel,
    ) -> None:
        """
        @brief 记录主面板当前窗口位置。
        @param window 主面板顶层窗口。
        @return None
        @note 配置变更会重建面板，记录位置用于避免重建后回到初始居中位置。
        """

        try:
            window.update_idletasks()
            self._panel_position = (
                int(window.winfo_x()),
                int(window.winfo_y()),
            )
        except tk.TclError:
            return

    def _get_panel_position(
        self,
        screen_width: int,
        screen_height: int,
        panel_width: int,
        panel_height: int,
    ) -> tuple[int, int]:
        """
        @brief 获取主面板可用显示位置。
        @param screen_width 当前屏幕宽度。
        @param screen_height 当前屏幕高度。
        @param panel_width 主面板宽度。
        @param panel_height 主面板高度。
        @return tuple[int, int] 主面板左上角坐标。
        @note 若已有拖动位置，则复用并限制在屏幕范围内；否则使用屏幕居中位置。
        """

        if self._panel_position is None:
            position_x = (screen_width - panel_width) // 2
            position_y = (screen_height - panel_height) // 2
        else:
            position_x, position_y = self._panel_position

        max_position_x = max(0, screen_width - panel_width)
        max_position_y = max(0, screen_height - panel_height)
        position_x = max(0, min(max_position_x, int(position_x)))
        position_y = max(0, min(max_position_y, int(position_y)))

        return (
            position_x,
            position_y,
        )

    def _bind_window_drag(
        self,
        window: tk.Toplevel,
        widget: tk.Widget,
    ) -> None:
        """
        @brief 为无边框窗口绑定鼠标拖拽移动行为。
        @param window 需要移动的顶层窗口。
        @param widget 接收拖拽事件的控件。
        @return None
        """

        def on_drag_start(event: tk.Event) -> None:
            """
            @brief 记录窗口拖拽开始时的鼠标偏移。
            @param event Tk 鼠标事件。
            @return None
            """

            self._drag_start_x = event.x_root - window.winfo_x()
            self._drag_start_y = event.y_root - window.winfo_y()

        def on_drag_motion(event: tk.Event) -> None:
            """
            @brief 根据当前鼠标位置移动无边框窗口。
            @param event Tk 鼠标事件。
            @return None
            """

            next_x = event.x_root - self._drag_start_x
            next_y = event.y_root - self._drag_start_y
            window.geometry(f"+{next_x}+{next_y}")
            self._panel_position = (
                int(next_x),
                int(next_y),
            )

        widget.bind("<ButtonPress-1>", on_drag_start)
        widget.bind("<B1-Motion>", on_drag_motion)
