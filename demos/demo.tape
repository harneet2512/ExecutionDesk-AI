# ExecutionDesk-AI - live Claude Code + Polymarket MCP demo
#
# This renders a REAL interactive Claude Code session to MP4. It is not a
# simulation: VHS spins up a real PTY via ttyd, launches the actual `claude`
# binary, types the prompt, and ffmpeg captures the real streamed output.
# Auth is inherited from your Claude Code subscription login (~/.claude) -
# no Anthropic API key involved.

Output executiondesk-demo.mp4

Require claude
Require ttyd
Require ffmpeg

Set Shell "powershell"
Set Width 800
Set Height 600
Set FontSize 20
Set FontFamily "JetBrains Mono"
Set Theme "TokyoNight"
Set Padding 24
Set TypingSpeed 45ms
Set WaitTimeout 3m

# --- clean start (hidden from the recording) ---
Hide
Type "clear" Enter
Show

# --- launch a real interactive Claude Code session ---
#  --model sonnet                  banner shows claude-sonnet-4-x
#  --mcp-config mcp-config.json    connects the executiondesk Polymarket MCP server (8 tools)
#  --dangerously-skip-permissions  unattended run never stalls on a tool-approval prompt
Type "claude --model sonnet --mcp-config mcp-config.json --dangerously-skip-permissions"
Enter

# Wait until the TUI is up and the MCP server is connected. The startup banner
# lists connected servers, so the screen will contain "executiondesk".
Wait+Screen /executiondesk/
Sleep 2s

# --- type the demo prompt and run it against live Polymarket data ---
Type "Research World Cup prediction markets on Polymarket using executiondesk MCP tools. Search markets, get details on Spain, check the order book, pull price history. After each tool result write one sentence of trader analysis. No markdown."
Enter

# Live run: search_markets -> get_market_detail -> get_order_book -> get_price_history,
# with a line of analysis between each. THIS SLEEP IS THE ONE KNOB TO TUNE.
# Time a warm-up run, then set this a bit longer than the real run took.
# Over-shooting is fine (trailing static frames get trimmed afterward);
# under-shooting cuts off mid-run.
Sleep 100s

# --- clean finish ---
Ctrl+C
Sleep 400ms
Ctrl+C
Sleep 1s
