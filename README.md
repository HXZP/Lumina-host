# Lumina-host

Lumina-host 是 Lumina 的 Windows 上位机程序。它负责读取 Lumina USB HID 设备的方向和环境光数据，并结合显示器亮度控制能力，实现自动旋转、自动亮度和自动暗屏。

## 功能

- 监听 Lumina HID 设备的姿态方向，用于自动旋转绑定显示器。
- 读取 Lumina 环境光 lux 数据，用于按档位自动设置显示器亮度。
- 支持多台 Lumina，每台 Lumina 可绑定不同显示器。
- 支持多显示器亮度控制，优先使用 DDC/CI，必要时使用 WMI。
- 提供系统托盘面板，用于手动调节亮度、配置绑定、配置档位和开关自启动。
- 支持打包为文件夹版 `Lumina.exe`。

## 目录

```text
Lumina-host/
├─ assets/              图标资源
├─ src/                 上位机源码
├─ tools/               打包、自启动和发布辅助脚本
├─ requirements.txt     Python 依赖
└─ README.md            项目说明
```

## 运行

建议使用 Python 3.13。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\auto_dim_screen.py
```

如果没有创建本目录 `.venv`，`tools\build_release.bat` 会尝试复用相邻旧目录的可用虚拟环境。

## 打包

双击或运行：

```bat
tools\build_release.bat
```

打包成功后输出目录为：

```text
dist_release\Lumina
```

运行发布版时需要保留整个 `Lumina` 文件夹，不要只复制 `Lumina.exe`。

## 常见问题

### 缺少 PyInstaller

如果提示缺少 `PyInstaller` 或其他依赖，请安装依赖：

```powershell
python -m pip install -r requirements.txt
```

### Access is denied

如果打包时报 `Access is denied`，通常是以下原因：

- `Lumina.exe` 正在运行。
- 资源管理器打开了 `dist_release\Lumina` 目录。
- 上一次使用管理员权限打包，导致普通权限无法删除旧文件。

处理方式：

1. 退出正在运行的 Lumina。
2. 关闭打开在 `dist_release` 或 `build` 下的资源管理器窗口。
3. 删除 `build` 和 `dist_release` 后重新打包。
4. 如果仍失败，使用管理员权限运行 `tools\build_release.bat`。

### 外接显示器无法调亮度

请确认显示器支持并开启 DDC/CI。部分显示器、扩展坞或转接线可能不支持亮度控制。

## 自启动

发布版可通过程序托盘菜单开启或关闭自启动，也可以使用：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File tools\uninstall_autostart.ps1
```

自启动写入当前用户注册表：

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

## 日志

默认日志位置：

```text
dist_release\Lumina\logs\lumina.log
```

如果程序目录不可写，会自动回退到：

```text
%LOCALAPPDATA%\Lumina\logs\lumina.log
```
