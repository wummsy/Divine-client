<#
.SYNOPSIS
    Tell Windows Defender to leave Divine Client alone, and only Divine Client.

.DESCRIPTION
    An unsigned launcher that downloads a Java runtime, writes an options file and
    runs a child process looks like a generic Trojan to a behaviour-based scanner.
    Rather than asking people to "disable antivirus" - which nobody should do - this
    script adds the three narrow exclusions Defender itself recommends for a trusted
    line-of-business program:

      * the app folder          (where DivineClient.exe and _internal live)
      * the data folder         (%APPDATA%\.divineclient - instances, logs, tunnel agent)
      * DivineClient.exe by name  (so the child processes it starts are not re-scanned)

    It does not switch real-time protection off, does not touch the registry, does
    not add a startup entry, and prints exactly what it changed so you can undo it.
    Run with -Remove to take the exclusions back out.

    If you use another antivirus (Bitdefender, Kaspersky, ESET, Malwarebytes...)
    Defender's cmdlets may be disabled; the script detects that and tells you which
    product is registered, so you know where to add the exclusion instead.

.PARAMETER AppPath
    Folder containing DivineClient.exe. Defaults to this script's folder's parent (the
    way the release zip is laid out), then to the current directory.

.PARAMETER Remove
    Remove the exclusions this script would otherwise add.

.PARAMETER ShowThreats
    List recent Defender detections for these paths - useful for copying the exact
    threat name into a false-positive report.

.EXAMPLE
    .\defender_exclusions.ps1 -ShowThreats
    .\defender_exclusions.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$AppPath,
    [switch]$Remove,
    [switch]$ShowThreats
)

$ErrorActionPreference = 'Stop'
$dataFolder = Join-Path $env:APPDATA '.divineclient'
$exeName    = 'DivineClient.exe'

function Resolve-AppFolder {
    param([string]$Hint)
    $candidates = @()
    if ($Hint) { $candidates += $Hint }
    if ($PSScriptRoot) {
        $candidates += $PSScriptRoot                                  # tools\ in the repo
        $candidates += (Split-Path -Parent $PSScriptRoot)              # repo root
        $candidates += (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\DivineClient')
        $candidates += (Join-Path $PSScriptRoot 'dist\DivineClient')      # beside this script
    }
    $candidates += (Get-Location).Path
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c $exeName))) { return (Resolve-Path $c).Path }
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c -PathType Container)) { return (Resolve-Path $c).Path }
    }
    return $null
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-MpAvailable {
    return $null -ne (Get-Command Get-MpPreference -ErrorAction SilentlyContinue)
}

