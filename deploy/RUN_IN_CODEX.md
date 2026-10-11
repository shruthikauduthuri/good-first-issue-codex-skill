# Run the installed skill in Codex GUI

The finder is installed on Linode `172.238.189.250` as `good-first-issues.service`. It runs as the unprivileged `gfi` account, listens on server loopback port 8000, and starts on boot. The installed desktop skill uses a private `config.json` and connects over an SSH tunnel on local port 8765.

The installed client's private `ssh_tunnel` settings let it reconnect automatically after a computer restart or when the local tunnel is stopped. The existing deployment key and trusted-host record must remain at their configured paths. If Codex blocks network access, approve the normal client-command network request and rerun the skill. Restarting the computer alone does not launch a tunnel; invoking the updated skill does.

## Try it in the app

1. Open a fresh Codex chat.
2. Select **Good First Issue Finder** from the skill picker. If it is missing, restart Codex.
3. Send:

```text
$good-first-issues Find one small Python documentation issue in an active repository.
```

Selecting the skill from the picker also works if your desktop version uses a different mention shortcut. Allow the script's network request if the app asks. Successful output contains clickable GitHub issues, difficulty, fit reasons, contributor guidance, checks and timestamps. Empty successful results say `No verified results`; authentication and timeout failures are errors.

## Manual tunnel fallback

From a terminal:

```sh
cd /Users/uduthurishruthika/Desktop/hack-midwest/good-first-issue-codex-skill
ssh -i .local/linode-deploy \
  -o UserKnownHostsFile=.local/known_hosts \
  -o ExitOnForwardFailure=yes \
  -N -L 127.0.0.1:8765:127.0.0.1:8000 root@172.238.189.250
```

Keep that terminal open while using the skill. If port 8765 is already in use by the existing tunnel, use the running tunnel; do not start a second one.

## Update inference credentials

The local `.env` and server `/opt/good-first-issues/.env` contain the server credentials. Changing only the local file does not update the running service. After updating the local file, ask Codex to sync it to this Linode and restart `good-first-issues.service`, or upload it through your normal secure deployment process. Never paste keys into chat.

The deployed health endpoint is `http://127.0.0.1:8765/health` while the tunnel is running. A `ready` health response means credentials are present; it does not establish that Akamai accepts them. Use `scripts/smoke_inference.py` to verify real inference and tool calling.
