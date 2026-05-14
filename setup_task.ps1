# setup_task.ps1
# 以系統管理員身分執行，自動建立 Windows 工作排程器任務
# 用法（PowerShell 系統管理員）：.\setup_task.ps1

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Python     = "C:\Users\fr367\AppData\Local\Programs\Python\Python312\python.exe"
$RunScript  = Join-Path $ScriptDir "run_scraper.py"
$TaskName   = "LejuDailyScrape"
$LogFile    = Join-Path $ScriptDir "task_scheduler.log"

# 每天凌晨 2:00 執行
$Trigger  = New-ScheduledTaskTrigger -Daily -At "02:00"
$Action   = New-ScheduledTaskAction `
              -Execute $Python `
              -Argument "`"$RunScript`"" `
              -WorkingDirectory $ScriptDir
$Settings = New-ScheduledTaskSettingsSet `
              -ExecutionTimeLimit  (New-TimeSpan -Hours 2) `
              -RestartCount        2 `
              -RestartInterval     (New-TimeSpan -Minutes 10) `
              -StartWhenAvailable

# 若已存在則先移除
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已移除舊任務：$TaskName"
}

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Trigger    $Trigger `
    -Action     $Action `
    -Settings   $Settings `
    -RunLevel   Highest `
    -Description "每天凌晨 2 點自動更新樂居桃園區實價登錄資料" | Out-Null

Write-Host ""
Write-Host "✅ 工作排程器任務已建立：$TaskName"
Write-Host "   執行時間：每天凌晨 02:00"
Write-Host "   腳本路徑：$RunScript"
Write-Host ""
Write-Host "立即測試執行（可選）："
Write-Host "   Start-ScheduledTask -TaskName '$TaskName'"
