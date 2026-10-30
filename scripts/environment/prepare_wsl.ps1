param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = 'Stop'
$result = [ordered]@{
    started_at = [DateTime]::UtcNow.ToString('o')
    status = 'running'
    reboot_required = $false
    runtime_installer_exit = $null
}
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$resultPath = Join-Path $LogDirectory 'wsl-provision-result.json'

try {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator authorization is required to prepare WSL.'
    }
    $package = (Resolve-Path -LiteralPath $InstallerPath).Path
    $hash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash
    if ($hash -ne $ExpectedSha256) { throw 'The WSL installer does not match the verified release hash.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $package
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        throw 'The WSL installer publisher could not be verified.'
    }
    $result.installer_sha256 = $hash
    $result.publisher = $signature.SignerCertificate.Subject

    $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    $result.virtual_machine_platform_before = $feature.State.ToString()
    if ($feature.State -eq 'EnablePending') {
        $result.reboot_required = $true
    } elseif ($feature.State -ne 'Enabled') {
        $enabled = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
        $result.reboot_required = [bool]$enabled.RestartNeeded
    }

    $msiLog = Join-Path $LogDirectory 'wsl-msi.log'
    $arguments = '/i "{0}" /qn /norestart /L*v "{1}"' -f $package, $msiLog
    $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    $result.runtime_installer_exit = $process.ExitCode
    if ($process.ExitCode -notin @(0, 3010)) { throw "WSL installer failed with exit code $($process.ExitCode)." }
    if ($process.ExitCode -eq 3010) { $result.reboot_required = $true }
    $result.virtual_machine_platform_after = (Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State.ToString()
    $result.status = if ($result.reboot_required) { 'installed_reboot_required' } else { 'installed' }
} catch {
    $result.status = 'failed'
    $result.error = $_.Exception.Message
} finally {
    $result.finished_at = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}

if ($result.status -eq 'failed') { exit 1 }
exit 0
