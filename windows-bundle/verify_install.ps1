param([string]$Installer, [string]$Target)
$ErrorActionPreference = 'Stop'
$taskInstaller = (Resolve-Path -LiteralPath $Installer).Path
$taskTarget = [IO.Path]::GetFullPath($Target)
$taskAllowed = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'test-installed'))
if (-not $taskTarget.StartsWith($taskAllowed + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Test target must be inside distribution/test-installed' }
if (Test-Path -LiteralPath $taskTarget) { throw 'Use a new test target' }
$taskProcess = Start-Process -FilePath $taskInstaller -ArgumentList "/S /TESTMODE /D=$taskTarget" -PassThru -Wait -WindowStyle Hidden
if ($taskProcess.ExitCode -ne 0) { throw "Installer exited $($taskProcess.ExitCode)" }
if (-not (Test-Path -LiteralPath (Join-Path $taskTarget 'Uninstall.exe'))) { throw 'Missing uninstaller' }
$taskCheck = Get-Content -LiteralPath (Join-Path $taskTarget 'install-check.json') -Raw | ConvertFrom-Json
if (-not $taskCheck.passed) { throw 'Runtime check failed' }
$taskConfig = Get-Content -LiteralPath (Join-Path $taskTarget 'MCP-config\client-config.json') -Raw | ConvertFrom-Json
if ($taskConfig.mcpServers.ingecad.command -ne (Join-Path $taskTarget 'runtime\python.exe')) { throw 'Incorrect configured runtime path' }
$taskDesktop = [Environment]::GetFolderPath('Desktop')
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut((Join-Path $taskDesktop 'IngeCAD AI Bundle Test.lnk'))
if ($taskShortcut.TargetPath -ne (Join-Path $taskTarget 'IngeCAD.exe')) { throw 'Incorrect shortcut target' }
$taskRegPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\IngeCAD AI Bundle Test'
if ((Get-ItemProperty -LiteralPath $taskRegPath).InstallLocation -ne $taskTarget) { throw 'Incorrect uninstall registration' }
$taskProof = Join-Path $PSScriptRoot 'test-installed-proof'
& (Join-Path $taskTarget 'runtime\python.exe') -B (Join-Path $PSScriptRoot 'verify_bundle.py') $taskTarget $taskProof
if ($LASTEXITCODE -ne 0) { throw 'Installed GUI/MCP/DWG verification failed' }
$taskSentinel = Join-Path $taskTarget 'user-drawing-preserve.dxf'
[IO.File]::WriteAllText($taskSentinel, 'Fixture representing a user-owned drawing; do not delete.')
$taskUninstall = Start-Process -FilePath (Join-Path $taskTarget 'Uninstall.exe') -ArgumentList '/S' -PassThru -Wait -WindowStyle Hidden
$taskDeadline = [DateTime]::UtcNow.AddSeconds(60)
while ((Test-Path -LiteralPath $taskRegPath) -and [DateTime]::UtcNow -lt $taskDeadline) { Start-Sleep -Milliseconds 250 }
if (Test-Path -LiteralPath $taskRegPath) { throw 'Uninstall registry entry survived' }
if (Test-Path -LiteralPath (Join-Path $taskTarget 'IngeCAD.exe')) { throw 'Installed launcher survived uninstall' }
if (Test-Path -LiteralPath (Join-Path $taskDesktop 'IngeCAD AI Bundle Test.lnk')) { throw 'Test shortcut survived uninstall' }
if (-not (Test-Path -LiteralPath $taskSentinel)) { throw 'Uninstaller deleted a user-owned drawing fixture' }
$taskReport = [ordered]@{ passed=$true; target=$taskTarget; offline_runtime=$taskCheck; shortcut_verified=$true; mcp_paths_generated=$true; gui_mcp_dwg_verified=$true; uninstall_verified=$true; user_drawing_preserved=$true; clean_other_machine_tested=$false }
$taskReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'test-installer-verification.json') -Encoding UTF8
Write-Output 'PASS: offline installer, shortcuts, generated paths, native GUI/MCP/DWG, safe uninstall.'
