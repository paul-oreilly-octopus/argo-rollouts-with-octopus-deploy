#!/usr/bin/env python3
"""Rapid-deployment stress test of the Argo rollback recording.

Creates and deploys a release every --interval seconds for --minutes (faster than a
deployment takes, so Octopus queues them, and with "cancel superseded deployments" on,
cancels all but the newest queued one), with StartColour random-with-red so Argo aborts
some, and the last one red so the run ends with an abort. With --chase, one more deployment
is queued the moment the runbook creates its record, racing it. Then waits for everything
to settle and checks:
  - each Argo abort ran the Record Argo rollback runbook exactly once;
  - every deployment succeeded, was aborted by Argo, or was superseded;
  - every record-only deployment succeeded or was superseded (never ran stale);
  - Octopus's latest deployment succeeded and is the release the cluster actually runs.

  ./stress_test.py                                   # canary, every 5s for 2 min, 5s canary pauses
  ./stress_test.py --interval 10 --minutes 1 --pause 10s --chase
  ./stress_test.py bluegreen --chase                 # blue-green, 4 analysis checks per window
  ./stress_test.py --cycle 5 --minutes 3 --chase     # 5 good, 5 red, 5 good, ... (last one red)

It also tracks which release should be stable (the last one that succeeded: Argo only falls
back to a release that completed its rollout), and checks it against what each deployment's
check step saw in the cluster and the release Argo told the runbook it rolled back to.
"""
import argparse
import datetime
import re
import sys
import time

from config import SETTINGS
from deploy import create_release
from octopus_api import PROJECTS, SERVER, SPACE, api, find_by_name, kubectl

RECORD_RUNBOOK = "Record Argo rollback"


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_time(value):
    return datetime.datetime.fromisoformat(value) if value else None


def deploy(project, environment, colour, speed):
    release = create_release(project)
    snapshot = api("GET", f"{SPACE}/variables/{release['ProjectVariableSetSnapshotId']}")["Variables"]
    values = {"StartColour": colour, **speed}
    form = {v["Id"]: values[v["Name"]] for v in snapshot if v["Name"] in values and v.get("Prompt")}
    deployment = api("POST", f"{SPACE}/deployments", {
        "ReleaseId": release["Id"], "EnvironmentId": environment["Id"], "FormValues": form})
    return {"id": deployment["Id"], "task": deployment["TaskId"], "release": release["Version"], "colour": colour}


def superseded(task):
    return task["State"] == "Canceled" and (task.get("ErrorMessage") or "").strip().startswith("Superseded")


def active_tasks(project, environment):
    return api("GET", f"{SPACE}/tasks?project={project['Id']}&environment={environment['Id']}&active=true&take=100")["Items"]


_logs = {}


def raw_log(task_id):
    if task_id not in _logs:
        _logs[task_id] = api("GET", f"{SPACE}/tasks/{task_id}/raw", raw=True)
    return _logs[task_id]


def highlights(task_id):
    return [line.split("|", 1)[-1].strip() for line in raw_log(task_id).splitlines() if "Highlight" in line]


