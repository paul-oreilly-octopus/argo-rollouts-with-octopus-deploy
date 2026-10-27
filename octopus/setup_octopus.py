#!/usr/bin/env python3
"""Creates or updates the Colour Demo projects in the demo's Octopus space (OCTOPUS_SPACE_NAME).

Safe to re-run: each project's deployment process, variables, deployment settings and
runbooks ("Simulate builds", "Record Argo rollback") are replaced with what's defined here
and in the files alongside this script. The runbooks use the same API key
(sensitive variable ReleaseCreatorApiKey), updated on every run so a new key takes effect.
"""
import sys
from datetime import datetime

from config import SETTINGS
from octopus_api import HERE, PROJECTS, SPACE, SPACE_NAME, api, api_key, find_by_name

PROJECT_GROUP = "Argo Rollouts Demo"
LIFECYCLE = "Default Lifecycle"
TARGET_TAG = SETTINGS["OCTOPUS_TARGET_TAG"]
DEFAULT_WORKER_POOL = "Hosted Ubuntu"  # Octopus Cloud's dynamic Linux workers
RUNBOOK = "Simulate builds"
RECORD_RUNBOOK = "Record Argo rollback"
RUNBOOKS = {
    RUNBOOK: ("simulate-builds.ps1", "Create releases",
              "Creates a new release every N seconds for M minutes, versioned "
              "MAJOR.MINOR.BUGFIX-BUILD, to simulate a CI pipeline producing builds."),
    RECORD_RUNBOOK: ("record-argo-rollback.ps1", "Record or skip",
                     "Run by the Argo Rollouts webhook when Argo aborts a release. Records the release Argo "
                     "rolled back to as a record-only deployment, unless a newer deployment is already "
                     "queued or running."),
}
IMAGE = "colour-demo:1.1.0"
FAIL_COLOUR = "red"
START_COLOURS = [
    ("random-without-red", "Random, never red"),
    ("random-with-red", "Random, sometimes red (some releases get rolled back)"),
    ("red", "Red (fails analysis: automatic rollback)"),
    ("blue", "Blue"), ("green", "Green"), ("teal", "Teal"), ("yellow", "Yellow"),
    ("orange", "Orange"), ("pink", "Pink"), ("purple", "Purple"),
]

DEMOS = {
    "canary": {
        "rollout": "colour-canary",
        "yaml": "rollout-canary.yaml",
        "services": "stable canary",
        "description": "Argo Rollouts canary (25/50/75%) with background analysis. "
                       "A red canary pod makes Argo abort and roll back automatically.",
        "variables": {"PauseDuration": "45s"},
        "prompts": {"PauseDuration": ("Pause between canary steps",
                                      "How long Argo pauses at 25%, 50% and 75%, e.g. 45s or 5s.")},
    },
    "bluegreen": {
        "rollout": "colour-bluegreen",
        "yaml": "rollout-bluegreen.yaml",
        "services": "active preview",
        "description": "Argo Rollouts blue-green with pre- and post-promotion analysis. "
                       "A red preview/new pod makes Argo abort and roll back automatically.",
        "variables": {"AnalysisCount": "10"},
        "prompts": {"AnalysisCount": ("Analysis checks",
                                      "Health checks (5s apart) before and after promotion, e.g. 10 or 4.")},
    },
}


def read(name):
    return (HERE / name).read_text()


CHECK_STEP = "Check deployed version"
NEEDS_DEPLOY = f"#{{Octopus.Action[{CHECK_STEP}].Output.NeedsDeploy}}"
NOT_ARGO_TRIGGERED = '#{if ArgoRollback.Triggered == "True"}False#{else}True#{/if}'


def step(name, action_type, properties, target_tag=None, worker_pool_id=None, run_if=None):
    action = {
        "Name": name,
        "ActionType": action_type,
        "IsDisabled": False,
        "IsRequired": False,
        "Condition": "Success",
        "Environments": [],
        "ExcludedEnvironments": [],
        "Channels": [],
        "TenantTags": [],
        "Packages": [],
        "Properties": {"Octopus.Action.RunOnServer": "false" if target_tag else "true", **properties},
    }
    if worker_pool_id:
        action["WorkerPoolId"] = worker_pool_id
    step_properties = {"Octopus.Action.TargetRoles": target_tag} if target_tag else {}
    if run_if:  # run only when this variable expression is truthy
        step_properties["Octopus.Step.ConditionVariableExpression"] = run_if
    return {
        "Name": name,
        "Condition": "Variable" if run_if else "Success",
        "StartTrigger": "StartAfterPrevious",
        "PackageRequirement": "LetOctopusDecide",
        "Properties": step_properties,
        "Actions": [action],
    }


def script_properties(script, syntax):
    return {
        "Octopus.Action.Script.ScriptSource": "Inline",
        "Octopus.Action.Script.Syntax": syntax,
        "Octopus.Action.Script.ScriptBody": script,
    }


