import json
import pytest
from test_client_api import client


def config(tmp_path):
    identity = tmp_path / "identity"
    known = tmp_path / "known_hosts"
    identity.write_text("synthetic key fixture")
    known.write_text("synthetic host fixture")
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ssh_tunnel": {"host": "192.0.2.1", "user": "root", "identity_file": str(identity), "known_hosts_file": str(known)}}))
    return p


def test_running_tunnel_does_not_launch_ssh(tmp_path, monkeypatch):
    p = config(tmp_path)
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(client.socket, "create_connection", lambda *a, **kw: Socket())
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **kw: pytest.fail("SSH should not start"))
    client.ensure_tunnel("http://127.0.0.1:8765/find", str(p))


def test_stopped_tunnel_reconnects_with_host_verification(tmp_path, monkeypatch):
    p = config(tmp_path)
    def refused(*a, **kw): raise ConnectionRefusedError()
    monkeypatch.setattr(client.socket, "create_connection", refused)
    calls = []
    def run(args, **kw):
        calls.append(args)
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr(client.subprocess, "run", run)
    client.ensure_tunnel("http://127.0.0.1:8765/find", str(p))
    assert len(calls) == 1
    assert "StrictHostKeyChecking=yes" in calls[0]
    assert "127.0.0.1:8765:127.0.0.1:8000" in calls[0]
    assert calls[0][-1] == "root@192.0.2.1"


def test_failed_reconnect_is_actionable(tmp_path, monkeypatch):
    p = config(tmp_path)
    def refused(*a, **kw): raise ConnectionRefusedError()
    monkeypatch.setattr(client.socket, "create_connection", refused)
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **kw: type("Result", (), {"returncode": 255})())
    with pytest.raises(client.ClientError, match="allow this skill's network request"):
        client.ensure_tunnel("http://127.0.0.1:8765/find", str(p))
