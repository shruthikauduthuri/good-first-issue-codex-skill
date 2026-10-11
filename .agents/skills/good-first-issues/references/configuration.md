# Desktop configuration

The client reads `scripts/config.json` first, then environment variables for missing values. `--config /absolute/path/config.json` or `GFI_CONFIG` selects a different file.

```json
{"endpoint": "https://your-service.example/find", "api_key": "your-shared-service-key", "timeout": 210}
```

Create a private file with a hidden key prompt:

```sh
python3 <skill-directory>/scripts/configure.py
```

Fallback variables: `GFI_ENDPOINT`, `GFI_API_KEY`, `GFI_TIMEOUT`. The endpoint is the finder service's `/find` URL, **not** the Akamai inference URL. The inference and GitHub tokens stay on the server. `config.example.json` is a template only.

Remote services require HTTPS. HTTP is allowed only for loopback (`localhost`, `127.0.0.1`, `::1`), supporting an SSH tunnel to Linode. Redirects are rejected to prevent forwarding the shared key elsewhere. Private config files require permissions 0600 on Unix.

If the service is not deployed, use the repository README. Do not present live results until the configured service answers successfully.

An existing trusted SSH connection can be restored automatically when the local port is closed. Add `ssh_tunnel` to the private config with `host` (IPv4), `user`, absolute `identity_file` and `known_hosts_file` paths, and `remote_port` (default 8000). This works with `http://127.0.0.1:<local-port>/find`. It uses the existing key, requires a previously trusted host, and makes one reconnect attempt; it never provisions resources, creates keys, changes server permissions, or bypasses host verification. If Codex blocks network access, request the normal approval for the client command and rerun it. Restarting the computer alone does not start an SSH tunnel.
