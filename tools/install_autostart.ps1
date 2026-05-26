$ErrorActionPreference = "Stop"

$toolDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDirectory = Split-Path -Parent $toolDirectory
$distExecutable = Join-Path $appDirectory "dist_release\Lumina\Lumina.exe"
$scriptExecutable = Join-Path $appDirectory "src\auto_dim_screen.py"
$registryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$valueName = "Lumina"

if (Test-Path $distExecutable)
{
    $commandValue = '"' + $distExecutable + '"'
}
elseif (Test-Path $scriptExecutable)
{
    $pythonCommand = (Get-Command python -ErrorAction Stop).Source
    $commandValue = '"' + $pythonCommand + '" "' + $scriptExecutable + '"'
}
else
{
    throw "未找到 Lumina 可执行文件或脚本。"
}

if (-not (Test-Path $registryPath))
{
    New-Item -Path $registryPath -Force | Out-Null
}

New-ItemProperty `
    -Path $registryPath `
    -Name $valueName `
    -Value $commandValue `
    -PropertyType String `
    -Force | Out-Null

Write-Output "已为当前用户启用 Lumina 登录后自启动。"
Write-Output "启动命令: $commandValue"
