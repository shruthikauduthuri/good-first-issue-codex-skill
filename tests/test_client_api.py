import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import pytest
from fastapi.testclient import TestClient
import service.app as api
from service.schemas import FindResponse


CLIENT = Path(__file__).resolve().parents[1] / ".agents/skills/good-first-issues/scripts/find_issues.py"
spec = importlib.util.spec_from_file_location("gfi_client", CLIENT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def result():
    return {"query": "Python", "results": [{"repo": "team/project", "issue_url": "https://github.com/team/project/issues/7", "title": "Fix [small] bug", "difficulty": "easy", "availability": "Open; no claim or PR detected", "fit_reason": "Small scope", "contributing_notes": "Run tests", "verified_at": datetime.now(timezone.utc).isoformat(), "checks_passed": sorted(client.CHECKS)}]}


def test_private_config_overrides_gui_env(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"endpoint": "http://localhost:8000/find", "api_key": "local-key"}))
    p.chmod(0o600)
    monkeypatch.setenv("GFI_ENDPOINT", "https://different.example/find")
    assert client.load_config(str(p))[:2] == ("http://localhost:8000/find", "local-key")


def test_public_config_rejected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}")
    p.chmod(0o644)
    with pytest.raises(client.ClientError):
        client.load_config(str(p))


@pytest.mark.parametrize("url", ["http://remote.example/find", "https://x/v1", "https://key@x/find", "https://x/find?key=secret"])
def test_unsafe_endpoint_rejected(url):
    with pytest.raises(client.ClientError):
        client.validate_endpoint(url)


@pytest.mark.parametrize("field,value", [("issue_url", "https://evil.example/a"), ("checks_passed", []), ("verified_at", "2020-01-01T00:00:00Z"), ("difficulty", "trivial")])
def test_bad_evidence_rejected(field, value):
    data = result()
    data["results"][0][field] = value
    with pytest.raises(client.ClientError):
        client.validate_response(data, 5)


def test_markdown_keeps_canonical_link():
    text = client.render(client.validate_response(result(), 5))
    assert "https://github.com/team/project/issues/7" in text
    assert r"Fix \[small\] bug" in text


def test_empty_results():
    assert client.render({"query": "q", "results": []}).startswith("No verified results.")


def test_client_real_http_transport():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers["X-API-Key"] == "shared-test-key"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["description"] == "Python"
            data = json.dumps(result()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = client.fetch(f"http://127.0.0.1:{server.server_port}/find", "shared-test-key", 2, "Python", None, 5)
        assert len(data["results"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_api_auth_validation_and_success(monkeypatch):
    monkeypatch.setenv("GFI_API_KEY", "shared-test-key")
    monkeypatch.setattr(api, "run_find", lambda req, timeout: FindResponse(query=req.description, results=[], rejections=[], trace=[], model="hackathon-chat"))
    with TestClient(api.app) as http:
        assert http.post("/find", json={"description": "Python"}).status_code == 401
        assert http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "   "}).status_code == 422
        assert http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python", "count": 11}).status_code == 422
        response = http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python"})
        assert response.status_code == 200
        assert response.json()["results"] == []


def test_api_upstream_failure_is_not_empty_success(monkeypatch):
    monkeypatch.setenv("GFI_API_KEY", "shared-test-key")
    def fail(*args):
        raise RuntimeError("secret-should-not-be-returned")
    monkeypatch.setattr(api, "run_find", fail)
    with TestClient(api.app) as http:
        r = http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python"})
        assert r.status_code == 502
        assert "secret-should-not" not in r.text


def test_api_reports_inference_auth_without_secret(monkeypatch):
    from openai import AuthenticationError
    import httpx
    monkeypatch.setenv("GFI_API_KEY", "shared-test-key")
    def fail(*args):
        raise AuthenticationError("private-secret", response=httpx.Response(401, request=httpx.Request("POST", "https://synthetic.example/v1")), body=None)
    monkeypatch.setattr(api, "run_find", fail)
    with TestClient(api.app) as http:
        r = http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python"})
        assert r.status_code == 502
        assert "Akamai inference rejected" in r.json()["detail"]
        assert "private-secret" not in r.text


def test_long_search_budget_and_deadline_failure(monkeypatch, tmp_path):
    from service.github import DeadlineExceeded
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"endpoint": "http://localhost:8000/find", "api_key": "local-key", "timeout": 330}))
    p.chmod(0o600)
    assert client.load_config(str(p))[2] == 330
    monkeypatch.setenv("GFI_API_KEY", "shared-test-key")
    monkeypatch.setenv("GFI_REQUEST_TIMEOUT", "300")
    budgets = []
    def expired(req, timeout):
        budgets.append(timeout)
        raise DeadlineExceeded("expired")
    monkeypatch.setattr(api, "run_find", expired)
    with TestClient(api.app) as http:
        r = http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python"})
        assert r.status_code == 504
        assert "results" not in r.json()
    assert budgets == [300]


def test_search_budget_cannot_exceed_five_minutes(monkeypatch):
    monkeypatch.setenv("GFI_API_KEY", "shared-test-key")
    monkeypatch.setenv("GFI_REQUEST_TIMEOUT", "301")
    def unexpected(*args):
        pytest.fail("Invalid timeout must be rejected before starting a search")
    monkeypatch.setattr(api, "run_find", unexpected)
    with TestClient(api.app) as http:
        response = http.post("/find", headers={"X-API-Key": "shared-test-key"}, json={"description": "Python"})
        assert response.status_code == 503
