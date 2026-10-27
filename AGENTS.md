# Instructions for AI agents

You're helping someone set up, run or update this demo: Octopus Deploy driving Argo Rollouts
on a local kind cluster, with Argo's automatic rollbacks synced back to Octopus. Read
[README.md](README.md) for what it is, and [docs/how-it-works.md](docs/how-it-works.md) for
the design. Follow these instructions when doing the setup.
[AGENT-INSTRUCTIONS.md](AGENT-INSTRUCTIONS.md) is the same process as a checklist, starting
from forking the repo: work through it, and use this file for the detail.

## Ground rules

- **Never print, echo, log, copy or commit an API key.** Read keys only from files: the
  scripts already do this. Don't `cat` key files, pass keys as command-line arguments, or put
  them in `config.env`, commit messages or chat output. If the user pastes a key into the
  conversation, write it to `secrets/octopus-api-key.txt` (mode 600) without repeating it, and
  suggest they rotate it later.
- **Keep instance details out of tracked files.** The user's URL, space and choices go only
  in `config.env`, and keys only in `secrets/` or a path outside the repo. Both are
  git-ignored. Don't edit tracked files to fit one environment; if something needs to be
  configurable, add a setting with a default in `octopus/config.py` (and
  `config.example.env`). A fork of this public repo is public, so a committed detail is
  published.
- **Ask before anything destructive or outward-facing:** `./uninstall.sh` (deletes the
  cluster), `--delete-space` (deletes an Octopus space and everything in it), deleting
  deployment targets or projects, or pushing to a remote.
- **Use the demo's cluster explicitly:** `kubectl --context kind-<CLUSTER_NAME>` (the
  scripts' `k` helper does this). Never change or rely on the user's current kubectl context.
- **Run in a Linux shell:** on Windows, run everything inside WSL 2, not PowerShell. Native
  Windows tools write CRLF line endings and mangle quoting.

## Setting up the demo

### 1. Gather what you need

Ask the user for anything you can't find:
- **Octopus URL**, e.g. `https://their-instance.octopus.app`. For a self-hosted server, also
  the polling address (default `https://<host>:10943/`) and gRPC address (default
  `grpc://<host>:8443`).
- **Where their API key is:** a file path. The default is `secrets/octopus-api-key.txt` in the
  repo. Don't ask them to paste it.
