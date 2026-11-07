[CmdletBinding()]
param(
    [string]$Title = 'Воспроизводимый baseline и ограниченный ночной цикл GigaChat',
    [string]$BodyFile,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$repository = 'pypsycoder/conversation-assistant'
$gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
$gitExe = 'C:\Program Files\Git\cmd\git.exe'
if (-not (Test-Path -LiteralPath $gitExe)) {
    if (-not $gitCommand) { throw 'git.exe не найден' }
    $gitExe = $gitCommand.Source
}
$ghCommand = Get-Command gh.exe -ErrorAction SilentlyContinue
$ghExe = Join-Path $projectRoot '.tools/gh-2.103.3/app/bin/gh.exe'
if (-not (Test-Path -LiteralPath $ghExe)) {
    if (-not $ghCommand) { throw 'Нужен официальный GitHub CLI: см. docs/GIT_WORKFLOW.md' }
    $ghExe = $ghCommand.Source
}

function Invoke-GitChecked {
    param([string[]]$Arguments)
    $result = & $gitExe -C $projectRoot @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Ошибка git: $($Arguments[0])" }
    return $result
}

function Invoke-GhChecked {
    param([string[]]$Arguments)
    $result = & $ghExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Ошибка gh: $($Arguments[0]); проверьте gh auth status" }
    return $result
}

$origin = (Invoke-GitChecked -Arguments @('remote', 'get-url', 'origin')).Trim()
if ($origin -notin @('https://github.com/pypsycoder/conversation-assistant.git',
                    'git@github.com:pypsycoder/conversation-assistant.git')) {
    throw 'origin не соответствует отдельному проекту conversation-assistant'
}
$branch = (Invoke-GitChecked -Arguments @('branch', '--show-current')).Trim()
if (-not $branch -or $branch -eq 'main') { throw 'Нужна отдельная исследовательская ветка' }
$changed = Invoke-GitChecked -Arguments @('status', '--porcelain', '--untracked-files=no')
if ($changed) { throw 'Сначала проверьте и закоммитьте изменения отслеживаемых файлов' }
$login = (Invoke-GhChecked -Arguments @('api', 'user', '--jq', '.login')).Trim()
if ($login -ne 'pypsycoder') { throw 'GitHub CLI авторизован не как pypsycoder' }
if (-not $BodyFile) { $BodyFile = Join-Path $projectRoot 'docs/pr-nightly-baseline.md' }
$resolvedBody = (Resolve-Path -LiteralPath $BodyFile).Path
if ($CheckOnly) {
    [pscustomobject]@{ repository = $repository; branch = $branch; login = $login;
        bodyFile = $resolvedBody; mode = 'check_only' } | ConvertTo-Json
    return
}

# Never add files, commit, merge, force-push, or rewrite history here.
Invoke-GitChecked -Arguments @('fetch', 'origin', 'main')
$ahead = Invoke-GitChecked -Arguments @('rev-list', '--count', 'origin/main..HEAD')
if ([int]$ahead -eq 0) { throw 'Нет коммитов для PR относительно origin/main' }
Invoke-GitChecked -Arguments @('push', '--set-upstream', 'origin', "HEAD:refs/heads/$branch")
$existingJson = Invoke-GhChecked -Arguments @('pr', 'list', '--repo', $repository, '--head', $branch,
    '--base', 'main', '--state', 'open', '--json', 'url')
$existing = @($existingJson | ConvertFrom-Json)
if ($existing.Count -gt 0) {
    $existing[0].url
    return
}
Invoke-GhChecked -Arguments @('pr', 'create', '--repo', $repository, '--base', 'main', '--head', $branch,
    '--draft', '--title', $Title, '--body-file', $resolvedBody)
