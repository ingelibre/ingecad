param([string]$IngeCADDirectory)
$ErrorActionPreference = 'Stop'
if (-not $IngeCADDirectory) {
    $taskRegistration = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\IngeCAD AI Bundle' -ErrorAction SilentlyContinue
    if ($taskRegistration) { $IngeCADDirectory = $taskRegistration.InstallLocation }
    else { $IngeCADDirectory = Join-Path $env:LOCALAPPDATA 'Programs\IngeCAD-AI' }
}
$taskRoot = [IO.Path]::GetFullPath($IngeCADDirectory)
$taskTarget = Join-Path $taskRoot 'plugins\ingecad_mcp'
if (-not (Test-Path -LiteralPath (Join-Path $taskTarget '__init__.py'))) {
    throw 'IngeCAD AI Bundle not found. Use -IngeCADDirectory with the installed bundle directory.'
}
$taskRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe','IngeCAD.exe') -and $_.CommandLine -and $_.CommandLine.IndexOf($taskRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
}
if ($taskRunning) { throw 'Close IngeCAD and its connected MCP client before applying this update.' }
foreach ($taskFile in (Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'plugin') -File)) {
    if ($taskFile.Extension -notin @('.py','.json') -or $taskFile.Name -eq 'connection.json') { continue }
    Copy-Item -LiteralPath $taskFile.FullName -Destination (Join-Path $taskTarget $taskFile.Name) -Force
}
Write-Output 'Updated IngeCAD AI/MCP to 0.3.2. Reopen IngeCAD, start a new chat, and run Test connection.'
