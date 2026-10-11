import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from service.github import VerificationError

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

    def close(self):
        pass

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