def colour_for(i, count, args):
    if i == count - 1 and args.final_colour:
        return args.final_colour
    if args.cycle:  # N good, N red, N good, ...
        return "random-without-red" if (i // args.cycle) % 2 == 0 else "red"
    return args.colour


def cluster_release(namespace, name):
    def get(*args):
        return kubectl("-n", namespace, "get", *args, check=False)
    stable = get("rollout", name, "-o", "jsonpath={.status.stableRS}")
    phase = get("rollout", name, "-o", "jsonpath={.status.phase}")
    release = get("rs", f"{name}-{stable}", "-o", r"jsonpath={.spec.template.metadata.annotations.octopus\.com/release}")
    return release, phase


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default="canary", choices=PROJECTS)
    parser.add_argument("--env", default=SETTINGS["OCTOPUS_DEMO_ENVIRONMENT"])
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--minutes", type=float, default=2)
    parser.add_argument("--pause", default="5s", help="canary: PauseDuration between steps (default 5s)")
    parser.add_argument("--analysis-count", default="4",
                        help="blue-green: AnalysisCount checks before and after promotion (default 4)")
    parser.add_argument("--colour", default="random-with-red")
    parser.add_argument("--cycle", type=int, metavar="N",
                        help="instead of --colour: N good (random-without-red), then N red, repeating")
    parser.add_argument("--final-colour", default="red", help="StartColour of the last deployment ('' for none)")
    parser.add_argument("--settle", type=int, default=60, help="seconds with nothing active before checking")
    parser.add_argument("--chase", action="store_true",
                        help="deploy once more (never red) as soon as the runbook creates a record")
    args = parser.parse_args()

    project = find_by_name("projects", PROJECTS[args.project])
    environment = find_by_name("environments", args.env)
    runbook = next(r for r in api("GET", f"{SPACE}/projects/{project['Id']}/runbooks")["Items"]
                   if r["Name"] == RECORD_RUNBOOK)
    speed = {"PauseDuration": args.pause} if args.project == "canary" else {"AnalysisCount": args.analysis_count}
    rollout = f"colour-{args.project}"
    namespace = f"{rollout}-{args.env.lower()}"
    initial_stable, _ = cluster_release(namespace, rollout)
    if not initial_stable:
        sys.exit(f"Rollout {rollout} isn't running in {namespace} yet: deploy {project['Name']} once first "
                 f"(./octopus/deploy.py {args.project}).")
    start = now()
    count = max(1, int(args.minutes * 60 / args.interval))
    colours = f"{args.cycle} good / {args.cycle} red cycle" if args.cycle else f"StartColour {args.colour}"
    print(f"{start:%H:%M:%S} Deploying {count} releases of {project['Name']}, one every {args.interval}s "
          f"({colours}, last one {args.final_colour or 'as the pattern'}; "
          + ", ".join(f"{k} {v}" for k, v in speed.items()) + f"); cluster runs {initial_stable}")

    ours = []
    for i in range(count):
        tick = time.monotonic()
        colour = colour_for(i, count, args)
        ours.append(deploy(project, environment, colour, speed))
        print(f"  {now():%H:%M:%S} {ours[-1]['release']} {ours[-1]['id']} ({colour})")
        time.sleep(max(0.0, args.interval - (time.monotonic() - tick)))

    if args.chase:
        print(f"{now():%H:%M:%S} Waiting for the runbook to create a record, to deploy straight after it ...")
        our_ids = {d["id"] for d in ours}
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            latest = api("GET", f"{SPACE}/deployments?projects={project['Id']}"
                                f"&environments={environment['Id']}&take=1")["Items"][0]
            if latest["Id"] not in our_ids:
                ours.append({**deploy(project, environment, "random-without-red", speed), "colour": "chase"})
                print(f"  {now():%H:%M:%S} record {latest['Id']} created; chased it with "
                      f"{ours[-1]['release']} {ours[-1]['id']}")
                break
            time.sleep(1)

    print(f"{now():%H:%M:%S} All queued; waiting until nothing is active for {args.settle}s ...")
    quiet_since = None
    while True:
        active = active_tasks(project, environment)
        if active:
            quiet_since = None
            print(f"  {now():%H:%M:%S} {len(active)} active: {', '.join(t['Description'][:40] for t in active[:3])}")
            time.sleep(15)
            continue
        quiet_since = quiet_since or time.monotonic()
        if time.monotonic() - quiet_since >= args.settle:
            break
        time.sleep(5)

    # Everything this run produced: our deployments, the runbook runs and the records they created.
    deployments = [d for d in api("GET", f"{SPACE}/deployments?projects={project['Id']}"
                                         f"&environments={environment['Id']}&take=200")["Items"]
                   if parse_time(d["Created"]) >= start]
    tasks = {d["TaskId"]: api("GET", f"{SPACE}/tasks/{d['TaskId']}") for d in deployments}
    runs = [t for t in api("GET", f"{SPACE}/tasks?runbook={runbook['Id']}&take=200")["Items"]
            if parse_time(t["QueueTime"]) >= start]
    our_ids = {d["id"] for d in ours}
    releases = {d["ReleaseId"]: api("GET", f"{SPACE}/releases/{d['ReleaseId']}")["Version"]
                for d in deployments if d["Id"] not in our_ids}

    # Runbook runs: which aborted deployment each was about, and what it decided.
    run_for = {}
    for run in runs:
        log = raw_log(run["Id"])
        aborted = re.search(r"\(deployment (Deployments-\d+)\)", log)
        rolled_back_to = re.search(r"and rolled back to (\S+?)\. Reason", log)
        decision = next((h for h in highlights(run["Id"])), f"no decision ({run['State']})")
        record = re.search(r"deployment (Deployments-\d+) \(", decision) if decision.startswith("Recording") else None
        run_for.setdefault(aborted.group(1) if aborted else "?", []).append(
            {"run": run, "decision": decision, "record": record.group(1) if record else None,
             "rolled_back_to": rolled_back_to.group(1) if rolled_back_to else "?"})

    # Argo only falls back to the stable ReplicaSet: the last release that completed its rollout.
    # Track what that should be, and compare it with what each deployment's check step saw in the
    # cluster and with the release Argo told the runbook it rolled back to.
    expected_stable = initial_stable
    problems = []
    print(f"\nStable at the start: {initial_stable}")
    print(f"{'release':<14}{'colour':<20}{'queued':<10}{'started':<10}{'done':<10}{'result':<11}"
          f"{'stable seen':<13}runbook")
    for d in ours:
        task = tasks[d["task"]]
        aborted = task["State"] == "Failed" and any("aborted" in h for h in highlights(d["task"]))
        result = "aborted" if aborted else "superseded" if superseded(task) else task["State"]
        entries = run_for.get(d["id"], [])
        seen = ""
        if task["StartTime"]:
            match = re.search(r"Cluster: stable=(\S+) ", raw_log(d["task"]))
            seen = match.group(1) if match else "?"
            if seen != expected_stable:
                problems.append(f"{d['release']} saw stable {seen} in the cluster; expected {expected_stable}")
            for e in entries:
                if e["rolled_back_to"] != expected_stable:
                    problems.append(f"Argo rolled {d['release']} back to {e['rolled_back_to']}; "
                                    f"expected {expected_stable}")
            if result == "Success":
                expected_stable = d["release"]
        if aborted and len(entries) != 1:
            problems.append(f"{d['release']} was aborted but ran the runbook {len(entries)} times")
        if not aborted and entries:
            problems.append(f"{d['release']} wasn't aborted but ran the runbook")
        if result not in ("Success", "aborted", "superseded"):
            problems.append(f"{d['release']} ended {task['State']} without an Argo abort")
        decision = "; ".join(e["decision"].split(":")[0] + (f" -> {e['record']}" if e["record"] else "")
                             for e in entries)
        times = [parse_time(task[k]) for k in ("QueueTime", "StartTime", "CompletedTime")]
        print(f"{d['release']:<14}{d['colour']:<20}" + "".join(f"{t:%H:%M:%S}  " if t else "-         " for t in times)
              + f"{result:<11}{seen:<13}{decision}")
        for e in entries:
            if aborted:
                lag = parse_time(e["run"]["StartTime"]) - times[2]
                print(f"{'':<14}runbook {e['run']['Id']} started {lag.total_seconds():+.0f}s after the deployment "
                      f"failed, took {e['run']['Duration']}: {e['decision']}")

    records = [d for d in deployments if d["Id"] not in our_ids]
    print(f"\nRecord-only deployments: {len(records)}")
    for d in records:
        task = tasks[d["TaskId"]]
        started = parse_time(task["StartTime"])
        print(f"  {d['Id']} {releases[d['ReleaseId']]}: {task['State']} ({(task.get('ErrorMessage') or task['Duration']).strip()}), "
              f"queued {parse_time(task['QueueTime']):%H:%M:%S}, started {f'{started:%H:%M:%S}' if started else '-'}")
        if task["State"] != "Success" and not superseded(task):
            problems.append(f"record {d['Id']} of {releases[d['ReleaseId']]} ended {task['State']}")
    unexpected = [d for d in records if not any(e["record"] == d["Id"] for es in run_for.values() for e in es)]
    for d in unexpected:
        problems.append(f"deployment {d['Id']} wasn't created by this test or the runbook")

    latest = api("GET", f"{SPACE}/deployments?projects={project['Id']}&environments={environment['Id']}&take=1")["Items"][0]
    latest_release = api("GET", f"{SPACE}/releases/{latest['ReleaseId']}")["Version"]
    latest_state = api("GET", f"{SPACE}/tasks/{latest['TaskId']}")["State"]
    running, phase = cluster_release(namespace, rollout)
    if running != expected_stable:
        problems.append(f"the cluster runs {running}; expected {expected_stable}")
    print(f"\nOctopus latest: {latest_release} ({latest_state}, {latest['Id']}); "
          f"cluster stable: {running} (phase {phase})")
    if latest_release != running or latest_state != "Success":
        problems.append(f"Octopus shows {latest_release} ({latest_state}) but the cluster runs {running}")

    aborts = sum(1 for d in ours if d["id"] in run_for)
    print(f"\n{len(ours)} deployments, {aborts} aborted by Argo, {len(runs)} runbook runs, {len(records)} records")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("All checks passed.")
    print(f"  {SERVER}/app#/{SPACE}/projects/{project['Slug']}/deployments")


if __name__ == "__main__":
    main()
