# This script runs inside the recording terminal window.
# It starts ffmpeg, launches Claude interactive, injects the prompt via SendKeys,
# waits for execution, and produces the final MP4.

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
Set-Location "D:\ExecutionDesk-AI"

$mcpConfig = "D:\ExecutionDesk-AI\demos\mcp-config.json"
$rawFile   = "D:\ExecutionDesk-AI\demos\raw-capture.mkv"
$outFile   = Join-Path $env:USERPROFILE "Downloads\fdpe demo.mp4"
$prompt    = "Research World Cup prediction markets on Polymarket using executiondesk MCP tools. First search_markets for World Cup. Then get_market_detail on the top result. Then get_order_book for it. Then get_price_history with interval max and fidelity 60. After each tool result write one sentence of trader analysis. No markdown. Be concise."

if (Test-Path $rawFile) { Remove-Item $rawFile -Force }
if (Test-Path $outFile) { Remove-Item $outFile -Force }

# Load SendKeys
Add-Type -AssemblyName System.Windows.Forms
$wshell = New-Object -ComObject WScript.Shell

# Start screen recorder in background
$rec = Start-Process ffmpeg -ArgumentList @(
    "-f", "gdigrab", "-framerate", "30", "-i", "desktop",
    "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
    "-y", $rawFile
) -PassThru -WindowStyle Hidden
Start-Sleep 2

# Launch Claude interactive TUI in the FOREGROUND of THIS terminal
# We pipe nothing — it runs interactive with full TUI
$claudeArgs = "--model sonnet --mcp-config `"$mcpConfig`" --dangerously-skip-permissions"
$claudeProc = Start-Process -FilePath "claude" -ArgumentList $claudeArgs -PassThru -NoNewWindow

# Wait for TUI to load and render banner + MCP connection
Start-Sleep 15

# Type the prompt into the Claude TUI
# Escape SendKeys special chars: + ^ % ~ ( ) { }
$safe = $prompt.Replace('{', '{{').Replace('}', '}}')
$safe = $safe.Replace('+', '{+}').Replace('^', '{^}').Replace('%', '{%}').Replace('~', '{~}')
$safe = $safe.Replace('(', '{(}').Replace(')', '{)}')

$wshell.AppActivate($claudeProc.Id) | Out-Null
Start-Sleep 1
$wshell.SendKeys($safe)
Start-Sleep 2
$wshell.SendKeys("{ENTER}")

# Wait for MCP tool execution to complete
Start-Sleep 75

# Stop recorder
try { Stop-Process -Id $rec.Id -Force } catch {}
Start-Sleep 2

# Kill Claude TUI
try { Stop-Process -Id $claudeProc.Id -Force } catch {}

if (-not (Test-Path $rawFile) -or (Get-Item $rawFile).Length -lt 500000) {
    Write-Host "ERROR: recording failed" -ForegroundColor Red
    pause; exit 1
}

# Convert to 1920x1080 MP4
& ffmpeg -i $rawFile -t 65 -vf "scale=1920:1080:flags=lanczos" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart -y $outFile

if (Test-Path $outFile) {
    $d = & ffprobe -v error -show_entries format=duration -of csv=p=0 $outFile
    $s = [math]::Round((Get-Item $outFile).Length / 1MB, 1)
    Write-Host "DONE: $outFile (${d}s, ${s}MB)" -ForegroundColor Green
} else {
    Write-Host "ERROR: conversion failed" -ForegroundColor Red
}
pause
