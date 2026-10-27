# Runbook "Record Argo rollback": the Argo Rollouts webhook (k8s/argo-notifications.yaml) runs
# this when Argo aborts a release. It records the release Argo rolled back to as a record-only
# deployment (ArgoRollback.Triggered=True: nothing is deployed, see check-deployed-version.sh),
# but only if the aborted deployment is still the newest deployment of this project to this
# environment. If a newer one is queued or running, it skips: Octopus queues deployments per
# project and environment, so a record would wait behind it, run after the cluster had moved
# on, and show an old release as current. The newer deployment updates Octopus instead.
# Runbook runs aren't queued behind deployments, so this decides within seconds of the abort.
$ErrorActionPreference = "Stop"

$server = $OctopusParameters["Octopus.Web.ServerUri"].TrimEnd("/")
$space = $OctopusParameters["Octopus.Space.Id"]
$projectId = $OctopusParameters["Octopus.Project.Id"]
$projectName = $OctopusParameters["Octopus.Project.Name"]
$environmentId = $OctopusParameters["Octopus.Environment.Id"]
$environmentName = $OctopusParameters["Octopus.Environment.Name"]
$release = $OctopusParameters["ArgoRollback.Release"]
$abortedRelease = $OctopusParameters["ArgoRollback.AbortedRelease"]
$abortedDeployment = $OctopusParameters["ArgoRollback.AbortedDeployment"]
$reason = $OctopusParameters["ArgoRollback.Reason"]
$headers = @{ "X-Octopus-ApiKey" = $OctopusParameters["ReleaseCreatorApiKey"] }
$api = "$server/api/$space"

Write-Host "Argo Rollouts aborted release $abortedRelease (deployment $abortedDeployment) and rolled back to $release. Reason: $reason"

# The newest deployment task that wasn't cancelled (tasks are listed newest first, queued ones
# included). With the project's "cancel superseded deployments" setting, queued deployments are
# cancelled when a newer one is queued, so cancelled ones never run and don't count.
$tasks = (Invoke-RestMethod "$api/tasks?project=$projectId&environment=$environmentId&name=Deploy&take=20" -Headers $headers).Items
$latest = $tasks | Where-Object { $_.State -ne "Canceled" } | Select-Object -First 1
if ($latest -and $latest.Arguments.DeploymentId -ne $abortedDeployment) {
    Write-Highlight "Skipped: $($latest.Description) ($($latest.Arguments.DeploymentId), $($latest.State)) is newer than the aborted $abortedRelease, so it will show what's running. Not recording $release."
    exit 0
}

$body = @{
    SpaceIdOrName    = $space
    ProjectName      = $projectName
    EnvironmentNames = @($environmentName)
    ReleaseVersion   = $release
    Variables        = @{
        "ArgoRollback.Triggered"      = "True"
        "ArgoRollback.AbortedRelease" = $abortedRelease
        "ArgoRollback.Reason"         = $reason
    }
} | ConvertTo-Json
$created = Invoke-RestMethod "$api/deployments/create/untenanted/v1" -Method Post -Headers $headers -Body $body -ContentType "application/json"
$record = $created.DeploymentServerTasks[0]
Write-Highlight "Recording $release as the current release of $projectName in ${environmentName}: deployment $($record.DeploymentId) ($($record.ServerTaskId))."