- **Space name:** the default "Argo Rollouts Demo" is created if it doesn't exist.
- **Which account the key belongs to.** API keys can't be scoped to a space: they have their
  account's permissions. Recommend a **service account** that an administrator makes a
  **space manager** of a space they create for the demo, so the key can only touch that space.
  An **AI agent key** (full access) is fine, and preferred when you're doing the setup. The
  user's own key also works if they can create spaces (`SpaceCreate`). Details:
  [The Octopus API key](README.md#the-octopus-api-key).
- **Tell the user the demo uses this one key for everything** (the installer, the agent, Argo
  Rollouts' webhook and the runbooks), and that this is a demo shortcut: in production, each of
  those should have its own tightly scoped key.
- Any port conflicts: the defaults are 80 and 443 (`INGRESS_HTTP_PORT`, `INGRESS_HTTPS_PORT`).

### 2. Check the machine

Use the user's OS section of [Preparing your machine](README.md#preparing-your-machine)
(Linux, macOS, or Windows with WSL 2).

```bash
uname -s                                     # Linux or Darwin (macOS)
docker info --format '{{.ServerVersion}}'   # Docker reachable (on WSL: Docker Desktop WSL integration)
python3 --version                            # 3.9+
command -v curl tar git
ss -ltn 2>/dev/null | grep -E ':(80|443)\s' # Linux: ports in use? choose others if so
lsof -nP -iTCP:80 -iTCP:443 -sTCP:LISTEN     # macOS: the same check
```

On Linux, check `sysctl fs.inotify.max_user_watches fs.inotify.max_user_instances` is at least
524288 and 512, and suggest the README's commands if not (they need `sudo`, so the user runs
them). With rootless Docker, use ports above 1024.

### 3. Write config.env

```bash
cp config.example.env config.env
```

Set `OCTOPUS_URL`, plus anything else that differs from the defaults (see the comments in the
file). Then validate it; this never prints the key:

```bash
python3 octopus/config.py check
```

### 4. Install

```bash
./install.sh
```

It's re-runnable, and each step is idempotent. If a step fails, fix the cause and re-run
that step, e.g. `./install.sh agent`, or continue with the remaining steps:
`./install.sh agent dashboard octopus argo`. The steps are
`check tools cluster space agent dashboard octopus argo`. The first run takes about 5-10
minutes, mostly creating the cluster and pulling images.

### 5. Verify

Check each of these, and report the results to the user:

```bash
source scripts/config.sh                      # loads the settings; gives you the k helper
k get pods -n argo-rollouts                   # argo-rollouts Running
k get pods -n "$AGENT_NAMESPACE"              # agent (and kubernetes-monitor) Running
k get pods -n colour-demo-dashboard           # dashboard Running
curl -s -o /dev/null -w '%{http_code}\n' "$(scripts/dashboard-url.sh)"   # 200
```

In Octopus (UI or API), the space should have:
- a deployment target named `AGENT_NAME` that's healthy;
- the projects "Colour Demo - Canary" and "Colour Demo - Blue-Green";
- the runbooks "Simulate builds" and "Record Argo rollback" in each project.

### 6. First deployments and a rollback test

```bash
python3 octopus/deploy.py canary                # Success (about 3 minutes with the default 45s pauses)
python3 octopus/deploy.py bluegreen             # Success (about 2 minutes)
python3 octopus/deploy.py canary --colour red   # Fails: "Argo Rollouts aborted release ..."
```

After the red deployment fails, within about 30 seconds:
- the project's **Record Argo rollback** runbook should have run and logged "Recording ...";
- a new deployment of the previous release should have succeeded in about 4 seconds, with the
  highlight "Recorded without deploying: ...".

Octopus's dashboard then shows the previous release as current, which matches the cluster:

```bash
k -n colour-canary-development get rollout colour-canary -o jsonpath='{.status.stableRS}'
```

### 7. Optional: stress tests

```bash
python3 octopus/stress_test.py canary --chase
python3 octopus/stress_test.py bluegreen --chase --minutes 3
python3 octopus/stress_test.py canary --cycle 15 --minutes 5 --chase
```

Each run ends with `All checks passed.` or a list of `PROBLEMS`. The script deploys before
waiting, so most deployments show as **superseded**. That's expected: it's Octopus's "cancel
superseded deployments" setting at work.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `SpaceCreate` / 403 creating the space | The key's account can't create spaces: have an admin create it with that account as a space manager, or set `OCTOPUS_SPACE_NAME` to a space it manages |
| 401 from Octopus after the key was replaced, e.g. the webhook or a runbook | The old key is still in the cluster or the project variables: run `./install.sh agent octopus argo` |
| Pods fail with "too many open files" (Linux) | Raise the inotify limits (README, Linux section) |
| `port is already allocated` creating the cluster | Change `INGRESS_HTTP_PORT` / `INGRESS_HTTPS_PORT`; `./uninstall.sh` (ask first), then `./install.sh` |
| The agent's Helm install times out | `k -n "$AGENT_NAMESPACE" logs <agent pod>`. Usually `OCTOPUS_POLLING_URL` is wrong (self-hosted), or the key lacks permission to register targets |
| A deployment target already exists with that name | The installer deletes a target named `AGENT_NAME` when the agent isn't installed (it's left over from an earlier cluster). If it belongs to something else, set a different `AGENT_NAME` |
| Runbook runs stay queued or fail to start | No usable worker: set `OCTOPUS_WORKER_POOL` to a pool with PowerShell that can reach `OCTOPUS_URL` |
| The red deployment fails, but no runbook run appears | `k -n argo-rollouts logs deploy/argo-rollouts \| grep -i notif`. Check that `./install.sh argo` ran since the key last changed (a 401 in the log means it didn't) |
| A record deployment fails with "not running" | The cluster moved on before the record ran (rare: a deployment was cancelled by hand). The next deployment corrects Octopus |
| `$'\r': command not found` | CRLF line endings: clone inside WSL, or `git config core.autocrlf false`, then `git checkout -- .` |
| The deploy API returns "Please provide a variable for the prompted value" | A release from before a prompt became optional. Create a new release |

## Updating from upstream

The user's copy is a fork or a private mirror of
`github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy`. To bring in updates:

```bash
git remote -v | grep -q upstream || git remote add upstream https://github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy.git
git fetch upstream && git merge upstream/main
./install.sh
```

Read the new entries in [CHANGELOG.md](CHANGELOG.md) first and tell the user what's changing.
Existing releases keep their old deployment process, so create new releases to pick up
process changes.

## Changing the demo

Keep it general: no instance names, URLs, IDs or personal details in tracked files. New
settings go in `octopus/config.py` with a default, plus `config.example.env` and the README's
table. Scripts must stay re-runnable. Add a CHANGELOG entry.