def kubectl_step(name, script, run_if=None):
    return step(name, "Octopus.KubernetesRunScript", script_properties(script, "Bash"),
                target_tag=TARGET_TAG, run_if=run_if)


def yaml_step(name, yaml, run_if=None):
    return step(name, "Octopus.KubernetesDeployRawYaml", {
        "Octopus.Action.Script.ScriptSource": "Inline",
        "Octopus.Action.KubernetesContainers.CustomResourceYaml": yaml,
        "Octopus.Action.KubernetesContainers.Namespace": "#{Namespace}",
        "Octopus.Action.Kubernetes.ResourceStatusCheck": "False",
        "Octopus.Action.Kubernetes.ServerSideApply.Enabled": "True",
        "Octopus.Action.Kubernetes.ServerSideApply.ForceConflicts": "True",
    }, target_tag=TARGET_TAG, run_if=run_if)


def var(name, value, prompt=None, scope=None, sensitive=False):
    return {"Name": name, "Value": value, "Type": "Sensitive" if sensitive else "String",
            "IsSensitive": sensitive, "Scope": scope or {}, "Prompt": prompt}


def prompt(label, description, options=None, required=True):
    display = {"Octopus.ControlType": "Select", "Octopus.SelectOptions": "\n".join(f"{v}|{t}" for v, t in options)} \
        if options else {"Octopus.ControlType": "SingleLineText"}
    return {"Label": label, "Description": description, "Required": required, "DisplaySettings": display}


def variables(settings, runbooks, api_key_var):
    runbook_scope = {"ProcessOwner": [runbooks[RUNBOOK]["Id"]]}
    record_scope = {"ProcessOwner": [runbooks[RECORD_RUNBOOK]["Id"]]}
    prompts = settings.get("prompts", {})
    return [
        var("RolloutName", settings["rollout"]),
        var("Namespace", f"{settings['rollout']}-#{{Octopus.Environment.Name | ToLower}}"),
        var("ServiceSuffixes", settings["services"]),
        var("Image", IMAGE),
        var("FailColour", FAIL_COLOUR),
        var("StartColour", "random-without-red", prompt(
            "Start colour",
            "Colour new pods start with. Releases snapshot this value when they're created, so change it "
            "here to control releases created from now on (including by the Simulate builds runbook). "
            f"Any pod starting {FAIL_COLOUR} fails the Argo Rollouts analysis and triggers an automatic rollback.",
            START_COLOURS, required=False)),  # optional, so API deployments (the Argo webhook) use the release's value
        var("RolloutTimeoutSeconds", "900"),
        *(var(k, v, prompt(*prompts[k], required=False) if k in prompts else None)
          for k, v in settings["variables"].items()),
        # Set when the Record Argo rollback runbook deploys the release Argo rolled back to.
        # Any step can use them, e.g. as a run condition: #{ArgoRollback.Triggered}
        var("ArgoRollback.Triggered", "False", prompt(
            "Argo rollback: triggered", "True when Argo Rollouts aborted a release and this deployment records "
            "the release it rolled back to. Set by the Record Argo rollback runbook; leave False for normal "
            "deployments.", [("False", "False"), ("True", "True")], required=False)),
        var("ArgoRollback.AbortedRelease", "", prompt(
            "Argo rollback: aborted release", "Set by the Argo Rollouts webhook: the release Argo aborted.",
            required=False)),
        var("ArgoRollback.Reason", "", prompt(
            "Argo rollback: reason", "Set by the Argo Rollouts webhook: Argo's abort message.", required=False)),
        # Only the Record Argo rollback runbook's run needs these (the Argo Rollouts webhook sets them).
        var("ArgoRollback.Release", "", prompt(
            "Argo rollback: release", "The release Argo rolled back to.", required=False), record_scope),
        var("ArgoRollback.AbortedDeployment", "", prompt(
            "Argo rollback: aborted deployment", "The Octopus deployment Argo aborted, e.g. Deployments-123.",
            required=False), record_scope),
        var("BuildIntervalSeconds", "2", prompt(
            "Build interval (seconds)", "How often to create a new release.", required=True), runbook_scope),
        var("BuildDurationMinutes", "30", prompt(
            "Run for (minutes)", "How long to keep creating releases.", required=True), runbook_scope),
        api_key_var,
    ]


