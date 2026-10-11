"""Read-only GitHub API with request-local caching and bounded pagination."""
import time
import re
import requests


class VerificationError(Exception):
    pass


class DeadlineExceeded(VerificationError):
    pass


def repo_path(repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise VerificationError("Invalid repository identifier")
    return f"/repos/{repo}"


class GitHub:
    def __init__(self, token, deadline, max_requests=160):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "good-first-issue-finder"})
        self.deadline = deadline
        self.max_requests = max_requests
        self.requests = 0
        self.cache = {}

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise DeadlineExceeded("Verification time budget exceeded")
        return left

    def get(self, path, params=None, fresh=False, optional=False):
        self.remaining()
        if not path.startswith("/") or path.startswith("//") or ".." in path:
            raise VerificationError("Invalid GitHub API path")
        cache_key = (path, tuple(sorted((params or {}).items())))
        if not fresh and cache_key in self.cache:
            return self.cache[cache_key]
        self.requests += 1
        if self.requests > self.max_requests:
            raise VerificationError("GitHub request budget exceeded")
        try:
            r = self.session.get("https://api.github.com" + path, params=params, timeout=min(8, self.remaining()), allow_redirects=False)
            if optional and r.status_code == 404:
                data = None
            elif r.status_code in {403, 429}:
                raise VerificationError("GitHub denied access or rate limit reached")
            elif r.status_code != 200:
                raise VerificationError(f"GitHub returned HTTP {r.status_code}")
            else:
                data = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise VerificationError("GitHub request failed") from exc
        self.cache[cache_key] = data
        return data

    def pages(self, path, params=None, fresh=False, max_pages=5):
        out = []
        for page in range(1, max_pages + 1):
            rows = self.get(path, {**(params or {}), "per_page": 100, "page": page}, fresh=fresh)
            if not isinstance(rows, list):
                raise VerificationError("Unexpected GitHub page response")
            out.extend(rows)
            if len(rows) < 100:
                return out
        # Never certify a candidate if comments, timeline or PRs were truncated.
        raise VerificationError("Pagination limit reached; availability cannot be verified")

    def close(self):
        self.session.close()
