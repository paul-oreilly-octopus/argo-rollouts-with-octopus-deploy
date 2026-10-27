# Runbook "Simulate builds": creates a release of this project every BuildIntervalSeconds
# for BuildDurationMinutes, like a CI pipeline producing builds of the same image.
# Versions are MAJOR.MINOR.BUGFIX-BUILDNUMBER. BUILDNUMBER always increments; then
# 90%: BUGFIX+1, 9%: MINOR+1 and BUGFIX=0, 1%: MAJOR+1 and MINOR=BUGFIX=0.
# Each release snapshots the project's StartColour setting at the time it's created.
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
Write-Host "Starting from $major.$minor.$bugfix-$build; one release every $interval s for $minutes min."

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
Write-Highlight "Created $created releases; latest is $version."
