$ErrorActionPreference = "Stop"

$repo = "C:\Users\jorda\ev-betting-tool"
$python = Join-Path $repo "venv\Scripts\python.exe"

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

if (-not $env:DISCORD_CHANNEL_ID) {
	$env:DISCORD_CHANNEL_ID = "1258141669723734078"
}

if (-not $env:DISCORD_BOT_TOKEN) {
	throw "DISCORD_BOT_TOKEN is not configured in User or Machine environment variables."
}

Push-Location $repo
try {
	& $python discord_bot.py
}
finally {
	Pop-Location
}