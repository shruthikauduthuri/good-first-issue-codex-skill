import asyncio
import hmac
import logging
import os
import threading
from fastapi import FastAPI, Header, HTTPException
from openai import AuthenticationError
from .agent import run_find
from .github import VerificationError, DeadlineExceeded
from .schemas import FindRequest, FindResponse


app = FastAPI(title="Good First Issue Finder", docs_url=None, redoc_url=None)
log = logging.getLogger("gfi")
slots = threading.BoundedSemaphore(2)


@app.get("/health")
def health():
    required = ["AKAMAI_API_KEY", "GITHUB_TOKEN", "GFI_API_KEY"]
    configured = all(os.getenv(k, "").strip() for k in required)
    return {"status": "ready" if configured else "needs_configuration", "agent": "strands", "model": os.getenv("AKAMAI_MODEL", "hackathon-chat")}


@app.post("/find", response_model=FindResponse)
async def find(request: FindRequest, x_api_key: str = Header(default="")):
    expected = os.getenv("GFI_API_KEY", "")
    if not expected:
        raise HTTPException(503, "Service is not configured")
    if not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid API key")
    try:
        timeout = float(os.getenv("GFI_REQUEST_TIMEOUT", "80"))
        if not 5 <= timeout <= 85:
            raise ValueError()
    except ValueError:
        raise HTTPException(503, "Invalid server timeout configuration")
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Service is busy")

    def work():
        try:
            return run_find(request, timeout)
        finally:
            # A client timeout does not free the slot while its worker still runs.
            slots.release()

    try:
        return await asyncio.wait_for(asyncio.to_thread(work), timeout=timeout)
    except (asyncio.TimeoutError, DeadlineExceeded):
        raise HTTPException(504, "Verification time budget exceeded; no results returned")
    except AuthenticationError:
        raise HTTPException(502, "Akamai inference rejected the configured team API key (HTTP 401)")
    except VerificationError:
        raise HTTPException(502, "Verification failed; check server configuration and GitHub access")
    except Exception as exc:
        # Log the class only. Provider exceptions may embed sensitive request data.
        log.error("Finder failed: %s", type(exc).__name__)
        raise HTTPException(502, "Agent or upstream service failed; no results returned")
