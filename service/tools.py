"""Five real Strands tools and a deterministic evidence ledger."""
import base64
from datetime import datetime, timezone, timedelta
import re
from strands import tool
from .github import repo_path, VerificationError, DeadlineExceeded
from .schemas import FindResponse, IssueResult, Rejection


CLAIM = re.compile(r"\b(i(?:['’]ll| will| am|['’]m| would like to| want to)\s+(?:take|work|fix|handle|implement)|(?:can|may|could)\s+i\s+(?:work|take|fix)|(?:please\s+)?assign\s+(?:this\s+)?(?:to\s+)?(?:me|@\w+)|working\s+on\s+(?:this|it)|(?:already\s+)?claimed|i(?:['’]ve| have)\s+(?:started|opened\s+a\s+pr))\b", re.I)


def now():
    return datetime.now(timezone.utc)


def recent(date, days):
    try:
        return now() - datetime.fromisoformat(date.replace("Z", "+00:00")) <= timedelta(days=days)
    except (TypeError, ValueError):
        return False


class Evidence:
    def __init__(self, github, language=None, require_good_first=False):
        self.gh = github
        self.language = language
        self.require_good_first = require_good_first
        self.candidate_limit = 40 if require_good_first else 20
        self.candidates = {}
        self.availability = {}
        self.guides = {}
        self.health = {}
        self.scores = {}
        self.rejections = {}
        self.trace = []
        self.calls = 0
        self.search_calls = 0

    def record(self, name, **facts):
        self.calls += 1
        self.gh.remaining()
        if self.calls > 90:
            raise VerificationError("Tool budget exceeded", "tool_budget")
        self.trace.append({"tool": name, "at": now().isoformat(), **facts})

    def candidate(self, repo, number):
        repo_path(repo)
        key = (repo, number)
        if key not in self.candidates:
            raise VerificationError("Candidate must first be returned by the search tool")
        return key

    def reject(self, repo, number, reason):
        self.rejections[(repo, number)] = Rejection(repo=repo, issue_number=number, reason=reason)
        self.record("candidate_rejected", repo=repo, issue_number=number, reason=reason)
        return {"available": False, "reason": reason}

    def search(self, query, language=None, labels=None):
        self.record("search_github_issues")
        if len(self.candidates) >= self.candidate_limit:
            return {"candidates": [], "note": "Candidate budget reached"}
        # Model supplies keywords/repo qualifiers; hard gates cannot be overridden.
        query = re.sub(r'\b(?:is|state|label|language):(?:"[^"]*"|\S+)', "", query).strip()[:300]
        label_values = [x for x in (labels or ["good first issue", "help wanted"]) if x in {"good first issue", "help wanted"}]
        if self.require_good_first:
            label_values = ["good first issue"]
        if not label_values:
            label_values = ["good first issue"]
        clauses = "label:" + ",".join(f'"{x}"' for x in label_values)
        lang = self.language or language
        if lang and not re.fullmatch(r"[\w+#.-]+", lang):
            raise VerificationError("Unsupported language filter")
        q = f'{query} is:issue is:open {clauses}'
        if lang:
            q += f" language:{lang}"
        data = self.gh.get("/search/issues", {"q": q, "sort": "updated", "order": "desc", "per_page": 20})
        if data.get("incomplete_results"):
            raise VerificationError("GitHub search results incomplete")
        rows = []
        for item in data.get("items", []):
            if "pull_request" in item or item.get("state") != "open":
                continue
            repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
            repo_path(repo)
            key = (repo, item["number"])
            if key not in self.candidates and len(self.candidates) >= self.candidate_limit:
                break
            self.candidates[key] = item
            rows.append({"repo": repo, "issue_number": item["number"], "title": item["title"], "body": (item.get("body") or "")[:1200], "updated_at": item["updated_at"]})
        return {"candidates": rows, "total_found": data.get("total_count", 0)}

    def check(self, repo, number, fresh=False):
        key = self.candidate(repo, number)
        self.record("check_issue_availability", repo=repo, issue_number=number, fresh=fresh)
        self.availability.pop(key, None)
        p = repo_path(repo) + f"/issues/{number}"
        try:
            issue = self.gh.get(p, fresh=fresh)
            self.candidates[key] = issue
            if issue.get("state") != "open" or "pull_request" in issue or issue.get("locked"):
                return self.reject(repo, number, "Issue closed, locked, or is a pull request")
            if self.require_good_first and "good first issue" not in {x.get("name", "").lower() for x in issue.get("labels", [])}:
                return self.reject(repo, number, "Missing good first issue label")
            if issue.get("assignees"):
                return self.reject(repo, number, "Issue has an assignee")
            if not recent(issue.get("updated_at"), 180):
                return self.reject(repo, number, "Issue has not been updated in 180 days")
            comments = self.gh.pages(p + "/comments", fresh=fresh)
            for c in comments:
                # Conservative: old claims are still claims, even after a later release.
                if CLAIM.search(c.get("body") or ""):
                    return self.reject(repo, number, "Claim or work-in-progress comment detected")
            timeline = self.gh.pages(p + "/timeline", fresh=fresh)
            for event in timeline:
                source = event.get("source", {}).get("issue", {})
                if source.get("pull_request"):
                    # Re-fetch; timeline state may lag behind the actual PR.
                    m = re.fullmatch(r"https://api.github.com/repos/([\w.-]+/[\w.-]+)/issues/(\d+)", source.get("url", ""))
                    if not m:
                        raise VerificationError("Linked pull request cannot be resolved")
                    linked = self.gh.get(repo_path(m[1]) + f"/pulls/{m[2]}", fresh=fresh)
                    if linked.get("state") == "open":
                        return self.reject(repo, number, "Cross-referenced open pull request")
                elif event.get("event") in {"connected", "referenced"} and event.get("commit_id"):
                    # GraphQL closing references can be unavailable to this REST token.
                    return self.reject(repo, number, "Linked development activity; availability uncertain")
            # Also scan open PR bodies: references may not yet appear in timeline.
            prs = self.gh.pages(repo_path(repo) + "/pulls", {"state": "open"}, fresh=fresh, max_pages=3)
            mention = re.compile(r"(?<![\w/])#" + str(number) + r"\b|" + re.escape(repo) + r"#" + str(number) + r"\b|https://github\.com/" + re.escape(repo) + r"/issues/" + str(number) + r"\b", re.I)
            for pr in prs:
                if mention.search((pr.get("body") or "") + " " + (pr.get("title") or "")):
                    return self.reject(repo, number, "Open pull request references this issue")
            # PR links in issue bodies/comments can refer to cross-repository work.
            text = (issue.get("body") or "") + "\n" + "\n".join(c.get("body") or "" for c in comments)
            for linked_repo, pr_num in set(re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)\b", text)):
                pr = self.gh.get(repo_path(linked_repo) + f"/pulls/{pr_num}", fresh=fresh)
                if pr.get("state") == "open":
                    return self.reject(repo, number, "Issue discussion links an open pull request")
            result = {"available": True, "verified_at": now().isoformat(), "checks_passed": ["issue_open", "no_assignees", "no_claim_comment", "no_open_pr"]}
            self.availability[key] = result
            self.rejections.pop(key, None)
            return result
        except DeadlineExceeded:
            raise
        except VerificationError as exc:
            if exc.code.startswith("github_"):
                raise
            return self.reject(repo, number, str(exc))

    def contributing(self, repo):
        self.record("read_contributing", repo=repo)
        if repo in self.guides:
            return self.guides[repo]
        root = repo_path(repo)
        def find(paths):
            for path in paths:
                obj = self.gh.get(root + "/contents/" + path, optional=True)
                if obj and obj.get("type") == "file":
                    excerpt = ""
                    if obj.get("encoding") == "base64":
                        excerpt = base64.b64decode(obj.get("content", "")).decode("utf-8", errors="replace")[:1800]
                    return {"path": path, "url": obj.get("html_url"), "excerpt": excerpt}
            return None
        guide = find(["CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", "CONTRIBUTING.rst"])
        coc = find(["CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md"])
        template = find([".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md"])
        result = {"has_contributor_guide": bool(guide), "guide": guide, "has_code_of_conduct": bool(coc), "has_pr_template": bool(template)}
        self.guides[repo] = result
        return result

    def repo_health(self, repo):
        self.record("repo_health", repo=repo)
        if repo in self.health:
            return self.health[repo]
        meta = self.gh.get(repo_path(repo))
        commits = self.gh.get(repo_path(repo) + "/commits", {"per_page": 1})
        commit_at = commits[0]["commit"]["committer"]["date"] if commits else None
        since = (now() - timedelta(days=90)).date().isoformat()
        merged = self.gh.get("/search/issues", {"q": f"repo:{repo} is:pr is:merged merged:>={since}", "per_page": 1})
        result = {"active": not meta.get("archived") and not meta.get("disabled") and recent(commit_at, 90), "last_commit_at": commit_at, "recent_merged_prs": merged.get("total_count", 0), "stars": meta.get("stargazers_count", 0), "size_kb": meta.get("size", 0), "language": meta.get("language")}
        self.health[repo] = result
        return result

    def difficulty(self, repo, number):
        key = self.candidate(repo, number)
        self.record("score_difficulty", repo=repo, issue_number=number)
        issue = self.candidates[key]
        text = issue["title"] + " " + (issue.get("body") or "")
        labels = [x["name"].lower() for x in issue.get("labels", [])]
        files = len(set(re.findall(r"\b[\w/-]+\.(?:py|tsx?|jsx?|rs|go|java|cpp|md)\b", text)))
        hard = any(x in text.lower() for x in ["breaking change", "architecture", "migration", "race condition", "distributed"])
        beginner = "good first issue" in labels or "beginner" in labels
        difficulty = "hard" if hard or files > 5 else "easy" if beginner and files <= 2 and len(text) < 4000 else "medium"
        result = {"difficulty": difficulty, "reason": f"{files} named files; {'beginner label' if beginner else 'no beginner label'}; {'broad/complex signals' if hard else 'no major complexity signal'}", "body_chars": len(text), "comment_count": issue.get("comments", 0)}
        self.scores[key] = result
        return result

    def finalize(self, selection, request, model):
        rows = []
        seen = set()
        for pick in selection.results[:request.count]:
            key = (pick.repo, pick.issue_number)
            if key in seen:
                continue
            seen.add(key)
            # The model cannot invent evidence, even by fabricating structured JSON.
            if key not in self.candidates or key not in self.availability or key not in self.scores:
                self.reject(pick.repo, pick.issue_number, "Agent nominated an issue without search, availability, and difficulty evidence")
                continue
            guide = self.guides.get(pick.repo)
            health = self.health.get(pick.repo)
            if not guide or not guide["has_contributor_guide"] or not health or not health["active"]:
                self.reject(pick.repo, pick.issue_number, "Missing contributor guide or active-repository evidence")
                continue
            if not self.check(pick.repo, pick.issue_number, fresh=True)["available"]:
                continue
            issue = self.candidates[key]
            score = self.scores[key]
            # LLM may raise difficulty, but cannot downplay hard deterministic signals.
            order = {"easy": 0, "medium": 1, "hard": 2}
            level = max([score["difficulty"], pick.difficulty], key=order.get)
            guide_url = guide["guide"]["url"] or guide["guide"]["path"]
            rows.append(IssueResult(repo=pick.repo, issue_url=f"https://github.com/{pick.repo}/issues/{pick.issue_number}", title=issue["title"], difficulty=level, difficulty_reason=score["reason"], availability="Open; no assignee, claim comment, or open PR detected", fit_reason=pick.fit_reason, contributing_notes=f"Guide: {guide_url}; code of conduct: {guide['has_code_of_conduct']}; PR template: {guide['has_pr_template']}", verified_at=self.availability[key]["verified_at"], checks_passed=self.availability[key]["checks_passed"] + ["repo_active", "has_contributor_guide"]))
            rows[-1].match_type = pick.match_type
        self.gh.remaining()
        return FindResponse(query=request.description, results=rows, rejections=list(self.rejections.values()), trace=self.trace, model=model)


