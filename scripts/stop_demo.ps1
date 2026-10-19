<#
stop_demo.ps1 — 시연 종료 (start_demo.ps1 을 되돌린다)

  실행: [내 PC PowerShell, 저장소 루트]
      powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1

  관제 화면 종료 → 챗봇 모델 내리기 → ollama serve 종료. DB 컨테이너는 그대로 둔다.
  단계마다 결과를 한 줄씩 낸다.
#>
param(
    # console_ui.CHAT_MODEL 과 같은 값. 앱이 비정상 종료되면 모델이 남는다.
    [string]$Model = 'exaone3.5:2.4b'
)
$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'

# 1. 관제 화면 — 창을 닫아 앱이 스스로 모델을 내리게 하고, 15초 안에 안 끝나면 끊는다.
$ids = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
    Where-Object { $_.CommandLine -like '*console_ui.py*' } |
    ForEach-Object { $_.ProcessId })
$forced = 0
foreach ($id in $ids) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $p) { continue }
    $p.CloseMainWindow() | Out-Null
    if (-not $p.WaitForExit(15000)) { Stop-Process -Id $id -Force; $forced++ }
}
Write-Host "[1/3] 관제 화면 $($ids.Count)개 종료 (강제 $forced 개)"

# 2. 모델 내리기 — 서버가 떠 있을 때만.
if (Get-Process -Name 'ollama' -ErrorAction SilentlyContinue) {
    & $ollama stop $Model *> $null
    $left = (& $ollama ps | Select-Object -Skip 1 | Measure-Object).Count
    Write-Host "[2/3] 모델 내림 · 남은 모델 $left 개"
} else {
    Write-Host '[2/3] 실행 안 함 — ollama 서버가 떠 있지 않다'
}

# 3. ollama serve 종료.
#    ⚠ [10/19 T-CC07g] 모델 실행기(llama-server)도 함께 끈다 — 남으면 VRAM 을 쥐어
#      다음 시작 때 챗봇 프롬프트 처리가 약 10배 느려진다(41초 → 정리 후 4.2초).
$srv = @(Get-Process -Name 'ollama', 'llama-server' -ErrorAction SilentlyContinue)
$srv | Stop-Process -Force
$nr = @($srv | Where-Object { $_.ProcessName -eq 'llama-server' }).Count
Write-Host "[3/3] ollama 프로세스 $($srv.Count - $nr)개 · 모델 실행기(llama-server) $nr 개 종료"
