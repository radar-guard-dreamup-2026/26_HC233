<#
prefill_check.ps1 — 챗봇 프롬프트 처리 속도 진단 (2026-10-19, 임시 진단용)

  실행: [내 PC PowerShell, 이 저장소 루트]
      powershell -ExecutionPolicy Bypass -File scripts\prefill_check.ps1

  왜 있나
    10/18 측정에서 사고 질문의 '프롬프트 처리'만 10/10 대비 약 10배 느려졌다
    (I-05: 3.72초 → 34.44초). 생성 속도는 같았다. 관제 화면 없이 Ollama 에
    I-05 와 같은 길이의 프롬프트(scripts\prefill_check_prompt.txt)를 직접 보내
    프롬프트 처리 시간만 잰다. 매번 첫 줄을 바꿔 캐시를 피한다.
  기준: 10/10 I-05 프롬프트 처리 3.72초. 이 근처면 정상.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$model = 'exaone3.5:2.4b'

# 전원·CPU 상태 — 원인 후보(배터리·전원 계획·클럭)를 같이 남긴다.
$bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
$ac = if ($bat) { if ($bat.BatteryStatus -eq 2) { 'AC(충전기 연결)' } else { "배터리 구동(상태 $($bat.BatteryStatus))" } } else { '배터리 없음' }
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Write-Host "전원: $ac"
Write-Host "전원 계획: $((powercfg /getactivescheme) -join ' ')"
Write-Host "CPU: $($cpu.Name.Trim()) · 현재 $($cpu.CurrentClockSpeed) MHz / 최대 $($cpu.MaxClockSpeed) MHz · 사용률 $($cpu.LoadPercentage)%"
$os = Get-CimInstance Win32_OperatingSystem
Write-Host ("가용 메모리: {0:N0} MB" -f ($os.FreePhysicalMemory / 1KB))
# [10/19 T-CC07g] 10배 지연의 실제 원인 = 남은 모델 실행기(llama-server)가 VRAM 을 쥔 것.
$runners = @(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)
Write-Host "남은 모델 실행기(llama-server): $($runners.Count)개  (시연 시작 전 0개여야 정상 — start_demo 가 정리)"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) { Write-Host "VRAM: $((& nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader) -join ' ')" }
Write-Host "CPU 상위 5개 프로세스(누적):"
Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 | ForEach-Object { Write-Host ("  {0,-28} CPU {1,8:N0}s  메모리 {2,6:N0} MB" -f $_.ProcessName, $_.CPU, ($_.WorkingSet64 / 1MB)) }

# Ollama 가 떠 있지 않으면 start_demo 와 같은 방식으로 serve 만 띄운다(트레이 앱 X).
function Test-Ollama { try { Invoke-WebRequest 'http://127.0.0.1:11434/api/version' -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }
if (-not (Test-Ollama)) {
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden
    $t = 0; while (-not (Test-Ollama) -and $t -lt 60) { Start-Sleep 2; $t += 2 }
    if (-not (Test-Ollama)) { Write-Host 'Ollama 가 응답하지 않는다 — 중단'; exit 1 }
    Write-Host 'Ollama serve 기동'
}

$prompt = Get-Content (Join-Path $PSScriptRoot 'prefill_check_prompt.txt') -Encoding UTF8 -Raw
function Ask([string]$p, [int]$predict) {
    $body = @{ model = $model; prompt = $p; stream = $false; keep_alive = '10m'
               options = @{ num_ctx = 2048; num_predict = $predict; temperature = 0 } } | ConvertTo-Json -Depth 4
    Invoke-RestMethod 'http://127.0.0.1:11434/api/generate' -Method Post `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8' -TimeoutSec 300
}
# 모델 적재(측정에서 제외)
$w = Ask '안녕' 1
Write-Host ("모델 적재: {0:N1}초" -f ($w.load_duration / 1e9))

foreach ($i in 1..3) {
    $r = Ask ("[진단 $i $(Get-Date -Format HHmmssfff)]`n" + $prompt) 30
    $pe = $r.prompt_eval_duration / 1e9; $ev = $r.eval_duration / 1e9
    Write-Host ("{0}회: 프롬프트 {1}토큰 {2:N2}초 ({3:N0} 토큰/초) · 생성 {4}토큰 {5:N2}초 ({6:N1} 토큰/초)" -f `
        $i, $r.prompt_eval_count, $pe, ($r.prompt_eval_count / [math]::Max($pe, 0.001)), $r.eval_count, $ev, ($r.eval_count / [math]::Max($ev, 0.001)))
}
Write-Host '기준: 10/10 I-05 프롬프트 처리 3.72초 · 10/18 34.44초'