def build_tools(evidence, grouped=False, auto_verify=False, count=1):
    @tool
    def search_github_issues(query: str, language: str = "", labels: list[str] | None = None) -> dict:
        """Search up to 20 open beginner issues using short topic keywords or repo qualifiers.

        Args:
            query: GitHub search keywords; don't combine many topics with AND.
            language: Optional primary programming language.
            labels: good first issue or help wanted; multiple labels are ORed by GitHub.
        """
        if auto_verify:
            if evidence.search_calls >= 3:
                return {"candidates": [], "note": "Search budget exhausted. Return verified nominations or an empty results list."}
            evidence.search_calls += 1
        result = evidence.search(query, language, labels)
        if not auto_verify:
            return result
        eligible = []
        # Check low-discussion candidates first; claims are more likely in long threads.
        candidates = sorted(result["candidates"], key=lambda r: (
            bool(evidence.candidates[(r["repo"], r["issue_number"])].get("assignees")),
            evidence.candidates[(r["repo"], r["issue_number"])].get("comments", 0)))
        for candidate in candidates[:8]:
            repo, number = candidate["repo"], candidate["issue_number"]
            if (repo, number) in evidence.rejections:
                continue
            if not evidence.check(repo, number)["available"]:
                continue
            health = evidence.repo_health(repo)
            if not health["active"]:
                evidence.reject(repo, number, "Repository inactive")
                continue
            guide = evidence.contributing(repo)
            if not guide["has_contributor_guide"]:
                evidence.reject(repo, number, "Missing contributor guide")
                continue
            eligible.append({**candidate, "eligible": True,
                             "difficulty": evidence.difficulty(repo, number),
                             "health": health})
            if len(eligible) >= count:
                break
        return {"candidates": eligible, "total_found": result.get("total_found", 0),
                "rejections": [r.model_dump() for r in evidence.rejections.values()],
                "note": "Only these candidates passed verification. Judge topic fit; nominate or try a different short query."}

    @tool
    def check_issue_availability(repo: str, issue_number: int) -> dict:
        """Check comments, assignees, timeline and open PRs for a searched issue.

        Args:
            repo: owner/name from search results.
            issue_number: Issue number from search results.
        """
        return evidence.check(repo, issue_number)

    @tool
    def read_contributing(repo: str) -> dict:
        """Read contributor guidance and check for code of conduct and PR template.

        Args:
            repo: owner/name from search results.
        """
        return evidence.contributing(repo)

    @tool
    def score_difficulty(repo: str, issue_number: int) -> dict:
        """Score actual issue scope using labels, file mentions and complexity signals.

        Args:
            repo: owner/name from search results.
            issue_number: Issue number from search results.
        """
        return evidence.difficulty(repo, issue_number)

    @tool
    def repo_health(repo: str) -> dict:
        """Check latest default-branch commit, archive status, recent merges and stars.

        Args:
            repo: owner/name from search results.
        """
        return evidence.repo_health(repo)

    @tool
    def verify_candidates(candidates: list[dict]) -> dict:
        """Verify up to four searched candidates together. Each needs repo and issue_number.

        Performs availability, contributing, difficulty and repository health checks.
        Only eligible candidates may be nominated. Rejected candidates include reasons.
        """
        if not 1 <= len(candidates) <= 4:
            return {"error": "Supply one to four candidates."}
        rows = []
        for candidate in candidates:
            repo, number = candidate.get("repo"), candidate.get("issue_number")
            available = evidence.check(repo, number)
            row = {"repo": repo, "issue_number": number, "eligible": False, "availability": available}
            if available["available"]:
                row["difficulty"] = evidence.difficulty(repo, number)
                row["health"] = evidence.repo_health(repo)
                row["contributing"] = evidence.contributing(repo)
                row["eligible"] = row["health"]["active"] and row["contributing"]["has_contributor_guide"]
            rows.append(row)
        return {"candidates": rows}

    if auto_verify:
        return [search_github_issues]
    if grouped:
        return [search_github_issues, verify_candidates]
    return [search_github_issues, check_issue_availability, read_contributing, score_difficulty, repo_health]
