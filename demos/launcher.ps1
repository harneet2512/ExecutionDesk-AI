# This runs inside the demo terminal window.
# It starts ffmpeg, then launches Claude interactive (which takes over the terminal).
# A separate process (typer.ps1) injects the prompt after Claude loads.

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
Set-Location "D:\ExecutionDesk-AI"

$rawFile = "D:\ExecutionDesk-AI\demos\raw-capture.mkv"
if (Test-Path $rawFile) { Remove-Item $rawFile -Force }

$host.UI.RawUI.WindowTitle = "FDPE-DEMO-RECORDING"

# Start screen recorder in background
Start-Process ffmpeg -ArgumentList @(
    "-f", "gdigrab", "-framerate", "30", "-i", "desktop",
    "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
    "-y", $rawFile
) -WindowStyle Hidden

Start-Sleep 2

# Launch Claude interactive — this takes over the terminal with full TUI
claude --model sonnet --mcp-config "D:\ExecutionDesk-AI\demos\mcp-local.json" --dangerously-skip-permissions

# After Claude exits (Ctrl+C or /exit), stop ffmpeg
taskkill /F /IM ffmpeg.exe 2>$null
Start-Sleep 1

# Convert to final MP4
$outFile = Join-Path $env:USERPROFILE "Downloads\fdpe demo.mp4"
if (Test-Path $rawFile) {
    & ffmpeg -i $rawFile -t 65 -vf "scale=1920:1080:flags=lanczos" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart -y $outFile
    if (Test-Path $outFile) {
        $d = & ffprobe -v error -show_entries format=duration -of csv=p=0 $outFile
        $s = [math]::Round((Get-Item $outFile).Length / 1MB, 1)
        Write-Host "DONE: $outFile (${d}s, ${s}MB)" -ForegroundColor Green
    }
}
pause
