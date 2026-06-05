# Lumina 使用说明书

## 1. 产品简介

Lumina 是一套用于 Windows 电脑的显示器辅助控制工具，由 Lumina 设备和 Windows 上位机程序组成。上位机通过 USB HID 读取设备方向和环境光数据，并根据用户配置控制显示器旋转、亮度和暗屏状态。

主要能力：

- 根据 Lumina 设备姿态自动旋转绑定显示器。
- 根据环境光 lux 数据自动调节显示器亮度。
- 支持多台 Lumina 设备分别绑定不同显示器。
- 支持多显示器亮度控制，优先使用 DDC/CI，必要时使用 WMI。
- 通过系统托盘面板进行绑定、亮度、档位、自启动等配置。

![产品整体示意图占位](assets/manual/product-overview.png)

图片建议：放置一张“Lumina 设备 + Windows 电脑 + 外接显示器”的整体连接示意图，标明 USB HID 数据、环境光数据、显示器控制三个方向。

## 2. 适用环境

### 2.1 系统要求

- 操作系统：Windows 10 或 Windows 11。
- 运行方式：推荐使用发布版 `Lumina.exe`。
- 显示器控制：外接显示器建议开启 DDC/CI。
- 设备连接：Lumina 设备通过 USB 连接电脑。

### 2.2 注意事项

- 部分显示器、扩展坞、转接线或显卡驱动可能不支持 DDC/CI 亮度控制。
- Windows 内置屏幕通常通过 WMI 或系统接口调节亮度，外接屏通常依赖 DDC/CI。
- 若移动了发布版文件夹位置，需要重新开启自启动。

![使用环境示意图占位](assets/manual/environment.png)

图片建议：绘制电脑、Lumina 设备、外接显示器、USB 连接线、显示器视频线的连接关系图。

## 3. 安装与启动

### 3.1 使用发布版

1. 打开发布目录：

```text
dist_release\Lumina
```

2. 双击运行：

```text
Lumina.exe
```

3. 程序启动后会显示在 Windows 系统托盘区域。

运行发布版时需要保留整个 `Lumina` 文件夹，不要只复制 `Lumina.exe`。

![发布目录示意图占位](assets/manual/release-folder.png)

图片建议：放置 `dist_release\Lumina` 文件夹截图，框出 `Lumina.exe` 和必要的资源文件。

### 3.2 使用源码版

源码版适合开发、调试或验证功能。建议使用 Python 3.13，也支持 Python 3.12。

```powershell
python -m pip install -r requirements.txt
python src\auto_dim_screen.py
```

![源码运行示意图占位](assets/manual/source-run.png)

图片建议：放置 PowerShell 运行命令截图，包含依赖安装和启动命令。

## 4. 托盘面板

程序运行后，会在 Windows 系统托盘区域显示 Lumina 图标。点击或右键图标可打开控制面板或菜单，用于查看设备状态、调节亮度和修改配置。

托盘面板常用功能：

- 查看 Lumina 设备连接状态。
- 查看显示器列表和绑定关系。
- 手动调节显示器亮度。
- 开启或关闭自动亮度。
- 开启或关闭自动旋转。
- 配置亮度档位。
- 开启或关闭开机自启动。
- 打开日志或退出程序。

![托盘入口示意图占位](assets/manual/tray-entry.png)

图片建议：截取 Windows 任务栏右下角托盘图标，标出 Lumina 图标位置。

![托盘面板示意图占位](assets/manual/tray-panel.png)

图片建议：截取 Lumina 托盘面板主界面，标注设备状态区、显示器区、亮度控制区和配置入口。

## 5. 设备与显示器绑定

当电脑连接多台 Lumina 或多台显示器时，需要为每台 Lumina 指定对应的显示器。绑定完成后，自动旋转和自动亮度会作用到对应显示器。

### 5.1 绑定步骤

