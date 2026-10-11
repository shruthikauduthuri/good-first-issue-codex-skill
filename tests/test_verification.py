import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
import pytest
from service.github import GitHub, VerificationError
from service.schemas import AgentSelection, FindRequest, Pick
from service.tools import Evidence, build_tools


def stamp(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class FakeGitHub:
    def __init__(self):
        self.issue = {"number": 7, "title": "Fix small Python bug", "body": "Update helper.py", "state": "open", "assignees": [], "updated_at": stamp(), "labels": [{"name": "good first issue"}], "repository_url": "https://api.github.com/repos/team/project", "comments": 0}
        self.comments = []
        self.timeline = []
        self.prs = []
        self.linked_pr = {"state": "closed"}
        self.truncated = False
        self.active = True
        self.guide = True
        self.search_query = ""
        self.fresh_issue = None

    def remaining(self):
        return 60

    def get(self, path, params=None, fresh=False, optional=False):
        if path == "/search/issues":
            if "is:issue" in params["q"]:
                self.search_query = params["q"]
            return {"items": [deepcopy(self.issue)], "total_count": 1}
        if path == "/repos/team/project/issues/7":
            return deepcopy(self.fresh_issue if fresh and self.fresh_issue else self.issue)
        if "/pulls/" in path:
            return self.linked_pr
        if "/contents/" in path:
            if self.guide and path.endswith("/CONTRIBUTING.md"):
                return {"type": "file", "html_url": "https://github.com/team/project/blob/main/CONTRIBUTING.md", "encoding": "base64", "content": base64.b64encode(b"Run pytest before submitting").decode()}
            return None
        if path.endswith("/commits"):
            return [{"commit": {"committer": {"date": stamp(0 if self.active else 120)}}}]
        if path == "/repos/team/project":
            return {"archived": False, "language": "Python"}
        raise AssertionError(path)

    def pages(self, path, params=None, fresh=False, max_pages=5):
        if self.truncated:
            raise VerificationError("Pagination limit reached; availability cannot be verified")
        if path.endswith("/comments"):
            return self.comments
        if path.endswith("/timeline"):
            return self.timeline
        if path.endswith("/pulls"):
            return self.prs
        raise AssertionError(path)


@pytest.mark.parametrize("failure", ["assigned", "claimed", "inactive", "no_guide"])
def test_automatic_search_does_not_expose_ineligible_candidates(failure):
    gh = FakeGitHub()
    if failure == "assigned":
        gh.issue["assignees"] = [{"login": "contributor"}]
    elif failure == "claimed":
        gh.comments = [{"body": "I will work on this"}]
    elif failure == "inactive":
        gh.active = False
    else:
        gh.guide = False
    ledger = Evidence(gh)
    result = build_tools(ledger, auto_verify=True)[0](query="Python")
    assert result["candidates"] == []
    assert result["rejections"]


def test_automatic_search_caps_queries():
    ledger = Evidence(FakeGitHub())
    search = build_tools(ledger, auto_verify=True)[0]
    for _ in range(3):
        search(query="Python")
    before = ledger.calls
    assert search(query="Python")["candidates"] == []
    assert ledger.calls == before


def test_good_first_label_is_enforced_in_search_and_fresh_check():
    gh = FakeGitHub()
    ledger = Evidence(gh, language="Python", require_good_first=True)
    ledger.search("unit test", labels=["help wanted"])
    assert 'label:"good first issue"' in gh.search_query
    assert "help wanted" not in gh.search_query
    gh.issue["labels"] = [{"name": "help wanted"}]
    assert not ledger.check("team/project", 7, fresh=True)["available"]


def test_empty_model_selection_returns_verified_related_issue(monkeypatch):
    from types import SimpleNamespace
    import service.agent as module
    gh = FakeGitHub()
    gh.close = lambda: None
    monkeypatch.setattr(module, "Agent", lambda **kwargs: lambda message: SimpleNamespace(structured_output=AgentSelection()))
    cfg = {"GITHUB_TOKEN": "test", "AKAMAI_API_KEY": "test", "base_url": "https://example.com/v1", "model": "test"}
    response = module.run_find(FindRequest(description="Python async race condition", count=1), config=cfg, github=gh)
    assert len(response.results) == 1
    assert response.results[0].match_type == "related"
    assert "no_open_pr" in response.results[0].checks_passed
    assert "language:Python" in gh.search_query


def test_related_fallback_never_returns_help_wanted_only(monkeypatch):
    from types import SimpleNamespace
    import service.agent as module
    gh = FakeGitHub()
    gh.close = lambda: None
    gh.issue["labels"] = [{"name": "help wanted"}]
    monkeypatch.setattr(module, "Agent", lambda **kwargs: lambda message: SimpleNamespace(structured_output=AgentSelection()))
    cfg = {"GITHUB_TOKEN": "test", "AKAMAI_API_KEY": "test", "base_url": "https://example.com/v1", "model": "test"}
    response = module.run_find(FindRequest(description="Python async", count=1), config=cfg, github=gh)
    assert response.results == []


@pytest.fixture
def evidence():
    e = Evidence(FakeGitHub(), language="Python")
    e.search("agent", language="JavaScript")
    return e


def prepare(e):
    assert e.check("team/project", 7)["available"]
    e.contributing("team/project")
    e.repo_health("team/project")
    e.difficulty("team/project", 7)


def finalize(e, number=7):
    return e.finalize(AgentSelection(results=[Pick(repo="team/project", issue_number=number, fit_reason="Small Python helper change", difficulty="easy")]), FindRequest(description="small Python bugs"), "hackathon-chat")


def test_all_checks_and_canonical_link(evidence):
    prepare(evidence)
    response = finalize(evidence)
    assert len(response.results) == 1
    r = response.results[0]
    assert r.issue_url == "https://github.com/team/project/issues/7"
    assert len(r.checks_passed) == 6
    assert "language:Python" in evidence.gh.search_query
    assert 'label:"good first issue","help wanted"' in evidence.gh.search_query
    assert {t["tool"] for t in response.trace} >= {"search_github_issues", "check_issue_availability", "read_contributing", "score_difficulty", "repo_health"}


@pytest.mark.parametrize("text", ["I'll take this", "Can I work on this?", "Please assign me", "I’m working on this", "I would like to work on this", "This is already claimed"])
def test_claim_comments_rejected(evidence, text):
    evidence.gh.comments = [{"body": text}]
    assert not evidence.check("team/project", 7)["available"]


def test_assignee_rejected(evidence):
    evidence.gh.issue["assignees"] = [{"login": "someone"}]
    assert not evidence.check("team/project", 7)["available"]


def test_timeline_open_pr_rejected(evidence):
    evidence.gh.timeline = [{"source": {"issue": {"pull_request": {}, "url": "https://api.github.com/repos/team/project/issues/9"}}}]
    evidence.gh.timeline[0]["source"]["issue"]["pull_request"] = {"url": "https://api.github.com/repos/team/project/pulls/9"}
    evidence.gh.linked_pr = {"state": "open"}
    assert not evidence.check("team/project", 7)["available"]


@pytest.mark.parametrize("body", ["Fixes #7", "Fixes team/project#7", "Related https://github.com/team/project/issues/7"])
def test_open_pr_body_rejected(evidence, body):
    evidence.gh.prs = [{"body": body, "title": "Fix"}]
    assert not evidence.check("team/project", 7)["available"]


def test_different_issue_number_not_rejected(evidence):
    evidence.gh.prs = [{"body": "Fixes #70"}]
    assert evidence.check("team/project", 7)["available"]


def test_pagination_fail_closed(evidence):
    evidence.gh.truncated = True
    assert not evidence.check("team/project", 7)["available"]


def test_stale_issue_rejected(evidence):
    evidence.gh.issue["updated_at"] = stamp(181)
    assert not evidence.check("team/project", 7)["available"]


def test_fabricated_issue_never_returned(evidence):
    assert not finalize(evidence, 999).results


def test_missing_checks_never_returned(evidence):
    assert not finalize(evidence).results


@pytest.mark.parametrize("missing", ["guide", "active"])
def test_bad_repository_never_returned(evidence, missing):
    setattr(evidence.gh, missing, False)
    prepare(evidence)
    assert not finalize(evidence).results


def test_final_recheck_drops_new_assignee(evidence):
    prepare(evidence)
    evidence.gh.fresh_issue = {**evidence.gh.issue, "assignees": [{"login": "new"}]}
    assert not finalize(evidence).results


def test_difficulty_cannot_downplay_complex_issue(evidence):
    evidence.gh.issue["body"] = "Architecture migration"
    prepare(evidence)
    assert finalize(evidence).results[0].difficulty == "hard"


def test_real_pagination_reads_later_pages():
    gh = GitHub("fake-token", time.monotonic() + 30)
    gh.get = lambda path, params, **kw: [{"body": "first"}] * 100 if params["page"] == 1 else [{"body": "I'll take this"}]
    assert len(gh.pages("/repos/a/b/issues/1/comments")) == 101
    gh.close()


def test_five_registered_strands_tools(evidence):
    assert len(build_tools(evidence)) == 5
