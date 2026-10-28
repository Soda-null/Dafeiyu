# 一键在 Windows 上养一条大肥鱼（Windows 10 / 11，PowerShell 5.1 或 7 都行）。
#
#   在 PowerShell 里粘贴这一行：
#   irm https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.ps1 -OutFile $env:TEMP\dafeiyu.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\dafeiyu.ps1
#
#   已经 clone 下来的仓库里：
#   powershell -ExecutionPolicy Bypass -File install.ps1             装（重复跑也安全：不覆盖已有的 .env 和记忆）
#   powershell -ExecutionPolicy Bypass -File install.ps1 update      拉新代码、装依赖、重启她（记忆不动）
#   powershell -ExecutionPolicy Bypass -File install.ps1 uninstall   停掉她、删掉开机自启（记忆和代码都留着）
#
# 装的东西全在一个文件夹里（默认 %USERPROFILE%\Dafeiyu，可用 DAFEIYU_DIR 改）：代码、.venv、.env（密钥）、
# data\（她的记忆）。开机自启用的是"任务计划程序"里你自己用户下的两个任务，不用管理员。
# 不想手动输入时可以预先给：$env:DEEPSEEK_API_KEY = "sk-..."
param([string]$Action = "install")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"

$RepoUrl = if ($env:DAFEIYU_REPO) { $env:DAFEIYU_REPO } else { "https://github.com/Soda-null/whale-be-friends.git" }
$TaskWechat = "Dafeiyu WeChat"
$TaskNightly = "Dafeiyu nightly"

function Say($msg)  { Write-Host "🐟 $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "!! $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }
function Ask($question, $default) {
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { return $default }
    $reply = Read-Host $question
    if ($reply) { return $reply } else { return $default }
}

# --- where the repo is --------------------------------------------------------------------
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "src\fish\__main__.py"))) {
    $Dir = $PSScriptRoot
} elseif ($env:DAFEIYU_DIR) {
    $Dir = $env:DAFEIYU_DIR
} else {
    $Dir = Join-Path $HOME "Dafeiyu"
}
$Py = Join-Path $Dir ".venv\Scripts\python.exe"
$PyW = Join-Path $Dir ".venv\Scripts\pythonw.exe"
$Runner = Join-Path $Dir "scripts\windows\run_hidden.pyw"
$EnvFile = Join-Path $Dir ".env"

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Offer-Winget($what, $id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    $yes = Ask "没找到 $what。要我用 winget（Windows 自带的软件安装器）装吗？[Y/n]" "Y"
    if ($yes -match "^[nN]") { return $false }
    winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements
    Refresh-Path
    return $true
}

function Find-Python {
    # The py launcher first: a bare "python" may be the Microsoft Store stub that only opens the Store.
    # Windows PowerShell 5.1 turns any stderr line of a native command into an error when
    # stderr is redirected, so the probe runs with errors allowed ("py -3.13" may not exist).
    $ErrorActionPreference = "Continue"
    $candidates = @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python"), @("python3"))
    foreach ($c in $candidates) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($c | Select-Object -Skip 1)
        $out = & $c[0] @rest -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "True") { return ,$c }
    }
    return $null
}

