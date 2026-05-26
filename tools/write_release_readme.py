# -*- coding: utf-8 -*-
"""
@brief 为打包后的 Lumina 发布目录生成中文说明文件。
@note 该脚本由 build_release.bat 在 PyInstaller 打包成功后调用。
"""

from __future__ import annotations

from pathlib import Path


release_directory = (
    Path(__file__).resolve().parent.parent / "dist_release" / "Lumina"
)
readme_file = release_directory / "readme.txt"

readme_text = """Lumina 使用说明
================

一、程序功能
------------
Lumina 是一个 Windows 自动调光工具。

它会根据每块屏幕上的窗口状态、鼠标位置和鼠标静止时间，自动调节支持 DDC/CI 或 WMI 的显示器亮度：

1. 某块屏幕没有普通窗口，并且鼠标不在该屏幕上时，满足延迟条件后进入暗光模式。
2. 某块屏幕没有普通窗口，但鼠标停留在该屏幕上时，如果鼠标连续静止达到延迟条件，也会进入暗光模式。
3. 当屏幕重新出现窗口、鼠标活动或手动恢复时，会恢复到记录的恢复亮度。
4. 可通过托盘面板手动调节每块显示器亮度。
5. 支持 Lumina 设备提供的自动亮度输入。

二、安装与启动
--------------
本程序是文件夹版打包结果。

请复制整个 Lumina 文件夹到目标电脑，不要只复制 Lumina.exe。
程序运行需要同目录下的 _internal 文件夹。

启动方式：
1. 打开 Lumina 文件夹。
2. 双击 Lumina.exe。
3. 程序启动后会显示在系统托盘区域。

三、托盘菜单
------------
右键系统托盘中的 Lumina 图标，可以使用以下功能：

1. 亮度调节：打开亮度调节面板。
2. 启用自动调光：开启或暂停自动调光。
3. 立即恢复亮度：立即把受控显示器恢复到记录的恢复亮度。
4. 开启自启动：将程序加入当前用户的 Windows 开机启动项。
5. 关闭自启动：移除开机启动项。
6. 退出：退出程序。

四、亮度调节面板
----------------
点击托盘图标或在托盘菜单中选择“亮度调节”可打开面板。

面板会根据当前受控显示器数量自动显示对应数量的亮度滑块，并纵向排列。
拖动滑块会立即设置对应显示器亮度。

底部三个图案按钮含义：

1. 左侧太阳图案：启用或暂停自动调光。
   黄色表示自动调光已启用，灰色表示已暂停。

2. 中间关闭图案：关闭亮度调节面板。

3. 右侧播放三角图案：开启或关闭 Windows 开机自启动。
   黄色表示自启动已开启，灰色表示未开启。

鼠标悬停在按钮上时，会显示对应功能提示。

五、自启动说明
--------------
开启自启动后，程序会写入当前用户的注册表启动项：

HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

如果移动了 Lumina 文件夹位置，请重新运行程序并重新开启自启动。

六、日志说明
------------
日志默认保存在：

Lumina\\logs\\lumina.log

如果程序所在目录没有写入权限，会自动回退到：

%LOCALAPPDATA%\\Lumina\\logs\\lumina.log

日志包含时间戳、日志等级、模块名、显示器识别结果、亮度读写操作、托盘操作、异常和兜底事件。
单个日志文件最大 20MB，超过后自动轮转并保留 5 个历史文件。

七、注意事项
------------
1. 外接显示器通常需要支持 DDC/CI 亮度控制，内置屏通常通过 Windows WMI 控制。
2. 很多外接显示器需要在显示器 OSD 菜单中开启 DDC/CI。
3. 部分特殊显示器可能无法通过本工具调节亮度。
4. 如果无法调节亮度，请检查显示器连接方式、DDC/CI 开关和显卡/显示器驱动。
5. 如果程序更新后图标仍显示旧样式，可能是 Windows 图标缓存导致，可重启资源管理器或重启电脑后再查看。
6. 如果打包或覆盖文件失败，请先退出正在运行的 Lumina.exe，并关闭打开在发布目录中的资源管理器窗口。
"""

release_directory.mkdir(parents=True, exist_ok=True)
readme_file.write_text(readme_text, encoding="utf-8")
print(f"README written: {readme_file}")