1. 确认 Lumina 设备已经通过 USB 连接电脑。
2. 打开 Lumina 托盘面板。
3. 在设备列表中选择需要配置的 Lumina 设备。
4. 在显示器列表中选择目标显示器。
5. 保存绑定配置。
6. 改变 Lumina 设备方向或环境光，确认目标显示器响应正确。

![设备绑定流程图占位](assets/manual/device-binding-flow.png)

图片建议：绘制“选择 Lumina 设备 -> 选择显示器 -> 保存绑定 -> 验证效果”的流程图。

![设备绑定界面示意图占位](assets/manual/device-binding-panel.png)

图片建议：截取设备绑定配置界面，标注设备名称、显示器名称、保存按钮。

### 5.2 绑定建议

- 一台 Lumina 建议只绑定一台主要显示器。
- 多显示器环境下，建议先通过 Windows 显示设置确认显示器编号和物理位置。
- 若更换显示器、扩展坞或接口，建议重新检查绑定关系。

## 6. 自动旋转

自动旋转功能会根据 Lumina 设备的姿态方向，自动调整绑定显示器的屏幕方向。

### 6.1 使用步骤

1. 将 Lumina 设备固定在目标显示器上。
2. 在托盘面板中完成设备与显示器绑定。
3. 开启自动旋转功能。
4. 旋转显示器或 Lumina 设备，观察 Windows 显示方向是否同步变化。

![自动旋转安装示意图占位](assets/manual/auto-rotation-mount.png)

图片建议：放置 Lumina 设备固定在显示器背面或边框位置的照片，标明设备方向。

![自动旋转效果示意图占位](assets/manual/auto-rotation-effect.png)

图片建议：用左右对比图展示横屏和竖屏两种状态，标出 Lumina 姿态变化与显示器方向变化的对应关系。

### 6.2 调试建议

- 若旋转方向相反，检查 Lumina 安装方向是否与配置一致。
- 若系统没有响应，确认该显示器已正确绑定。
- 若 Windows 显示方向被系统策略锁定，需要先解除系统限制。

## 7. 自动亮度

自动亮度功能会读取 Lumina 环境光 lux 数据，并按照预设档位设置绑定显示器亮度。

### 7.1 亮度档位

亮度档位用于定义不同环境光条件下的显示器亮度。例如：

| 环境光范围 | 建议亮度 |
| --- | --- |
| 较暗环境 | 20% - 35% |
| 普通室内 | 40% - 65% |
| 明亮环境 | 70% - 100% |

实际档位需要根据显示器亮度表现、办公环境和用户习惯调整。

![亮度档位配置示意图占位](assets/manual/brightness-levels.png)

图片建议：截取亮度档位配置界面，标注 lux 阈值、目标亮度百分比、保存按钮。

### 7.2 使用步骤

1. 确认 Lumina 设备连接正常。
2. 确认显示器支持亮度控制。
3. 在托盘面板中完成设备与显示器绑定。
4. 配置环境光档位和目标亮度。
5. 开启自动亮度功能。
6. 改变环境光，观察显示器亮度是否按档位变化。

![自动亮度流程图占位](assets/manual/auto-brightness-flow.png)

图片建议：绘制“读取 lux -> 匹配档位 -> 设置显示器亮度 -> 状态反馈”的流程图。

### 7.3 使用建议

- 档位不要设置过密，避免亮度频繁跳变。
- 建议在常用办公环境下测试并微调亮度百分比。
- 外接显示器需要确认 DDC/CI 已开启。

## 8. 自动暗屏

自动暗屏用于在特定条件下自动降低屏幕亮度或进入暗屏状态，减少低光环境下的刺眼感。

### 8.1 使用步骤

1. 打开 Lumina 托盘面板。
2. 确认自动亮度已经配置完成。
3. 开启自动暗屏功能。
4. 设置触发条件或暗屏亮度。
5. 在低光环境下验证暗屏效果。

![自动暗屏示意图占位](assets/manual/auto-dim.png)

