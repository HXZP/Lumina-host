$ErrorActionPreference = "Stop"

$registryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$valueName = "Lumina"

if (-not (Test-Path $registryPath))
{
    Write-Output "当前用户尚未配置自启动。"
    exit 0
}

$existingValue = Get-ItemProperty `
    -Path $registryPath `
    -Name $valueName `
    -ErrorAction SilentlyContinue

if ($null -eq $existingValue)
{
    Write-Output "当前用户尚未配置 Lumina 自启动。"
    exit 0
}

Remove-ItemProperty `
    -Path $registryPath `
    -Name $valueName

Write-Output "已为当前用户关闭 Lumina 登录后自启动。"
