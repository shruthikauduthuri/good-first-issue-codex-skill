"""Safe public failure categories, including errors wrapped by Strands."""
from openai import AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError
from strands.types.exceptions import ModelThrottledException
from .github import VerificationError, DeadlineExceeded

MESSAGES = {
    'inference_auth': 'Inference endpoint rejected its API key. Check the endpoint credentials.',
    'inference_rate_limit': 'Inference endpoint is rate limited. Wait before retrying.',
    'inference_timeout': 'An inference request timed out. Retry later or compare another endpoint.',
    'inference_connection': 'Cannot connect to the inference endpoint.',
    'deadline_exceeded': 'The five-minute search budget expired; no unverified results returned.',
    'reasoning_budget': 'The agent exhausted its model-turn budget. Narrow the search.',
    'tool_budget': 'The verification tool budget was exhausted. Narrow the search.',
    'github_rate_limit': 'GitHub denied access or rate limited the request. Check token permissions and quota.',
    'github_auth': 'GitHub rejected its token. Check server credentials.',
    'github_connection': 'A GitHub request failed. Retry later.',
    'configuration': 'Server configuration is incomplete or invalid.',
    'structured_output': 'The model did not return valid structured recommendations.',
    'verification_failed': 'Evidence verification failed; no unverified results returned.',
    'upstream_failure': 'The agent or an upstream service failed.',
}

def classify(exc):
    pending, seen = [exc], set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen: continue
        seen.add(id(current))
        code = None
        if isinstance(current, DeadlineExceeded): code = 'deadline_exceeded'
        elif isinstance(current, AuthenticationError): code = 'inference_auth'
        elif isinstance(current, (RateLimitError, ModelThrottledException)): code = 'inference_rate_limit'
        elif isinstance(current, APITimeoutError): code = 'inference_timeout'
        elif isinstance(current, APIConnectionError): code = 'inference_connection'
        elif isinstance(current, VerificationError): code = current.code
        if code:
            status = 504 if code in {'deadline_exceeded', 'inference_timeout'} else 503 if code in {'configuration','inference_rate_limit','github_rate_limit'} else 502
            return status, code, MESSAGES.get(code, MESSAGES['verification_failed'])
        pending.extend(x for x in [getattr(current,'original_exception',None),current.__cause__,current.__context__] if isinstance(x, BaseException))
    return 502, 'upstream_failure', MESSAGES['upstream_failure']