图片建议：使用前后对比图展示普通亮度和暗屏亮度，并标出触发条件。

### 8.2 注意事项

- 自动暗屏不等同于关闭显示器。
- 若显示器最低亮度仍然偏亮，需要结合显示器自身菜单调整。
- 若暗屏影响正常使用，可关闭自动暗屏或提高触发阈值。

## 9. 开机自启动

发布版可以通过托盘菜单开启或关闭开机自启动。也可以使用以下脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File tools\uninstall_autostart.ps1
```

自启动写入当前用户注册表：

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

如果移动了 `Lumina` 文件夹位置，请重新运行程序并重新开启自启动。

![自启动设置示意图占位](assets/manual/autostart.png)

图片建议：截取托盘菜单中的“开机自启动”开关，或截取 Windows 启动项配置结果。

## 10. 日志与问题排查

### 10.1 日志位置

默认日志位置：

```text
dist_release\Lumina\logs\lumina.log
```

如果程序目录不可写，会自动回退到：

```text
%LOCALAPPDATA%\Lumina\logs\lumina.log
```

![日志文件示意图占位](assets/manual/log-file.png)

图片建议：放置日志目录截图，标出 `lumina.log` 文件。

### 10.2 常见问题

#### 找不到 Lumina 设备

处理建议：

1. 确认 USB 线连接正常。
2. 更换 USB 接口后重启 Lumina 程序。
3. 检查设备管理器中是否能看到 HID 设备。
4. 查看日志中是否存在设备枚举失败信息。

#### 外接显示器无法调节亮度

处理建议：

1. 打开显示器 OSD 菜单，确认 DDC/CI 已开启。
2. 尽量直接连接显示器，减少扩展坞或转接线影响。
3. 更新显卡驱动。
4. 查看日志中是否存在 DDC/CI 或 WMI 调用失败信息。

#### 自动旋转无效

处理建议：

1. 确认 Lumina 已绑定到正确显示器。
2. 确认自动旋转开关已开启。
3. 检查 Windows 显示设置是否允许旋转。
4. 查看日志中是否有方向识别或显示器设置失败信息。

#### 亮度变化不符合预期

处理建议：

1. 检查亮度档位阈值是否设置合理。
2. 检查 Lumina 环境光窗口是否被遮挡。
3. 调整档位之间的间隔，避免频繁跳变。
4. 查看日志中的 lux 数据和亮度设置记录。

![故障排查流程图占位](assets/manual/troubleshooting-flow.png)

图片建议：绘制“问题现象 -> 检查设备连接 -> 检查绑定配置 -> 检查显示器能力 -> 查看日志”的排查流程图。

## 11. 图片素材清单

建议后续补充以下图片到 `assets/manual/` 目录：

| 文件名 | 图片内容建议 |
| --- | --- |
| `product-overview.png` | Lumina 设备、电脑、显示器整体关系图 |
| `environment.png` | 使用环境和线缆连接示意图 |
| `release-folder.png` | 发布版文件夹截图 |
| `source-run.png` | 源码运行命令截图 |
| `tray-entry.png` | Windows 托盘入口截图 |
| `tray-panel.png` | Lumina 托盘面板主界面截图 |
| `device-binding-flow.png` | 设备绑定流程图 |
| `device-binding-panel.png` | 设备绑定界面截图 |
| `auto-rotation-mount.png` | Lumina 安装方向照片或示意图 |
| `auto-rotation-effect.png` | 横屏/竖屏自动旋转效果对比图 |
| `brightness-levels.png` | 亮度档位配置界面截图 |
| `auto-brightness-flow.png` | 自动亮度工作流程图 |
| `auto-dim.png` | 自动暗屏效果对比图 |
| `autostart.png` | 自启动开关截图 |
| `log-file.png` | 日志文件位置截图 |
| `troubleshooting-flow.png` | 故障排查流程图 |

## 12. 版本记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| V1.0 | 2026-06-05 | 初版说明书，预留示意图位置和图片建议 |
