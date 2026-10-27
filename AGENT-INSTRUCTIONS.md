# Agent checklist: from fork to a working demo

A checklist for an AI agent (Claude Code, or any other) setting up this demo for someone. Work
through it in order, ticking items off as you go, and tell the user where you are. The detail
behind each step, and the rules, are in [AGENTS.md](AGENTS.md). Follow its ground rules
throughout, especially:

- **Never print, echo, copy or commit an API key.** Keys live only in files.
- **Ask before anything destructive or outward-facing:** forking, pushing, `./uninstall.sh`,
  `--delete-space`, deleting targets or projects.
- **Instance details go only in `config.env` and `secrets/`,** both git-ignored.

Steps marked **(user)** need the person or an Octopus administrator. You can't do them, but
you can explain exactly what to do.

## 1. Get the code

- [ ] Ask the user where their copy should live:
  - **A public fork** (fine if they'll never commit settings): `gh repo fork
    paul-oreilly-octopus/argo-rollouts-with-octopus-deploy --clone`, or fork in the GitHub UI and
    `git clone` it. Ask before creating the fork.
  - **A private copy** (if they want to commit their own changes): they create an empty
    private repo, then `git clone --bare` this repo and `git push --mirror` to theirs. Ask
    before pushing.
  - **Just a clone** to try it out: `git clone
    https://github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy.git`.
- [ ] On Windows, clone **inside WSL 2** into the Linux filesystem (e.g. `~/src`), not under
  `/mnt/c`, and run every command there.
- [ ] Add the upstream remote, so they can take updates later:
  `git remote add upstream https://github.com/paul-oreilly-octopus/argo-rollouts-with-octopus-deploy.git`.

## 2. Get the credentials and details

- [ ] **Octopus URL**, e.g. `https://their-instance.octopus.app`. For a self-hosted server,
  also the polling address (default `https://<host>:10943/`) and gRPC address (default
  `grpc://<host>:8443`).
- [ ] **Space name:** default `Argo Rollouts Demo`.
- [ ] **(user) An API key limited to that space.** Octopus keys can't be scoped to a space
  themselves: they have the permissions of their account. So recommend that an Octopus
  administrator:
  1. creates a **service account** (**Configuration** › **Users** › **Create service account**);
  2. creates the **space** (**Configuration** › **Spaces** › **Add space**) with that service
     account as a **space manager**;
  3. creates an **API key** for the service account, with full access. An AI agent key
     (**New API key for AI Agent**) is best, since you're an agent;
  4. saves the key in a file: `secrets/octopus-api-key.txt` in the clone (mode 600), or a path
     outside the repo.

  The alternative is the user's own key, if they can create spaces (`SpaceCreate`): the
  installer then creates the space. See
  [The Octopus API key](README.md#the-octopus-api-key) for what the key is used for.
- [ ] **Explain that the demo uses this one key for everything:** the installer, the
  Kubernetes agent, Argo Rollouts' webhook and the runbooks. That's a shortcut for a demo; in
  production, each of those should have its own tightly scoped key.
- [ ] **Ask for the key's file path, not the key.** If the user pastes a key anyway, write it to
  `secrets/octopus-api-key.txt` with mode 600 without repeating it, and suggest they rotate it.
- [ ] **Worker pool:** on Octopus Cloud the default ("Hosted Ubuntu") is fine. Self-hosted:
  ask for a pool whose workers have PowerShell and can reach the Octopus URL.

## 3. Prepare the machine

Follow [Preparing your machine](README.md#preparing-your-machine) for their OS.

- [ ] Docker is reachable: `docker info --format '{{.ServerVersion}}'`.
  - Linux: Docker Engine, user in the `docker` group, inotify limits raised.
  - macOS: Docker Desktop running, with at least 4 GB of memory.
  - Windows: Docker Desktop with WSL integration on for the distribution.
- [ ] `python3 --version` is 3.9 or later; `curl`, `tar` and `git` exist.
- [ ] Ports 80 and 443 are free (`ss -ltn` on Linux, `lsof -nP -iTCP -sTCP:LISTEN` on macOS).
  If not, or with rootless Docker, choose others (e.g. 8080 and 8443).

## 4. Configure

- [ ] `cp config.example.env config.env`, then set `OCTOPUS_URL`, `OCTOPUS_SPACE_NAME`, and
  anything else that differs from the defaults (key file path, ports, self-hosted URLs, worker
  pool).
- [ ] `python3 octopus/config.py check` passes. It never prints the key.
- [ ] `git status` shows no new tracked changes: `config.env` and `secrets/` are ignored.

## 5. Install

- [ ] `./install.sh` (about 5-10 minutes the first time).
- [ ] If a step fails, fix the cause using the troubleshooting tables in [AGENTS.md](AGENTS.md)
  and the README, then re-run from that step, e.g. `./install.sh agent dashboard octopus argo`.

## 6. Verify

- [ ] Pods are running (`source scripts/config.sh` first, for the `k` helper):
  - [ ] `k get pods -n argo-rollouts`
  - [ ] `k get pods -n "$AGENT_NAMESPACE"` (agent, and the Kubernetes monitor)
  - [ ] `k get pods -n colour-demo-dashboard`
- [ ] The dashboard returns 200: `curl -s -o /dev/null -w '%{http_code}\n' "$(scripts/dashboard-url.sh)"`.
- [ ] In Octopus, the space has:
  - [ ] a healthy deployment target named `AGENT_NAME`;
  - [ ] the projects "Colour Demo - Canary" and "Colour Demo - Blue-Green";
  - [ ] the runbooks "Simulate builds" and "Record Argo rollback" in each project.

## 7. Test deployments and a rollback

- [ ] `python3 octopus/deploy.py canary` succeeds (about 3 minutes).
- [ ] `python3 octopus/deploy.py bluegreen` succeeds (about 2 minutes).
- [ ] `python3 octopus/deploy.py canary --colour red` fails with "Argo Rollouts aborted release ...".
- [ ] Within about 30 seconds, the canary project's **Record Argo rollback** runbook ran and
  logged "Recording ...".
- [ ] Then a deployment of the previous release succeeded in about 4 seconds, with the highlight
  "Recorded without deploying: ...".
- [ ] Octopus's current release matches the cluster:
  `k -n colour-canary-development get rollout colour-canary -o jsonpath='{.status.stableRS}'`.

## 8. Optional: stress test

- [ ] `python3 octopus/stress_test.py canary --chase` ends with `All checks passed.` Most
  deployments show as superseded: that's expected.

## 9. Hand over

- [ ] Tell the user the result of each check, with any failures and what you did about them.
- [ ] Give them the dashboard URL (`scripts/dashboard-url.sh`) and the
  [demo walkthrough](README.md#running-the-demo).
- [ ] Remind them:
  - `config.env` and `secrets/` must never be committed (a fork is public);
  - the demo's one API key is also stored in two Kubernetes Secrets and a sensitive project
    variable. After replacing it, run `./install.sh agent octopus argo`. A production setup
    would use separate, tightly scoped keys;
  - to take updates: `git fetch upstream && git merge upstream/main && ./install.sh`, after
    reading [CHANGELOG.md](CHANGELOG.md).
