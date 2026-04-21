# Start Discord Bot
# This script launches the bot using environment variables.

$repo = "C:\Users\jorda\ev-betting-tool"
$python = Join-Path $repo "venv\Scripts\python.exe"

# Pull persisted vars if they are not present in the current process.
if (-not $env:DISCORD_BOT_TOKEN) {
	$userToken = [Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "User")
	if (-not $userToken) {
		$userToken = [Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "Machine")
	}
	if ($userToken) {
		$env:DISCORD_BOT_TOKEN = $userToken
	}
}

if (-not $env:DISCORD_CHANNEL_ID) {
	$userChannel = [Environment]::GetEnvironmentVariable("DISCORD_CHANNEL_ID", "User")
	if (-not $userChannel) {
		$userChannel = [Environment]::GetEnvironmentVariable("DISCORD_CHANNEL_ID", "Machine")
	}
	if ($userChannel) {
		$env:DISCORD_CHANNEL_ID = $userChannel
	}
}

# Set default channel id if not already configured.
if (-not $env:DISCORD_CHANNEL_ID) {
	$env:DISCORD_CHANNEL_ID = "1258141669723734078"
}

# Require token from environment or secure prompt.
if (-not $env:DISCORD_BOT_TOKEN) {
	$secureToken = Read-Host "Enter DISCORD_BOT_TOKEN" -AsSecureString
	$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
	try {
		$env:DISCORD_BOT_TOKEN = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
	}
	finally {
		[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
	}
}

Write-Host "Starting Discord Bot..." -ForegroundColor Green
Write-Host "Listening to channel: $env:DISCORD_CHANNEL_ID" -ForegroundColor Cyan
Write-Host ""

# Run the bot
Push-Location $repo
try {
	& $python discord_bot.py
}
finally {
	Pop-Location
}

# If bot exits, prompt user
Write-Host ""
Write-Host "Bot stopped" -ForegroundColor Yellow
Write-Host "Press Enter to close this window..."
Read-Host
