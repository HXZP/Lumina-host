# -*- coding: utf-8 -*-
"""
@brief 为 Lumina 发布目录生成用户使用说明。
@note 生成 readme.txt、README.md、README.pdf 和配套示意图。
"""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


BASE_DIRECTORY = Path(__file__).resolve().parent.parent
RELEASE_DIRECTORY = BASE_DIRECTORY / "dist_release" / "Lumina"
IMAGE_DIRECTORY = RELEASE_DIRECTORY / "manual_images"
TEXT_README_PATH = RELEASE_DIRECTORY / "readme.txt"
MARKDOWN_README_PATH = RELEASE_DIRECTORY / "README.md"
PDF_README_PATH = RELEASE_DIRECTORY / "README.pdf"
FONT_REGULAR_PATH = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD_PATH = Path("C:/Windows/Fonts/msyhbd.ttc")

DOCUMENT_SECTIONS = [
    (
        "1. 启动",
        [
            "保留整个 Lumina 文件夹，不要只复制 Lumina.exe。",
            "双击 Lumina.exe 启动，启动后在 Windows 系统托盘显示 Lumina 图标。",
            "点击托盘图标，或右键托盘图标选择“亮度调节”，打开控制面板。",
        ],
    ),
    (
        "2. 控制面板",
        [
            "上方是 Lumina 设备卡，下方是显示器亮度区。",
            "面板配置会自动保存，不需要点击保存按钮。",
            "右下角显示当前已连接的 Lumina 数量。",
        ],
    ),
    (
        "3. 自动旋转",
        [
            "在设备卡中选择自动旋转目标显示器。",
            "显示器坐标轴以正对屏幕为准：左到右是 X+，下到上是 Y+。",
            "Lumina 外壳边缘有坐标轴丝印，设置方向时可以直接对照丝印。",
            "设置“屏幕X+”和“屏幕Y+”，把显示器方向绑定到 Lumina 当前安装后的机身方向。",
            "勾选“自动旋转”。旋转设备或显示器后，屏幕方向会按配置切换。",
        ],
    ),
    (
        "4. 自动亮度",
        [
            "在设备卡中勾选“自动亮度”。",
            "设置 0 档到 4 档亮度百分比；点击档位名称可调整 lux 分界点。",
            "在显示器亮度区，把目标显示器右侧下拉框选为对应 Lumina。",
            "选择“手动”时显示亮度滑杆，可直接拖动调节显示器亮度。",
        ],
    ),
    (
        "5. LED",
        [
            "设备卡右上角红色圆点用于关闭 LED。",
            "设备卡右上角白色圆点用于打开 LED。",
            "每次点击都会立即发送一次 LED 指令，并记住状态。",
            "锁屏、休眠或睡眠前会临时关闭 LED，解锁或恢复后按记忆状态恢复。",
        ],
    ),
    (
        "6. 自动暗屏和自启动",
        [
            "底部左侧输入框设置自动暗屏空闲时间，单位为秒。",
            "月亮按钮启用或暂停自动暗屏。",
            "中间按钮关闭控制面板。",
            "右侧三角按钮开启或关闭 Windows 开机自启动。",
        ],
    ),
    (
        "7. 常见问题",
        [
            "无法调节亮度：确认显示器支持并开启 DDC/CI，尽量减少扩展坞和转接线影响。",
            "自动旋转方向不对：重新检查“屏幕X+”和“屏幕Y+”是否与设备安装方向一致。",
            "LED 点击无反应：确认设备固件支持 LED 控制，重新插拔 Lumina 后再试。",
            "程序无法覆盖更新：先退出 Lumina.exe，并关闭打开在 Lumina 文件夹中的资源管理器窗口。",
        ],
    ),
]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    @brief 加载用于生成图片和 PDF 的中文字体。
    @param size 字体大小。
    @param bold 为 True 时优先加载粗体字体。
    @return ImageFont.FreeTypeFont 加载后的字体对象。
    """

    font_path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH

    if not font_path.exists():
        font_path = FONT_REGULAR_PATH

    return ImageFont.truetype(str(font_path), size=size)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    width: int,
) -> None:
    """
    @brief 绘制带箭头的线段。
    @param draw Pillow 绘图对象。
    @param start 起点坐标。
    @param end 终点坐标。
    @param color 箭头颜色。
    @param width 线宽。
    @return None
    """

    draw.line(
        [start, end],
        fill=color,
        width=width,
    )

    x1, y1 = start
    x2, y2 = end

    if abs(x2 - x1) >= abs(y2 - y1):
        points = [
            (x2, y2),
            (x2 - 22, y2 - 13),
            (x2 - 22, y2 + 13),
        ]
    else:
        points = [
            (x2, y2),
            (x2 - 13, y2 + 22),
            (x2 + 13, y2 + 22),
        ]

    draw.polygon(
        points,
        fill=color,
    )


def draw_coordinate_image(output_path: Path) -> None:
    """
    @brief 绘制显示器坐标轴示意图。
    @param output_path 输出图片路径。
    @return None
    """

    image = Image.new(
        "RGB",
        (1200, 680),
        "#f7f9fc",
    )
    draw = ImageDraw.Draw(image)
    title_font = load_font(34, True)
    text_font = load_font(24)
    small_font = load_font(20)
    label_font = load_font(42, True)

    draw.text(
        (600, 48),
        "显示器坐标轴",
        fill="#202630",
        font=title_font,
        anchor="mm",
    )

    draw.rounded_rectangle(
        (110, 110, 720, 500),
        radius=26,
        fill="#202630",
    )
    draw.rounded_rectangle(
        (145, 145, 685, 450),
        radius=12,
        fill="#dcecf4",
    )
    draw.rectangle(
        (355, 500, 475, 555),
        fill="#2b3340",
    )
    draw.polygon(
        [(275, 590), (555, 590), (510, 552), (320, 552)],
        fill="#3a4452",
    )

    origin = (220, 370)
    draw_arrow(
        draw,
        origin,
        (610, 370),
        (15, 159, 179),
        10,
    )
    draw_arrow(
        draw,
        origin,
        (220, 185),
        (240, 163, 24),
        10,
    )
    draw.ellipse(
        (209, 359, 231, 381),
        fill="#202630",
    )
    draw.text(
        (635, 370),
        "X+",
        fill="#0f9fb3",
        font=label_font,
        anchor="lm",
    )
    draw.text(
        (220, 160),
        "Y+",
        fill="#f0a318",
        font=label_font,
        anchor="mm",
    )
    draw.text(
        (415, 410),
        "横向：左 → 右",
        fill="#2b3340",
        font=text_font,
        anchor="mm",
    )
    draw.text(
        (142, 276),
        "纵向：下 → 上",
        fill="#2b3340",
        font=text_font,
        anchor="mm",
    )

    draw.rounded_rectangle(
        (790, 128, 1088, 486),
        radius=22,
        fill="#252b35",
    )
    draw.text(
        (822, 172),
        "设备卡设置",
        fill="#f4f7fb",
        font=title_font,
        anchor="lm",
    )
    draw.text(
        (828, 240),
        "屏幕X+",
        fill="#aab4c3",
        font=text_font,
        anchor="lm",
    )
    draw.rounded_rectangle(
        (940, 216, 1046, 262),
        radius=8,
        fill="#151922",
        outline="#3a4352",
        width=2,
    )
    draw.text(
        (993, 239),
        "Y+",
        fill="#ffffff",
        font=text_font,
        anchor="mm",
    )
    draw.text(
        (828, 312),
        "屏幕Y+",
        fill="#aab4c3",
        font=text_font,
        anchor="lm",
    )
    draw.rounded_rectangle(
        (940, 288, 1046, 334),
        radius=8,
        fill="#151922",
        outline="#3a4352",
        width=2,
    )
    draw.text(
        (993, 311),
        "Z+",
        fill="#ffffff",
        font=text_font,
        anchor="mm",
    )
    draw.text(
        (828, 390),
        "含义：把显示器方向绑定到",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )
    draw.text(
        (828, 424),
        "Lumina 当前机身方向",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )

    draw.rounded_rectangle(
        (160, 620, 1040, 660),
        radius=20,
        fill="#e8eef5",
    )
    draw.text(
        (600, 640),
        "屏幕X+ = 左到右；屏幕Y+ = 下到上",
        fill="#202630",
        font=text_font,
        anchor="mm",
    )
    image.save(output_path)


def draw_panel_image(output_path: Path) -> None:
    """
    @brief 绘制 Lumina 控制面板功能示意图。
    @param output_path 输出图片路径。
    @return None
    """

    image = Image.new(
        "RGB",
        (1200, 720),
        "#f7f9fc",
    )
    draw = ImageDraw.Draw(image)
    title_font = load_font(34, True)
    text_font = load_font(22)
    small_font = load_font(18)

    draw.text(
        (600, 48),
        "Lumina 控制面板",
        fill="#202630",
        font=title_font,
        anchor="mm",
    )

    draw.rounded_rectangle(
        (105, 95, 1095, 655),
        radius=28,
        fill="#1f232b",
    )

    draw.rounded_rectangle(
        (145, 135, 520, 430),
        radius=18,
        fill="#252b35",
        outline="#3a4352",
        width=2,
    )
    draw.text(
        (175, 172),
        "Lumina #1",
        fill="#f4f7fb",
        font=text_font,
        anchor="lm",
    )
    draw.ellipse(
        (442, 158, 462, 178),
        fill="#f05252",
        outline="#3a4352",
        width=3,
    )
    draw.ellipse(
        (478, 158, 498, 178),
        fill="#ffffff",
        outline="#ffc43d",
        width=3,
    )
    draw.text(
        (175, 225),
        "自动旋转  当前: X+",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )
    draw.rounded_rectangle(
        (175, 254, 470, 294),
        radius=8,
        fill="#151922",
        outline="#3a4352",
    )
    draw.text(
        (195, 274),
        "显示器 [1]",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )
    draw.text(
        (175, 330),
        "屏幕X+  Y+     屏幕Y+  Z+",
        fill="#aab4c3",
        font=small_font,
        anchor="lm",
    )
    draw.text(
        (175, 378),
        "自动亮度   0档 1档 2档 3档 4档",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )

    draw.rounded_rectangle(
        (560, 135, 1055, 430),
        radius=18,
        fill="#252b35",
        outline="#3a4352",
        width=2,
    )
    draw.text(
        (590, 172),
        "显示器亮度",
        fill="#f4f7fb",
        font=text_font,
        anchor="lm",
    )
    draw.text(
        (590, 230),
        "[1] 主显示器",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )
    draw.line(
        (590, 285, 850, 285),
        fill="#151922",
        width=12,
    )
    draw.ellipse(
        (715, 270, 745, 300),
        fill="#ffc43d",
    )
    draw.rounded_rectangle(
        (890, 252, 1010, 292),
        radius=8,
        fill="#151922",
        outline="#3a4352",
    )
    draw.text(
        (950, 272),
        "手动",
        fill="#f4f7fb",
        font=small_font,
        anchor="mm",
    )
    draw.text(
        (590, 350),
        "选 Lumina：自动亮度接管",
        fill="#aab4c3",
        font=small_font,
        anchor="lm",
    )

    draw.rounded_rectangle(
        (145, 480, 1055, 612),
        radius=18,
        fill="#252b35",
        outline="#3a4352",
        width=2,
    )
    draw.text(
        (180, 525),
        "底部：空闲秒数输入框  |  月亮=自动暗屏  |  ×=关闭面板  |  三角=自启动",
        fill="#f4f7fb",
        font=small_font,
        anchor="lm",
    )
    draw.text(
        (180, 568),
        "配置自动保存；鼠标悬停可查看提示。",
        fill="#aab4c3",
        font=small_font,
        anchor="lm",
    )
    image.save(output_path)


def build_markdown_text() -> str:
    """
    @brief 生成发布版 Markdown 说明。
    @return str Markdown 文本。
    """

    lines = [
        "# Lumina 使用说明",
        "",
        "![Lumina 控制面板](manual_images/panel-guide.png)",
        "",
    ]

    for title, items in DOCUMENT_SECTIONS:
        lines.append(f"## {title}")
        lines.append("")

        if title.startswith("3."):
            lines.append("![显示器坐标轴](manual_images/display-coordinate-axis.png)")
            lines.append("")

        for item in items:
            lines.append(f"- {item}")

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_text_readme() -> str:
    """
    @brief 生成发布版纯文本说明。
    @return str 纯文本说明。
    """

    lines = [
        "Lumina 使用说明",
        "================",
        "",
    ]

    for title, items in DOCUMENT_SECTIONS:
        lines.append(title)
        lines.append("-" * len(title))

        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {item}")

        lines.append("")

    lines.append("图片版说明请打开 README.md 或 README.pdf。")
    lines.append("")
    return "\n".join(lines)


def wrap_text_by_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """
    @brief 按像素宽度折行文本。
    @param draw Pillow 绘图对象。
    @param text 待折行文本。
    @param font 文本字体。
    @param max_width 最大行宽。
    @return list[str] 折行后的文本列表。
    """

    result: list[str] = []
    current = ""

    for char in text:
        next_text = current + char
        bounds = draw.textbbox(
            (0, 0),
            next_text,
            font=font,
        )

        if bounds[2] - bounds[0] <= max_width:
            current = next_text
            continue

        if current:
            result.append(current)

        current = char

    if current:
        result.append(current)

    if not result:
        result = wrap(
            text,
            width=34,
        )

    return result


def create_pdf_pages() -> list[Image.Image]:
    """
    @brief 创建 PDF 每页图像。
    @return list[Image.Image] PDF 页面图像列表。
    """

    page_width = 1240
    page_height = 1754
    margin = 86
    body_width = page_width - margin * 2
    title_font = load_font(44, True)
    section_font = load_font(30, True)
    body_font = load_font(24)
    small_font = load_font(20)
    pages: list[Image.Image] = []

    def new_page() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
        """
        @brief 创建新的 PDF 页面图像。
        @return tuple[Image.Image, ImageDraw.ImageDraw, int] 页面、绘图对象和当前 y 坐标。
        """

        page = Image.new(
            "RGB",
            (page_width, page_height),
            "#ffffff",
        )
        page_draw = ImageDraw.Draw(page)
        return (
            page,
            page_draw,
            margin,
        )

    page, draw, y = new_page()
    draw.text(
        (margin, y),
        "Lumina 使用说明",
        fill="#202630",
        font=title_font,
        anchor="la",
    )
    y += 74

    panel_image = Image.open(IMAGE_DIRECTORY / "panel-guide.png").convert("RGB")
    panel_image.thumbnail(
        (body_width, 440),
        Image.Resampling.LANCZOS,
    )
    page.paste(
        panel_image,
        (margin, y),
    )
    y += panel_image.height + 40

    for title, items in DOCUMENT_SECTIONS:
        needed_height = 62 + len(items) * 68

        if title.startswith("3."):
            needed_height += 360

        if y + needed_height > page_height - margin:
            pages.append(page)
            page, draw, y = new_page()

        draw.text(
            (margin, y),
            title,
            fill="#202630",
            font=section_font,
            anchor="la",
        )
        y += 48

        if title.startswith("3."):
            coordinate_image = Image.open(
                IMAGE_DIRECTORY / "display-coordinate-axis.png"
            ).convert("RGB")
            coordinate_image.thumbnail(
                (body_width, 330),
                Image.Resampling.LANCZOS,
            )
            page.paste(
                coordinate_image,
                (margin, y),
            )
            y += coordinate_image.height + 24

        for item in items:
            wrapped_lines = wrap_text_by_width(
                draw,
                item,
                body_font,
                body_width - 40,
            )
            draw.text(
                (margin, y),
                "•",
                fill="#0f9fb3",
                font=body_font,
                anchor="la",
            )

            for line_index, line in enumerate(wrapped_lines):
                draw.text(
                    (margin + 34, y + line_index * 34),
                    line,
                    fill="#2b3340",
                    font=body_font,
                    anchor="la",
                )

            y += max(44, len(wrapped_lines) * 34 + 16)

        y += 18

    draw.text(
        (margin, page_height - 54),
        "Lumina",
        fill="#aab4c3",
        font=small_font,
        anchor="la",
    )
    pages.append(page)
    return pages


def write_pdf() -> None:
    """
    @brief 写入发布版 PDF 说明。
    @return None
    """

    pages = create_pdf_pages()
    first_page = pages[0]
    rest_pages = pages[1:]
    first_page.save(
        PDF_README_PATH,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=rest_pages,
    )


def main() -> None:
    """
    @brief 生成发布目录中的用户说明文件。
    @return None
    """

    RELEASE_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    IMAGE_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    draw_panel_image(IMAGE_DIRECTORY / "panel-guide.png")
    draw_coordinate_image(IMAGE_DIRECTORY / "display-coordinate-axis.png")
    TEXT_README_PATH.write_text(
        build_text_readme(),
        encoding="utf-8-sig",
    )
    MARKDOWN_README_PATH.write_text(
        build_markdown_text(),
        encoding="utf-8",
    )
    write_pdf()
    print(f"README written: {TEXT_README_PATH}")
    print(f"Markdown written: {MARKDOWN_README_PATH}")
    print(f"PDF written: {PDF_README_PATH}")


if __name__ == "__main__":
    main()