def ensure_runbook(project, worker_pool_id, name):
    script, step_name, description = RUNBOOKS[name]
    runbooks = api("GET", f"{SPACE}/projects/{project['Id']}/runbooks")["Items"]
    runbook = next((r for r in runbooks if r["Name"] == name), None)
    if runbook is None:
        runbook = api("POST", f"{SPACE}/runbooks", {
            "Name": name,
            "ProjectId": project["Id"],
            "Description": description,
            "EnvironmentScope": "All",
            "RunRetentionPolicy": {"QuantityToKeep": 100, "ShouldKeepForever": False},
        })
        print(f"  created runbook {name} ({runbook['Id']})")
    process = api("GET", runbook["Links"]["RunbookProcesses"])
    process["Steps"] = [step(step_name, "Octopus.Script", script_properties(read(script), "PowerShell"),
                             worker_pool_id=worker_pool_id)]
    api("PUT", runbook["Links"]["RunbookProcesses"], process)
    return runbook


def publish_runbook(runbook):
    snapshot = api("POST", f"{SPACE}/runbookSnapshots?publish=true", {
        "ProjectId": runbook["ProjectId"], "RunbookId": runbook["Id"],
        "Name": f"{runbook['Name']} {datetime.now():%Y-%m-%d %H:%M:%S}"})  # unique per project
    print(f"  published runbook snapshot {snapshot['Name']}")


def ensure_project(key, settings, group_id, lifecycle_id, worker_pool_id):
    name = PROJECTS[key]
    project = find_by_name("projects", name)
    if project is None:
        project = api("POST", f"{SPACE}/projects", {
            "Name": name, "Description": settings["description"],
            "ProjectGroupId": group_id, "LifecycleId": lifecycle_id})
        print(f"Created project {name} ({project['Id']})")
    else:
        print(f"Updating project {name} ({project['Id']})")

    process = api("GET", project["Links"]["DeploymentProcess"])
    process["Steps"] = [
        kubectl_step("Prepare namespace", read("prepare-namespace.sh"), run_if=NOT_ARGO_TRIGGERED),
        kubectl_step(CHECK_STEP, read("check-deployed-version.sh")),
        yaml_step("Apply Rollout", read(settings["yaml"]), run_if=NEEDS_DEPLOY),
        kubectl_step("Wait for Argo Rollout", read("wait-for-rollout.sh"), run_if=NEEDS_DEPLOY),
    ]
    api("PUT", project["Links"]["DeploymentProcess"], process)

    # Cancel superseded deployments: queuing a deployment cancels older ones still queued, so
    # with rapid deployments Octopus only ever runs the newest (see docs/how-it-works.md).
    deployment_settings = api("GET", f"{SPACE}/projects/{project['Id']}/deploymentsettings")
    if "CancelQueuedTasks" in deployment_settings:
        deployment_settings.update(CancelQueuedTasks=True, CancelRunningTasks=True)
        api("PUT", f"{SPACE}/projects/{project['Id']}/deploymentsettings", deployment_settings)
    else:
        print("  note: this Octopus version can't cancel superseded deployments; rapid deployments will queue")

    runbooks = {name: ensure_runbook(project, worker_pool_id, name) for name in RUNBOOKS}

    variable_set = api("GET", project["Links"]["Variables"])
    key_scope = {"ProcessOwner": [r["Id"] for r in runbooks.values()]}
    api_key_var = var("ReleaseCreatorApiKey", api_key(), scope=key_scope, sensitive=True)
    variable_set["Variables"] = variables(settings, runbooks, api_key_var)
    api("PUT", project["Links"]["Variables"], variable_set)

    for runbook in runbooks.values():
        publish_runbook(runbook)


def worker_pool():
    """OCTOPUS_WORKER_POOL, else Hosted Ubuntu (Octopus Cloud), else the space's default pool."""
    pools = api("GET", f"{SPACE}/workerpools/all")
    wanted = SETTINGS["OCTOPUS_WORKER_POOL"]
    pool = next((p for p in pools if p["Name"] == (wanted or DEFAULT_WORKER_POOL)), None)
    if pool is None and wanted:
        sys.exit(f'Worker pool "{wanted}" (OCTOPUS_WORKER_POOL) not found in space {SPACE_NAME}.')
    pool = pool or next((p for p in pools if p.get("IsDefault")), None)
    if pool is None:
        sys.exit("No worker pool found for the runbooks: set OCTOPUS_WORKER_POOL.")
    print(f"Runbooks run on worker pool {pool['Name']}")
    return pool


def main():
    group = find_by_name("projectgroups", PROJECT_GROUP) or api("POST", f"{SPACE}/projectgroups", {
        "Name": PROJECT_GROUP, "Description": "Colour demo projects driven by Argo Rollouts on a local kind cluster."})
    lifecycle = find_by_name("lifecycles", LIFECYCLE)
    if lifecycle is None:
        sys.exit(f'Lifecycle "{LIFECYCLE}" not found in space {SPACE_NAME}: run octopus/setup_space.py first.')
    pool = worker_pool()

    for key, settings in DEMOS.items():
        ensure_project(key, settings, group["Id"], lifecycle["Id"], pool["Id"])


if __name__ == "__main__":
    main()
