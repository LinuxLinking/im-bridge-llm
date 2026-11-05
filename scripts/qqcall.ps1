param([string]$Tool,[string]$ArgsJson='{}')
$ErrorActionPreference='Stop'
$h=@{Accept='application/json, text/event-stream'; 'Content-Type'='application/json'}
$body=@{jsonrpc='2.0';id=1;method='initialize';params=@{protocolVersion='2024-11-05';capabilities=@{};clientInfo=@{name='probe';version='1'}}}|ConvertTo-Json -Depth 8
$resp=Invoke-WebRequest -Uri 'http://127.0.0.1:8078/mcp' -Method Post -Headers $h -Body $body
$h['mcp-session-id']=$resp.Headers['mcp-session-id']
$null=Invoke-WebRequest -Uri 'http://127.0.0.1:8078/mcp' -Method Post -Headers $h -Body (@{jsonrpc='2.0';method='notifications/initialized'}|ConvertTo-Json -Depth 5)
$argsObj=$ArgsJson|ConvertFrom-Json
$b2=@{jsonrpc='2.0';id=2;method='tools/call';params=@{name=$Tool;arguments=$argsObj}}|ConvertTo-Json -Depth 10
$r2=Invoke-WebRequest -Uri 'http://127.0.0.1:8078/mcp' -Method Post -Headers $h -Body $b2
$txt=$r2.Content
$line=($txt -split "data: " | Where-Object {$_ -match 'jsonrpc'} | Select-Object -Last 1)
$j=$line|ConvertFrom-Json
if($j.result.isError){ "ERROR: "+$j.result.content[0].text } else { $j.result.content | ForEach-Object { $_.text } }
