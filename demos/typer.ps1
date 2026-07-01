# Injects the COMPLETE FDPE trade lifecycle prompt into the Claude TUI.

Add-Type -AssemblyName System.Windows.Forms
$wshell = New-Object -ComObject WScript.Shell

# Complete end-to-end Polymarket trade: discover > analyze > execute > confirm
$prompt = "What are the top World Cup prediction markets on Polymarket? Analyze the highest-volume one -- order book, price history -- then buy 10 YES shares and confirm the trade."

# Wait for Claude TUI to fully load
Start-Sleep -Seconds 18

# Activate the demo window
$wshell.AppActivate("FDPE-DEMO-RECORDING") | Out-Null
Start-Sleep 1

# Clipboard paste (reliable)
[System.Windows.Forms.Clipboard]::SetText($prompt)
Start-Sleep 1
$wshell.SendKeys("^v")
Start-Sleep 2
$wshell.SendKeys("{ENTER}")
