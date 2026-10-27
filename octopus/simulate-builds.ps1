# Runbook "Simulate builds": creates a release of this project every BuildIntervalSeconds
# for BuildDurationMinutes, like a CI pipeline producing builds of the same image.
# Versions are MAJOR.MINOR.BUGFIX-BUILDNUMBER. BUILDNUMBER always increments; then
# 90%: BUGFIX+1, 9%: MINOR+1 and BUGFIX=0, 1%: MAJOR+1 and MINOR=BUGFIX=0.
# Each release snapshots the project's StartColour setting at the time it's created, so when
# the run's "Start colour" prompt differs from the project's setting, the run sets the project's
# value for its duration (releases created by anyone meanwhile get it too), then puts it back.
$ErrorActionPreference = "Stop"

$server = $OctopusParameters["Octopus.Web.ServerUri"].TrimEnd("/")
$space = $OctopusParameters["Octopus.Space.Id"]
$projectId = $OctopusParameters["Octopus.Project.Id"]
$runId = $OctopusParameters["Octopus.RunbookRun.Id"]
$interval = [double]$OctopusParameters["BuildIntervalSeconds"]
$minutes = [double]$OctopusParameters["BuildDurationMinutes"]
$headers = @{ "X-Octopus-ApiKey" = $OctopusParameters["ReleaseCreatorApiKey"] }
$api = "$server/api/$space"

# Continue from the highest build number among recent MAJOR.MINOR.BUGFIX-BUILD releases
# (versions only ever go up, so the highest is always among the newest).
$pattern = '^(\d+)\.(\d+)\.(\d+)-(\d+)$'
$major, $minor, $bugfix, $build = 1, 0, 0, 0
foreach ($release in (Invoke-RestMethod "$api/projects/$projectId/releases?take=100" -Headers $headers).Items) {
    if ($release.Version -match $pattern -and [int]$Matches[4] -gt $build) {
        $major, $minor, $bugfix, $build = [int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4]
    }
}
$channelId = (Invoke-RestMethod "$api/projects/$projectId/channels" -Headers $headers).Items[0].Id

# Sets the project's unscoped StartColour to $to, if it's currently $from (or $from is $null).
# Returns the value it replaced, or $null if it changed nothing.
$variablesUrl = "$api/variables/$((Invoke-RestMethod "$api/projects/$projectId" -Headers $headers).VariableSetId)"
function Set-StartColour($to, $from) {
    $set = Invoke-RestMethod $variablesUrl -Headers $headers
    $variable = $set.Variables | Where-Object { $_.Name -eq "StartColour" -and -not ($_.Scope.PSObject.Properties | Select-Object -First 1) } | Select-Object -First 1
    if (-not $variable -or $variable.Value -eq $to -or ($null -ne $from -and $variable.Value -ne $from)) { return $null }
    $old = $variable.Value
    $variable.Value = $to
    # Sensitive values come back as null, and Octopus keeps a sensitive variable's value when it's sent as null.
    Invoke-RestMethod $variablesUrl -Method Put -Headers $headers -Body ($set | ConvertTo-Json -Depth 20) -ContentType "application/json" | Out-Null
    return $old
}
$startColour = $OctopusParameters["StartColour"]
$replaced = $null
if ($startColour) {
    $replaced = Set-StartColour $startColour $null
    if ($null -ne $replaced) { Write-Host "Start colour for this run's releases: $startColour (the project's setting, $replaced, is restored at the end)." }
    else { Write-Host "Start colour for this run's releases: $startColour." }
}
Write-Host "Starting from $major.$minor.$bugfix-$build; one release every $interval s for $minutes min."

try {
$deadline = (Get-Date).AddMinutes($minutes)
$created = 0
$version = $null
while ((Get-Date) -lt $deadline) {
    $tick = Get-Date
    $build++
    $roll = Get-Random -Minimum 0 -Maximum 100
    if ($roll -lt 1) { $major++; $minor = 0; $bugfix = 0; $kind = "major" }
    elseif ($roll -lt 10) { $minor++; $bugfix = 0; $kind = "minor" }
    else { $bugfix++; $kind = "bugfix" }
    $candidate = "$major.$minor.$bugfix-$build"

    $body = @{
        ProjectId    = $projectId
        ChannelId    = $channelId
        Version      = $candidate
        ReleaseNotes = "Simulated $kind build $build, created by runbook run $runId."
    } | ConvertTo-Json
    try {
        Invoke-RestMethod "$api/releases" -Method Post -Headers $headers -Body $body -ContentType "application/json" | Out-Null
        $created++
        $version = $candidate
        Write-Host "Created release $candidate ($kind)"
    } catch {
        Write-Warning "Failed to create release ${candidate}: $($_.Exception.Message)"
    }

    $remaining = $interval - ((Get-Date) - $tick).TotalSeconds
    if ($remaining -gt 0) { Start-Sleep -Milliseconds ([int]($remaining * 1000)) }
}
} finally {
    # Put the project's setting back, unless someone changed it during the run.
    if ($null -ne $replaced -and $null -ne (Set-StartColour $replaced $startColour)) {
        Write-Host "Restored the project's Start colour setting to $replaced."
    }
}
Write-Highlight "Created $created releases with start colour $startColour; latest is $version."