function Get-Code {
    if (Test-Path (Join-Path $Dir "src\fish\__main__.py")) { return }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        if (-not (Offer-Winget "git" "Git.Git") -or -not (Get-Command git -ErrorAction SilentlyContinue)) {
            Die "需要先装 git：https://git-scm.com/download/win （或 winget install Git.Git），装完重开 PowerShell 再跑"
        }
    }
    if (Test-Path $Dir) { Die "$Dir 已经存在但不是大肥鱼的仓库；换个地方：`$env:DAFEIYU_DIR = `"$HOME\别的名字`"" }
    Say "把代码拿到 $Dir"
    git clone -q $RepoUrl $Dir
    if ($LASTEXITCODE -ne 0) { Die "git clone 失败了，看看网络" }
}

function Install-Deps {
    if (-not (Test-Path $Py)) {
        $base = Find-Python
        if (-not $base) {
            if (Offer-Winget "Python 3.11 或更新" "Python.Python.3.12") { $base = Find-Python }
            if (-not $base) { Die "需要 Python 3.11 或更新：https://www.python.org/downloads/ （装的时候勾上 Add to PATH），装完重开 PowerShell 再跑" }
        }
        Say "用 $($base -join ' ') 建虚拟环境（.venv，只给她用的 Python）"
        $rest = @($base | Select-Object -Skip 1)
        & $base[0] @rest -m venv (Join-Path $Dir ".venv")
        if ($LASTEXITCODE -ne 0) { Die "建不了虚拟环境" }
    }
    Say "装依赖（第一次要一两分钟）"
    & $Py -m pip install -q --upgrade pip
    & $Py -m pip install -q -r (Join-Path $Dir "requirements.txt") -e $Dir
    if ($LASTEXITCODE -ne 0) { Die "依赖没装上，看上面 pip 的报错" }
}

function Env-Get($name) {
    if (-not (Test-Path $EnvFile)) { return "" }
    $line = Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -match "^$name=" } | Select-Object -Last 1
    if ($line) { return $line.Substring($name.Length + 1) } else { return "" }
}

function Read-Key {
    if ([Console]::IsInputRedirected) { return "" }
    $secure = Read-Host "粘贴 key（输入时不显示）" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Check-Key($key) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://api.deepseek.com/models" -TimeoutSec 15 `
            -Headers @{ Authorization = "Bearer $key" } | Out-Null
        return 200
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

function Write-Env {
    if ((Test-Path $EnvFile) -and (Env-Get "DEEPSEEK_API_KEY")) {
        Say ".env 已经有了，不动它（要改就直接编辑 $EnvFile）"
        return
    }
    Write-Host ""
    Say "需要一个 DeepSeek 的 API key（她的脑子）。没有的话去 https://platform.deepseek.com 注册、充几块钱、建一个 key。"
    $key = $env:DEEPSEEK_API_KEY
    while ($true) {
        if (-not $key) { $key = Read-Key }
        if (-not $key) { Die "没有 key 她没法说话。拿到 key 后重跑这个脚本" }
        $code = Check-Key $key
        if ($code -eq 200) { Say "key 能用"; break }
        if ($code -eq 401) { Warn "DeepSeek 说这个 key 不对，再粘一次"; $key = ""; continue }
        Warn "连不上 DeepSeek 检查不了（HTTP $code），先存下，之后不行再改 .env"; break
    }
    $owner = Ask '她提到你的时候用"他"还是"她"？输入 他 或 她（回车 = 他）' "他"
    if ($owner -ne "她") { $owner = "他" }
    $text = @"
# 大肥鱼的设置。密钥只存在这台电脑上，不进 git。改完重启她：powershell -ExecutionPolicy Bypass -File install.ps1 update
DEEPSEEK_API_KEY=$key
# 她的白天黑夜跟这台电脑的时钟走（Windows 上不用写 TZ）
# 她称呼你用 他 还是 她
FISH_OWNER=$owner
# 她能不能先找你（1 = 能，0 = 不能）；一天最多几次，0 = 不限，她想发就发
FISH_REACH_OUT=1
FISH_REACH_MAX=0
# 她住哪：默认是这台电脑网络所在的城市。想让她住在别处，填那里的"纬度,经度"
# （只精确到约一公里，不会记门牌）。例：FISH_HOME=31.23,121.47
# FISH_HOME=
"@
    [IO.File]::WriteAllText($EnvFile, ($text -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    Say "设置写进了 $EnvFile"
}

function Check {
    Say "跑一遍自检（不联网、不花钱）"
    Push-Location $Dir
    try { & $Py -m pytest -q -p no:cacheprovider | Select-Object -Last 1 } finally { Pop-Location }
}

function Wechat-Login {
    if (Test-Path (Join-Path $Dir "data\wechat.json")) {
        Say "微信已经绑过了（要换号：cd $Dir; .\fish.cmd wechat login）"
        return
    }
    Write-Host ""
    if ([Console]::IsInputRedirected) {
        Say "没有终端可以显示二维码，先不绑。之后：cd $Dir; .\fish.cmd wechat login"
        return
    }
    $yes = Ask "现在绑微信吗？会出一个二维码，用你自己的微信扫（她只回扫码的这个号）。[Y/n]" "Y"
    if ($yes -match "^[nN]") { Say "先不绑。之后想绑：cd $Dir; .\fish.cmd wechat login"; return }
    Push-Location $Dir
    try { & $Py -m fish wechat login } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Warn "这次没绑上，之后再试：cd $Dir; .\fish.cmd wechat login" }
}

# --- running her in the background --------------------------------------------------------
function Remove-Tasks {
    foreach ($name in @($TaskWechat, $TaskNightly)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
    }
}

function Install-Tasks {
    if ($env:DAFEIYU_SKIP_SERVICES) { Say "跳过开机自启（DAFEIYU_SKIP_SERVICES）"; return }
    Remove-Tasks
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    try {
        $nightly = New-ScheduledTaskAction -Execute $PyW -Argument "`"$Runner`" nightly" -WorkingDirectory $Dir
        Register-ScheduledTask -TaskName $TaskNightly -Action $nightly -Settings $settings -User $user `
            -Trigger (New-ScheduledTaskTrigger -Daily -At "03:30") `
            -Description "大肥鱼每晚整理记忆、写日记（电脑关着就开机后补跑）" | Out-Null
        if (Test-Path (Join-Path $Dir "data\wechat.json")) {
            $wechat = New-ScheduledTaskAction -Execute $PyW -Argument "`"$Runner`" wechat" -WorkingDirectory $Dir
            Register-ScheduledTask -TaskName $TaskWechat -Action $wechat -Settings $settings -User $user `
                -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) `
                -Description "大肥鱼在微信上回你（登录 Windows 就启动，没有窗口）" | Out-Null
            Start-ScheduledTask -TaskName $TaskWechat
        }
    } catch {
        Warn "开机自启没设上（$($_.Exception.Message)）。手动让她跑：cd $Dir; .\fish.cmd wechat（窗口别关）"
        return
    }
    Warn "电脑睡眠或关机时她就不回了。想让她一直在，在 设置 → 系统 → 电源 里把睡眠设成'从不'，或者放到一台一直开着的机器上。"
}

function Finish {
    Write-Host ""
    Say "好了。她住在 $Dir"
    if (Test-Path (Join-Path $Dir "data\wechat.json")) {
        Write-Host "   去微信给她发一句话吧。第一次她会有点认生，聊多了就熟了。"
    } else {
        Write-Host "   在终端里和她聊：cd $Dir; .\fish.cmd"
    }
    Write-Host "   看她今天过得怎么样：cd $Dir; .\fish.cmd life"
    Write-Host "   看她记了什么：      cd $Dir; .\fish.cmd show"
    Write-Host "   看她的日志：        Get-Content $Dir\data\logs\wechat.log -Wait -Tail 20"
    Write-Host "   更新 / 重启：       powershell -ExecutionPolicy Bypass -File $Dir\install.ps1 update"
    Write-Host "   停掉她：            powershell -ExecutionPolicy Bypass -File $Dir\install.ps1 uninstall   （记忆留在 $Dir\data\）"
}

switch ($Action) {
    "install" {
        Get-Code
        Install-Deps
        Write-Env
        Check
        Wechat-Login
        Install-Tasks
        Finish
    }
    "update" {
        if (-not (Test-Path (Join-Path $Dir "src\fish\__main__.py"))) { Die "在 $Dir 没找到她；先装" }
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Say "拉新代码"
            git -C $Dir pull -q --ff-only
        }
        Install-Deps
        Check
        Install-Tasks
        Say "更新好了"
    }
    "uninstall" {
        Remove-Tasks
        Say "她停了，开机也不会再起来。记忆还在 $Dir\data\；想彻底删掉就删整个 $Dir 文件夹。"
    }
    default { Die "用法：install.ps1 [install|update|uninstall]" }
}
