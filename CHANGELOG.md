# Changelog

Notable changes to the demo. To update your copy, see
[Keeping your copy up to date](README.md#keeping-your-copy-up-to-date). After updating, run
`./install.sh` again and create new releases: existing releases keep the deployment process
they were created with.

## Unreleased

- README: "How the demo works" with diagrams and screenshots; setup for Linux, macOS and
  Windows (WSL 2); which Octopus API key to use (a service account that manages only the demo
  space) and what it needs.
- `AGENT-INSTRUCTIONS.md`: a checklist for AI agents, from forking the repo to a tested demo.
- `install.sh` works with macOS's bash 3.2.
- `source scripts/config.sh` works from zsh (macOS's default shell). It used to find the wrong
  repo root there, and `k` then ran against your current kubectl context; `k` now refuses to
  run if the settings aren't loaded.
- `.gitignore` covers vim undo files (`*.un~`).
- README: "Why a runbook records the rollback": Octopus runs one deployment at a time per
  project and environment, the demo needs "cancel superseded deployments", and that's why
  Argo's webhook starts a runbook instead of queuing a deployment.
- The dashboard shows **Rollout complete (pods unmonitored)** once a rollout has finished:
  Argo's analysis only runs during a rollout, so recolouring a stable pod does nothing. The
  image is now `colour-demo:1.2.0`; run `./install.sh dashboard octopus` and create a new
  release.
- **One API key for everything.** The installer no longer creates extra API keys for Argo
  Rollouts' webhook and the runbooks: they use the key you provide, which can be an AI agent
  key (Octopus doesn't let agent keys create API keys). `ARGO_NOTIFICATIONS_API_KEY_FILE` is
  gone, and every `./install.sh` run updates the key in the cluster and the projects, so
  replacing it is just updating the file. Production setups should use separate, tightly
  scoped keys.
- **Dashboard at http://localhost.** The dashboard's ingress answers for any host name, so
  it's at `http://localhost` (or `http://localhost:<INGRESS_HTTP_PORT>`) instead of
  `colour-demo.localtest.me`, which didn't resolve to the cluster on every machine (for
  example, when the name resolved to IPv6 `::1` first). The installer checks the dashboard
  responds and prints its link. Run `./install.sh dashboard` to update an existing cluster.
- **Port checks.** Before creating the cluster, the installer checks `INGRESS_HTTP_PORT` and
  `INGRESS_HTTPS_PORT` are free. When it reuses a cluster, it checks the cluster's port still
  matches `INGRESS_HTTP_PORT`.
- **Create the space first.** The README, `AGENTS.md` and `AGENT-INSTRUCTIONS.md` now have an
  administrator create the demo's space first, with the key's account as a space manager. The
  installer creates the space only if no space has that name and the key has `SpaceCreate`. If
  the name doesn't match, it lists the spaces the key can see.
- **Fixed: `FileNotFoundError: 'kubectl'` on a new Linux machine.** The Python scripts now find
  the tools the installer added, even when `~/.local/bin` isn't on your `PATH` yet.
- New setting `BIN_DIR` (default `~/.local/bin`): where the installer puts missing tools. Every
  script uses it. The Linux setup now explains how to add it to your `PATH`.
- First-deployment timings in `AGENTS.md` and `AGENT-INSTRUCTIONS.md`: about 30 seconds, since
  there's no earlier release to roll out from.

## 0.1.0

First public version.

- `install.sh`: a single, re-runnable installer for tools, the kind cluster (ingress-nginx,
  Argo Rollouts), the Octopus space, the Kubernetes agent, the dashboard, the projects and the
  Argo Rollouts webhook. `uninstall.sh` removes it all.
- Configuration in `config.env` (git-ignored), with defaults for everything except
  `OCTOPUS_URL`.
- Canary and blue-green Octopus projects with Argo Rollouts analysis, the per-pod colour
  dashboard, and the Simulate builds runbook.
- Rollback sync: Argo Rollouts' notifications run the Record Argo rollback runbook, which
  records the release Argo rolled back to as a record-only deployment, unless a newer
  deployment is queued or running.
- `octopus/stress_test.py` for rapid deployments, with `--chase` and `--cycle`.
- `AGENTS.md` / `CLAUDE.md`: setup instructions for AI agents.
