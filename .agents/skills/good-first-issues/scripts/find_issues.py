#!/usr/bin/env python3
"""Dependency-free desktop client. No successful output until fully validated."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import socket
import subprocess
import ipaddress
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ClientError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(endpoint):
    u = urlsplit(endpoint)
    if u.username or u.password or u.query or u.fragment or not u.hostname:
        raise ClientError("Endpoint must be a /find URL without credentials, query, or fragment.")
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ClientError("Use HTTPS for remote endpoints, or loopback HTTP through an SSH tunnel.")
    if u.path.rstrip("/") != "/find":
        raise ClientError("Endpoint must end in /find; do not use the inference URL.")
    return endpoint.rstrip("/")


def load_config(path=None):
    selected = path or os.getenv("GFI_CONFIG")
    p = Path(selected) if selected else Path(__file__).with_name("config.json")
    conf = {}
    if p.exists():
        if os.name == "posix" and stat.S_IMODE(p.stat().st_mode) & 0o077:
            raise ClientError("Private configuration must have permissions 0600. Run chmod 600 on it.")
        try:
            conf = json.loads(p.read_text())
        except (OSError, ValueError) as exc:
            raise ClientError("Cannot read configuration JSON.") from exc
        if not isinstance(conf, dict):
            raise ClientError("Configuration must be a JSON object.")
    elif selected:
        raise ClientError("Selected configuration file does not exist.")
    endpoint = conf.get("endpoint") or os.getenv("GFI_ENDPOINT", "")
    key = conf.get("api_key") or os.getenv("GFI_API_KEY", "")
    if not isinstance(endpoint, str) or not isinstance(key, str) or not endpoint or not key:
        raise ClientError("Missing endpoint or shared API key. Run scripts/configure.py for this skill.")
    if any(ord(c) <= 32 or ord(c) == 127 for c in key):
        raise ClientError("The shared API key contains whitespace or control characters.")
    try:
        timeout = float(conf.get("timeout") or os.getenv("GFI_TIMEOUT", "330"))
        if not 1 <= timeout <= 360:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ClientError("Timeout must be between 1 and 360 seconds.") from exc
    return validate_endpoint(endpoint), key, timeout


CHECKS = {"issue_open", "no_assignees", "no_claim_comment", "no_open_pr", "repo_active", "has_contributor_guide"}


def ensure_tunnel(endpoint, config_path=None):
    """Restore an explicitly configured loopback tunnel once per invocation."""
    selected = config_path or os.getenv("GFI_CONFIG")
    p = Path(selected) if selected else Path(__file__).with_name("config.json")
    if not p.exists():
        return
    conf = json.loads(p.read_text())
    tunnel = conf.get("ssh_tunnel")
    if not tunnel:
        return
    u = urlsplit(endpoint)
    if u.scheme != "http" or u.hostname != "127.0.0.1":
        raise ClientError("Automatic SSH tunnels require a 127.0.0.1 HTTP endpoint.")
    if not isinstance(tunnel, dict):
        raise ClientError("SSH tunnel configuration must be an object.")
    try:
        host = str(ipaddress.IPv4Address(tunnel["host"]))
        user = tunnel.get("user", "root")
        identity = Path(tunnel["identity_file"]).expanduser()
        known_hosts = Path(tunnel["known_hosts_file"]).expanduser()
        remote_port = int(tunnel.get("remote_port", 8000))
        local_port = u.port or 80
        if not isinstance(user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]*", user) or not 1 <= remote_port <= 65535:
            raise ValueError()
        if not identity.is_absolute() or not known_hosts.is_absolute() or not identity.is_file() or not known_hosts.is_file():
            raise ClientError("The SSH identity or trusted host file is missing. Restore the deployment files.")
    except (KeyError, ValueError, TypeError) as exc:
        raise ClientError("Invalid SSH tunnel configuration.") from exc
    try:
        with socket.create_connection(("127.0.0.1", local_port), timeout=1):
            return
    except OSError:
        pass
    print("Restoring the Linode SSH connection…", file=sys.stderr)
    args = ["ssh", "-i", str(identity), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}", "-o", "ConnectTimeout=10", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-fNT", "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", f"{user}@{host}"]
    try:
        result = subprocess.run(args, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientError("Could not restore the SSH tunnel. Check SSH access and allow this skill's network request in Codex.") from exc
    if result.returncode:
        raise ClientError("Could not restore the SSH tunnel. Check SSH access and allow this skill's network request in Codex.")


def validate_response(data, count):
    if not isinstance(data, dict) or not isinstance(data.get("query"), str) or not isinstance(data.get("results"), list):
        raise ClientError("Service returned an invalid result schema.")
    if len(data["results"]) > count:
        raise ClientError("Service returned too many results.")
    seen = set()
    for row in data["results"]:
        fields = ("repo", "title", "issue_url", "difficulty", "availability", "fit_reason", "contributing_notes", "verified_at")
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k] for k in fields):
            raise ClientError("Service returned an incomplete issue.")
        repo = row["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ClientError("Service returned an invalid repository.")
        if not re.fullmatch(r"https://github\.com/" + re.escape(repo) + r"/issues/[1-9][0-9]*", row["issue_url"]):
            raise ClientError("Service returned an invalid GitHub issue link.")
        if row["issue_url"] in seen or row["difficulty"] not in {"easy", "medium", "hard"}:
            raise ClientError("Service returned a duplicate issue or invalid difficulty.")
        seen.add(row["issue_url"])
        if not isinstance(row.get("checks_passed"), list) or not all(isinstance(c, str) for c in row["checks_passed"]) or not CHECKS.issubset(row["checks_passed"]):
            raise ClientError("Service returned an issue without all required verification checks.")
        try:
            stamp = datetime.fromisoformat(row["verified_at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if not -60 <= age <= 600:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ClientError("Service returned a stale or invalid verification timestamp.") from exc
    return data


def fetch(endpoint, key, timeout, description, language, count):
    payload = {"description": description, "count": count}
    if language:
        payload["language"] = language
    req = Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "X-API-Key": key})
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ClientError("Service response is too large.")
            data = json.loads(raw)
    except HTTPError as exc:
        messages = {401: "Service rejected the shared API key.", 422: "Service rejected the query or filters.", 429: "Service is busy; try again shortly.", 504: "Verification timed out; no results were returned."}
        if exc.code in {502, 503, 504}:
            try:
                detail = json.loads(exc.read(2000)).get("detail")
                allowed = {"inference_auth", "inference_rate_limit", "inference_timeout", "inference_connection", "deadline_exceeded", "reasoning_budget", "tool_budget", "github_rate_limit", "github_auth", "github_connection", "configuration", "structured_output", "verification_failed", "upstream_failure"}
                if isinstance(detail, dict) and detail.get("code") in allowed:
                    messages[exc.code] = str(detail.get("message", "Request failed"))[:400] + " [" + detail["code"] + "]"
            except (ValueError, AttributeError):
                pass
        raise ClientError(messages.get(exc.code, f"Service request failed (HTTP {exc.code}). Check service health and configuration.")) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise ClientError("Cannot reach the finder service or request timed out. Check network access, endpoint, and SSH tunnel.") from exc
    except (ValueError, UnicodeError) as exc:
        raise ClientError("Service did not return valid JSON.") from exc
    return validate_response(data, count)


def escape(text):
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", " ".join(text.split()))


def render(data):
    lines = ["No verified results."] if not data["results"] else ["Verified good first issues", ""]
    for i, r in enumerate(data["results"], 1):
        lines.extend([
            f'{i}. [{escape(r["title"])}]({r["issue_url"]}) — {escape(r["repo"])} · {r["difficulty"]}',
            f'   - Fit: {escape(r["fit_reason"])}',
            f'   - Availability: {escape(r["availability"])}',
            f'   - Contributing: {escape(r["contributing_notes"])}',
            f'   - Checked at {escape(r["verified_at"])}: {", ".join(sorted(CHECKS))}',
        ])
    rejected = data.get("rejections", [])
    if isinstance(rejected, list) and rejected:
        lines.append("\nCandidates rejected during verification:")
        for r in rejected:
            if isinstance(r, dict):
                lines.append(f'- {escape(str(r.get("repo", "candidate")))} #{escape(str(r.get("issue_number", "")))}: {escape(str(r.get("reason", "not verified")))}')
    lines.append("\nAvailability reflects inspected public GitHub data at verification time and can change.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--description", required=True)
    parser.add_argument("--language")
    parser.add_argument("--count", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if not args.description.strip() or len(args.description) > 2000:
            raise ClientError("Description must contain 1–2000 characters.")
        endpoint, key, timeout = load_config(args.config)
        ensure_tunnel(endpoint, args.config)
        print("Searching and verifying GitHub issues…", file=sys.stderr)
        data = fetch(endpoint, key, timeout, args.description, args.language, args.count)
        print(json.dumps(data, indent=2) if args.json else render(data))
        return 0
    except (ClientError, ValueError, TypeError) as exc:
        print(f"Good First Issue Finder: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