function Get-RegisteredAv {
    try {
        Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct `
            -ErrorAction Stop |
            Select-Object -ExpandProperty displayName
    } catch { @() }
}

$appFolder = Resolve-AppFolder -Hint $AppPath

Write-Host ''
Write-Host '  Divine Client - antivirus exclusion helper' -ForegroundColor Cyan
Write-Host '  -----------------------------------------' -ForegroundColor DarkGray
Write-Host "  app folder : $(if ($appFolder) { $appFolder } else { 'not found' })"
Write-Host "  data folder: $dataFolder"
Write-Host "  process    : $exeName"
Write-Host ''

if (-not (Test-IsAdmin)) {
    Write-Host '  Administrator rights are required to change Defender settings.' -ForegroundColor Yellow
    Write-Host '  Re-run add_defender_exclusions.bat and accept the UAC prompt, or'
    Write-Host '  open PowerShell as Administrator and run:'
    Write-Host "      .\defender_exclusions.ps1 -AppPath `"$appFolder`""
    Write-Host ''
    exit 2
}

if (-not (Get-MpAvailable)) {
    $av = @(Get-RegisteredAv)
    Write-Host '  Windows Defender cmdlets are not available on this machine, so this' -ForegroundColor Yellow
    Write-Host '  script cannot add exclusions here.'
    if ($av.Count) {
        Write-Host "  Active protection is provided by: $($av -join ', ')." -ForegroundColor Yellow
        Write-Host '  Add the two folders above to that product''s exclusion list instead'
        Write-Host '  (usually under Settings > Protection > Exceptions / Exclusions).'
    } else {
        Write-Host '  Defender may be turned off by group policy or a third-party product.'
    }
    Write-Host ''
    exit 3
}

try {
    $pref = Get-MpPreference
} catch {
    Write-Host "  Could not read the Defender configuration: $_" -ForegroundColor Red
    exit 4
}

if ($ShowThreats) {
    Write-Host '  Recent Defender detections (name + path) - copy these into a report:' -ForegroundColor Cyan
    try {
        $threats = @(Get-MpThreatDetection -ErrorAction SilentlyContinue |
            Sort-Object InitialDetectionTime -Descending | Select-Object -First 12)
        if (-not $threats.Count) { Write-Host '    (nothing recorded)' -ForegroundColor DarkGray }
        foreach ($t in $threats) {
            $bad = $false
            foreach ($p in @($t.Resources)) {
                if ($p -like '*aren*' -or $p -like '*\.divineclient\*') { $bad = $true }
            }
            $colour = if ($bad) { 'Yellow' } else { 'Gray' }
            Write-Host ("    {0}  {1}  {2}" -f $t.InitialDetectionTime, $t.ThreatID, `
                (($t.Resources | Select-Object -First 1) -replace '^.*file=', '')) -ForegroundColor $colour
        }
        $names = @(Get-MpThreat -ErrorAction SilentlyContinue |
            Where-Object { $_.ThreatName -and $_.ActiveExecutions } |
            Select-Object -ExpandProperty ThreatName -Unique)
        if ($names.Count) { Write-Host "  names seen: $($names -join ', ')" -ForegroundColor DarkGray }
    } catch {
        Write-Host "  Get-MpThreatDetection failed: $_" -ForegroundColor Yellow
        Write-Host '  Open Windows Security > Protection history to see the same list.'
    }
    Write-Host ''
}

$pathsBefore = @($pref.ExclusionPath)
$procBefore  = @($pref.ExclusionProcess)

if ($Remove) {
    Write-Host '  Removing the exclusions this helper added...' -ForegroundColor Cyan
    $dropPaths = @(@($appFolder, $dataFolder) | Where-Object { $_ })
    try {
        Remove-MpPreference -ExclusionPath $dropPaths -ExclusionProcess $exeName
    } catch {
        # Older builds have no Remove-MpPreference for every setting: rebuild the
        # lists without our entries instead.
        $keepPaths = @($pathsBefore | Where-Object { $_ -and ($dropPaths -notcontains $_) })
        $keepProc  = @($procBefore | Where-Object { $_ -and ($_ -ne $exeName) })
        try { Set-MpPreference -ExclusionPath $keepPaths -ExclusionProcess $keepProc } catch {
            Write-Host "  Could not rewrite the exclusion list: $_" -ForegroundColor Yellow
            Write-Host '  Remove them by hand: Windows Security > Virus & threat protection'
            Write-Host '  > Manage settings > Exclusions.'
        }
    }
    Write-Host '  Done. Nothing else about your protection settings was changed.'
    Write-Host ''
    exit 0
}

$scheme = @()
foreach ($p in @($appFolder, $dataFolder)) {
    if (-not $p) { continue }
    if ($pathsBefore -contains $p) {
        $scheme += "  = path already excluded : $p"
    } else {
        $scheme += "  + add path              : $p"
    }
}
$scheme += if ($procBefore -contains $exeName) {
    "  = process already excluded: $exeName"
} else {
    "  + add process             : $exeName"
}
Write-Host '  Planned changes:' -ForegroundColor Cyan
$scheme | ForEach-Object { Write-Host $_ }

# Add-MpPreference appends, so hand it only the entries that are genuinely missing
# - otherwise re-running this helper would pile duplicates into the list.
$addPaths = @(@($appFolder, $dataFolder) | Where-Object { $_ -and ($pathsBefore -notcontains $_) })

try {
    if ($addPaths.Count) { Add-MpPreference -ExclusionPath $addPaths -ErrorAction Stop }
    if ($procBefore -notcontains $exeName) {
        Add-MpPreference -ExclusionProcess $exeName -ErrorAction Stop
    }
} catch {
    Write-Host "  Defender refused: $_" -ForegroundColor Red
    Write-Host '  If it is managed by your organisation, only the IT policy can add'
    Write-Host '  exclusions - ask them, or run Divine Client on a machine you own.'
    exit 5
}

$after = Get-MpPreference
Write-Host ''
Write-Host '  Exclusions now set (paths):' -ForegroundColor Green
@($after.ExclusionPath) | ForEach-Object { Write-Host "    $_" }
Write-Host '  Exclusions now set (processes):' -ForegroundColor Green
@($after.ExclusionProcess) | ForEach-Object { Write-Host "    $_" }
Write-Host ''
Write-Host '  If DivineClient.exe was already quarantined, an exclusion alone will not' -ForegroundColor Yellow
Write-Host '  bring it back: Windows Security > Protection history > Allow on device,'
Write-Host '  or re-extract the zip after adding the exclusion.'
Write-Host ''
Write-Host '  This helper changes nothing else - no registry Run key, no firewall'
Write-Host '  rule, no real-time protection toggle. Undo with -Remove at any time.'
Write-Host ''
exit 0
