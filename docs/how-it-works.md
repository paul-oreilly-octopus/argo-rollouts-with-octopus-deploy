# How it works

This explains the design of the demo, what was learned building it, and the results of the
stress tests. For setting it up, see the [README](../README.md).

- [The pieces](#the-pieces)
- [The deployment process](#the-deployment-process)
- [Keeping Octopus in sync with Argo rollbacks](#keeping-octopus-in-sync-with-argo-rollbacks)
- [Rapid deployments](#rapid-deployments)
- [Stress test results](#stress-test-results)
- [Lessons learned](#lessons-learned)
- [Caveats](#caveats)

## The pieces

```
           your Octopus instance                                local kind cluster
┌─────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
│ space "Argo Rollouts Demo"              │ polls  │ Octopus Kubernetes agent (+ monitor)     │
│  Colour Demo - Canary      ─ deploys ───┼◄───────┤                                          │
│  Colour Demo - Blue-Green  ─ deploys    │        │ Argo Rollouts controller                 │
│  runbooks: Simulate builds,             │        │   Rollouts colour-canary / -bluegreen    │
│            Record Argo rollback  ◄──────┼────────┤   notifications webhook (on abort)       │
│                                         │ HTTPS  │ ingress-nginx ─► dashboard (one square   │
└─────────────────────────────────────────┘        │                  per pod)                │
                                                   └──────────────────────────────────────────┘
```

| Path | What |
|---|---|
| `app/app.py` | One image, two modes: `MODE=app` (each Rollout pod) and `MODE=dashboard` |
| `k8s/dashboard.yaml` | The dashboard's deployment, RBAC and ingress |
| `k8s/argo-notifications.yaml` | The Argo Rollouts webhook to Octopus (applied by `octopus/setup_argo_notifications.py`) |
| `octopus/setup_*.py` | Create or update the space, projects, runbooks and webhook (all re-runnable) |
| `octopus/*.sh`, `*.ps1`, `rollout-*.yaml` | The contents of the Octopus steps and runbooks |
| `octopus/deploy.py`, `simulate_builds.py`, `stress_test.py` | Drive the demo from the command line |
| `scripts/` | Tool install, kind cluster, Octopus agent and dashboard |

Each app pod starts with a colour (random, or the `StartColour` setting) and reports itself
**unhealthy while it's red**. The Argo Rollouts analysis checks the *new* pods every 5
seconds, so a single red new pod makes Argo abort the update and roll back automatically.

| Strategy | What happens | Where a red pod triggers rollback |
|---|---|---|
| Canary | 4 pods: 25% → 50% → 75% → 100%, `PauseDuration` (45s) between | Any canary pod, from the 25% step on |
| Blue-green | 3 new pods behind `preview`, analysed (`AnalysisCount` × 5s), promoted, analysed again | Preview pods before the switch; the new active pods after it (traffic switches back) |

## The deployment process

Both projects deploy to namespace `colour-<strategy>-<environment>` on target tag
`argo-rollouts`:

1. **Prepare namespace**: creates the namespace and the two Services *once*. Argo owns the
   Services' selectors after that; re-applying them would make Argo treat the next update as
   an initial deploy and skip analysis.
2. **Check deployed version**: compares the release with what the cluster runs (the stable
   ReplicaSet) and decides whether steps 3 and 4 run (output variable `NeedsDeploy`).
3. **Apply Rollout**: the AnalysisTemplate and Rollout, as inline YAML.
4. **Wait for Argo Rollout**: succeeds when the Rollout is Healthy and fails when Argo aborts,
   so the Octopus result reflects what happened. Redeploying the release Argo just aborted
   retries it.

Prompted variables: **Start colour** (`random-without-red` by default; `random-with-red`
makes roughly 1 in 8 pods start red; `uniform-without-red` and `uniform-with-red` do the same
but give every non-red pod of a release one colour, the release number's SHA-256 modulo the 7
non-red colours; `red` guarantees a rollback; or a specific colour),
**Pause between canary steps** (canary) and **Analysis checks** (blue-green). Releases snapshot
the project's values when they're created.

The **Simulate builds** runbook creates a release every `BuildIntervalSeconds` for
`BuildDurationMinutes`, versioned `MAJOR.MINOR.BUGFIX-BUILD`, to simulate a CI pipeline. It
only creates releases; deploying them is separate. Releases snapshot the project's Start colour
when they're created, so if the run's **Start colour** prompt differs from the project's
setting, the runbook sets the project's value for the run, then restores it (unless it was
changed meanwhile). Releases anyone else creates during the run get that colour too. This
means the runbook's key also needs permission to edit the project's variables.

## Keeping Octopus in sync with Argo rollbacks

Argo Rollouts rolls back on its own, so without help Octopus's dashboard shows the failed
release while the cluster runs the previous one. Here, Argo Rollouts calls Octopus when it
aborts, and Octopus records the release Argo rolled back to as a deployment that **deploys
nothing**, unless a newer deployment is already on its way:

```
Octopus deploys 1.0.5 ──► Argo aborts it; traffic goes back to 1.0.4's pods
                           │
                           ▼ webhook (k8s/argo-notifications.yaml)
POST /api/<space>/runbook-runs/create/v1   runbook "Record Argo rollback"
  Release=1.0.4, AbortedRelease=1.0.5, AbortedDeployment=Deployments-N, Reason=<Argo's message>
                           │
                           ▼ runbook (octopus/record-argo-rollback.ps1, a few seconds on a worker)
Is Deployments-N still the newest deployment of this project to this environment?
  no  ─► "Skipped": a newer deployment is queued or running, and it will show what's running
  yes ─► creates a deployment of 1.0.4 with ArgoRollback.Triggered=True
                           │
                           ▼ Octopus "deployment" of 1.0.4 (~4s of work)
Prepare namespace, Apply, Wait: skipped
Check deployed version: reads the cluster, logs "Recorded without deploying: colour-canary
runs release 1.0.4 (4/4 pods ready, ReplicaSet ...)", changes nothing
```

Result: the 1.0.5 deployment shows as failed, then 1.0.4 as the current, successful release.
The Rollout stays as Argo left it (Degraded, aborted) until the next deployment. Record-only
deployments never change the cluster, which may be moving faster than Octopus.

**Mapping a rollback to an Octopus release.** Every pod template carries the annotation
`octopus.com/release`, so each ReplicaSet says which release it is. The check step reads the
stable ReplicaSet's release, and the Apply step records it on the Rollout as
`octopus.com/rollback-release`: the release Argo falls back to if this deployment aborts.
Alongside it are `octopus.com/space-id`, `project`, `environment`, `release` and
`deployment` (the Octopus deployment that applied the spec), so the webhook body is built
entirely from the Rollout's annotations. Argo only ever falls back to the stable ReplicaSet,
the last release that completed its rollout, so a run of failed releases all fall back to the
same last good one.

**The check step** (`octopus/check-deployed-version.sh`) decides:

| Trigger | Cluster state | Result |
|---|---|---|
| Record (from the runbook) | Runs this release | Report it and succeed; nothing else runs |
| Record (from the runbook) | Runs another release | Report it and fail; nothing else runs |
| Normal | No Rollout yet, or it runs a different release | Deploy as normal |
| Normal | Already runs this release, and the Rollout is settled on it | Skip Apply and Wait ("nothing to deploy") |
| Normal | Pods run this release but the spec describes another (redeploying the stable release after an abort) | Adopt: copy the stable ReplicaSet's template back into the spec (like `kubectl argo rollouts undo`); no new pods |

**Rollback-aware variables.** These are optional prompts on both projects. The runbook sets them
on the record, and any step can use them, e.g. as a run condition `#{ArgoRollback.Triggered}`:
`ArgoRollback.Triggered` (True/False), `ArgoRollback.AbortedRelease`, `ArgoRollback.Reason`.
The webhook also passes the runbook `ArgoRollback.Release` and `ArgoRollback.AbortedDeployment`.
Prepare namespace runs only when `ArgoRollback.Triggered` isn't True; Apply and Wait run only
when the check step's `NeedsDeploy` is True, which it never is for a record.

**The webhook** fires on a custom trigger, `on-aborted-sync-octopus`, which Rollouts opt into
with the annotation `notifications.argoproj.io/subscribe.on-aborted-sync-octopus.octopus: ""`.

**API keys.** The demo uses the one key you provide for everything. Besides the installer, it's
used by:
- the Argo Rollouts controller, to start the runbook (Secret `argo-rollouts-notification-secret`);
- the runbooks, to create releases and records (sensitive project variable `ReleaseCreatorApiKey`);
- the Kubernetes agent and monitor (Secret `octopus-agent-api-key`).

It's a demo shortcut, and it means an AI agent key works: Octopus doesn't let agent keys
create API keys, so an installer that created dedicated keys couldn't run with one. **In
production, give each of these its own tightly scoped key,** on a service account that can only
do that job. The webhook's key, for example, only needs to run one runbook in one project.

## Rapid deployments

Some teams deploy more often than an Octopus deployment takes to run. Two Octopus behaviours
matter here:

- Octopus runs **one deployment per project and environment at a time** and queues the rest.
- With **cancel superseded deployments** on (project deployment settings `CancelQueuedTasks`
  and `CancelRunningTasks`, which the installer turns on), queuing a deployment cancels any
  older one still queued ("Superseded by ServerTasks-N"). So however fast deployments arrive,
  at most one runs and one waits, and the newest release always runs next.

That's why the webhook goes through a runbook rather than creating the record deployment
directly. In an earlier version it did create it directly. A record created while another
deployment was running then waited behind it, minutes in testing. It ran after the cluster had
moved on, failed as stale, and Octopus's dashboard showed that old, failed release as current.
Runbook runs aren't queued behind deployments, so the runbook decides with current
information:

- If a newer deployment is queued or running, it skips; that deployment runs next and shows
  what's in the cluster when it finishes.
- Otherwise, it creates the record. The record waits for the aborted deployment to finish (a
  few seconds). If a newer deployment is queued in that window, it supersedes the record,
  which is cancelled without running. A record never runs stale.

## Stress test results

`octopus/stress_test.py` deploys every few seconds and then checks:
- that every abort ran the runbook once;
- that no record failed;
- that each deployment saw the expected stable release;
- that Octopus's latest deployment succeeded and matches the cluster.

`--chase` deploys again the moment the runbook creates a record, to race it. `--cycle N`
alternates N good and N red releases.

Results on Octopus Cloud with kind on Docker Desktop (WSL 2), a deployment every 5 seconds,
with the canary pause at 5s and 4 blue-green analysis checks. Canary deployments then take
about 35s; blue-green about 55s, or about 20s when aborted:

| Run | Deployments | Ran | Superseded | Argo aborts | Runbook decisions | Octopus matched the cluster |
|---|---|---|---|---|---|---|
| Canary, 2 min | 24 | 5 | 19 | 2 | 1 skipped, 1 recorded (ran in 4s) | Yes |
| Canary, 3 min, chase | 37 | 8 | 29 | 2 | 1 skipped, 1 recorded (superseded by the chase) | Yes |
| Blue-green, 3 min, chase | 37 | 8 | 29 | 4 | 3 skipped, 1 recorded (superseded by the chase) | Yes |
| Canary, 5 min, `--cycle 15`, chase | 61 | 12 | 49 | 6 | 5 skipped, 1 recorded (superseded by the chase) | Yes |
| Blue-green, 5 min, `--cycle 15`, chase | 61 | 9 | 52 | 4 | 3 skipped, 1 recorded (superseded by the chase) | Yes |

In the cycle runs, up to four red releases in a row all fell back to the same last good
release, and every deployment saw the stable release the test expected. The runbook usually
started a few seconds *before* the aborted deployment's Wait step noticed the abort, because
Argo notifies as soon as it aborts, and took 3-6s. The first run on an idle hosted worker took
about 20s. With `--cycle 5`, the phases are shorter than a deployment, so superseding means red
releases rarely run back to back.

## Lessons learned

- **Argo Rollouts evaluates notification triggers two ways.** Per event: a trigger named
  after an event reason, e.g. `on-rollout-aborted`, fires each time that event is recorded.
  Continuously: every trigger's `when` condition is checked on each Rollout update, sending
  once when it becomes true. A custom trigger name avoids the per-event path, so one abort
  means one call. The controller records sends in the `notified.notifications.argoproj.io`
  annotation.
- **Failed sends aren't recorded,** so they're retried on every Rollout update until one works.
- **`status.abort` stays true for a moment after a new release is applied to an aborted
  Rollout.** So the trigger also requires `status.abortedAt` to be newer than the
  `octopus.com/deployed-at` annotation the check step stamps on each deployment; otherwise the
  old abort is sent again.
- **Octopus's create-deployment API rejects deployments missing required prompted
  variables.** That's why every prompt here is optional; a record uses the release's
  snapshot values.
- **`OctopusBypassDeploymentMutex` doesn't let deployments of the same project and environment
  run concurrently.** Cancelling superseded deployments is what keeps the queue short.
- **Releases snapshot the deployment process and variables,** so process changes only apply to
  releases created afterwards.
- **Re-applying the Services Argo manages** wipes the selector Argo added, and Argo then treats
  the next update as an initial deploy, without analysis.
- **Argo Rollouts' CRDs** are too big for client-side `kubectl apply`, so they're applied
  server-side.

## Caveats

- **Records rely on the newer process:** only releases created after the projects were set up
  have the check step and annotations, so the webhook can only record such releases.
- **The check step compares release numbers.** Redeploying the running release with changed
  variables is treated as "nothing to deploy".
- **If someone cancels the newer deployment the runbook skipped for,** nothing records the
  rollback until the next deployment.
- **Adopting** (redeploying the stable release after an abort) creates a new Rollout revision
  number pointing at the existing ReplicaSet.
- **ingress-nginx is archived upstream.** It's fine for a local demo, but consider Gateway API
  for anything longer-lived.
