# Good First Issue Finder for Codex

A Codex desktop skill backed by a real **Strands Agents** tool loop running on **Akamai Cloud / Linode**, using the workshop's hosted inference. Describe your interests and get a ranked shortlist with GitHub links, difficulty, contributor guidance, verification timestamps, and candidate rejection reasons.

Example in the Codex composer:

```text
$good-first-issues Beginner-friendly Python agent frameworks, small bug fixes, active maintainers
```

Use the skill picker if your desktop version uses a different mention shortcut. The client requires Python 3.9+ with no third-party dependencies; the service requires Python 3.11+.

## What is built

```text
Codex desktop → skill / Python client → POST /find on Linode
                                         ↓
                              Strands Agent / Akamai inference
                                         ↓
                                five read-only GitHub tools
                                         ↓
                              evidence validation + final recheck
                                         ↓
                                  ranked verified shortlist
```

The model plans searches, chooses candidates, uses tools, and judges fit and difficulty. The server supplies all titles, links, timestamps, and checks from an evidence ledger; fabricated model nominations cannot enter the shortlist.

Five tools: `search_github_issues`, `check_issue_availability`, `read_contributing`, `score_difficulty`, and `repo_health`. The agent searches at most 20 unique candidates. GitHub calls are cached only within a request; final availability checks bypass the cache.

Issues are rejected for assignees, claim/work-in-progress comments, open PR references, locked/closed status, or no update in 180 days. Repositories require a contributor guide and a default-branch commit within 90 days. Comments and timeline are paginated up to 500 records each; open PRs up to 300. Reaching a pagination cap rejects the candidate rather than certifying incomplete checks. Availability is a conservative assessment of inspected public data, not a guarantee or reservation. Old claim comments are conservatively rejected even if a later comment releases the issue. Contributor guides currently support common root, `.github`, and `docs` paths; missing guidance yields no nomination.

## Install in Codex desktop

From this repository:

```sh
python3 scripts/install_skill.py
```

The helper installs to `~/.agents/skills/good-first-issues`, the current user-scoped discovery directory, and never overwrites an existing installation. The repository also contains a discoverable copy in `.agents/skills/good-first-issues`. Avoid installing the same skill twice in a project if duplicate picker entries matter. Older app versions may use `~/.codex/skills`; install there explicitly with `--target ~/.codex/skills` if your version requires it.

Select **Good First Issue Finder** in the skill picker. Codex normally detects skill changes; restart if it does not appear. [Official skill discovery guidance](https://learn.chatgpt.com/docs/build-skills).

## Set up the Strands service

On your existing Linode, or locally for development:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally. The confirmed workshop defaults are:

```dotenv
AKAMAI_BASE_URL=https://ws.akamai-workshops.com/v1
AKAMAI_MODEL=hackathon-chat
```

Supply `AKAMAI_API_KEY` (organizer/team inference key), `GITHUB_TOKEN` (read access to public issues/repos), and `GFI_API_KEY` (a new random shared key for this finder). Keep all real values out of Git and chat. Generate the shared key with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and save it locally. The shared finder key is distinct from the inference key.

Test the actual Strands integration before starting the service:

```sh
.venv/bin/python scripts/smoke_inference.py
```

The smoke test proves a Python tool is called through Akamai inference and structured output is validated. A text-only answer fails this check. Then start:

```sh
.venv/bin/uvicorn service.app:app --env-file .env --host 127.0.0.1 --port 8000
```

`GET /health` shows configuration readiness, not proof of upstream connectivity. `POST /find` requires `X-API-Key`; accepts `description`, optional `language`, and `count` (1–10). Provider failures/timeouts return errors, never partial successful results.

## Run on existing Linode

Copy this repository to the existing host using your usual SSH access. After privately creating `.env`, if Docker Compose is available:

```sh
docker compose up -d --build
docker compose logs --tail 50 finder
```

The container uses an unprivileged user and binds only to Linode's loopback. For a demo, connect from your laptop:

```sh
ssh -N -L 8000:127.0.0.1:8000 YOUR_SSH_USER@YOUR_LINODE_IP
```

Configure the skill to use `http://127.0.0.1:8000/find`. For a public endpoint, place your existing HTTPS reverse proxy in front of Linode's loopback port and use `https://YOUR_DOMAIN/find`; set its request timeout to at least 90 seconds. Do not expose an unencrypted remote endpoint. The Python client rejects remote HTTP and redirects.

The project does not provision or purchase cloud resources. Deployment requires your existing host access and server credentials. A live cloud result and the approximate 90-second target must be measured after configuration; offline tests cannot establish those outcomes.

## Configure the installed desktop client

```sh
python3 ~/.agents/skills/good-first-issues/scripts/configure.py
```

Enter the finder `/find` URL and shared finder key using the hidden prompt. It writes a 0600 `scripts/config.json` so the app works when launched from the Dock. Existing config is never overwritten. The client prefers this file, then environment variables (`GFI_ENDPOINT`, `GFI_API_KEY`, `GFI_TIMEOUT`). `GFI_CONFIG` or `--config` selects a private config elsewhere. The Akamai inference URL is not the finder URL.

Test from any directory:

```sh
python3 ~/.agents/skills/good-first-issues/scripts/find_issues.py \
  --description "Python agent frameworks, small bug fixes" --language Python --count 5
```

In Codex, allow outbound access if the app asks. An unreachable endpoint, invalid key, or timeout produces an actionable error without made-up issues.

## Verify and demo

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests use synthetic GitHub data and local HTTP; they do not claim live issue availability. `scripts/smoke_inference.py` is the separate live inference test.

For judges: show the Linode service, run the inference smoke test, invoke the skill in a fresh Codex chat, show a rejection for a claimed/PR-covered issue, then open a returned GitHub issue. Use the client's `--json` option to inspect the complete `trace` with real tool names, decision timestamps, and rejection reasons. If no candidate was rejected in that run, do not fabricate a rejection. The service is read-only and never claims issues or creates PRs.

References: [Strands Python SDK](https://github.com/strands-agents/sdk-python), [Strands quickstart](https://strandsagents.com/docs/user-guide/sdk/quickstart/overview/), [Akamai HackMidwest inference reference](https://github.com/akamai-developers/akamai-workshop-hackmidwest/blob/main/docs/inference.md), [Akamai Linode workshop](https://github.com/akamai-developers/akamai-workshop-hackmidwest/blob/main/docs/03_body.md).
