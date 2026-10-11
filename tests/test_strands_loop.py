"""Run the real Strands loop and OpenAI adapter with a synthetic inference transport."""
import asyncio
import json
import httpx
import pytest
from openai import AsyncOpenAI
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.tools.executors import SequentialToolExecutor
from service.agent import Budget, SYSTEM_PROMPT
from service.schemas import AgentSelection, FindRequest
from service.tools import Evidence, build_tools
from test_verification import FakeGitHub


@pytest.mark.parametrize("grouped", [False, True, "auto"])
def test_actual_strands_tool_loop_and_final_evidence(grouped):
    ledger = Evidence(FakeGitHub())
    sequence = [
        ("search_github_issues", {"query": "Python"}),
        ("check_issue_availability", {"repo": "team/project", "issue_number": 7}),
        ("read_contributing", {"repo": "team/project"}),
        ("repo_health", {"repo": "team/project"}),
        ("score_difficulty", {"repo": "team/project", "issue_number": 7}),
    ]
    if grouped:
        sequence = [("search_github_issues", {"query": "Python"}), ("verify_candidates", {"candidates": [{"repo": "team/project", "issue_number": 7}]})]
    if grouped == "auto":
        sequence = [("search_github_issues", {"query": "Python"})]
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        specs = {t["function"]["name"]: t for t in payload["tools"]}
        n = len(calls)
        if n < len(sequence):
            name, args = sequence[n]
        else:
            # Select the actual schema tool registered by Strands, not a guessed name.
            name = next(name for name in specs if name not in {x[0] for x in sequence})
            args = {"results": [{"repo": "team/project", "issue_number": 7, "fit_reason": "Small Python helper fix", "difficulty": "easy"}]}
        assert name in specs
        calls.append(name)
        return httpx.Response(200, json={
            "id": f"fake-{n}", "object": "chat.completion", "created": 1,
            "model": "synthetic-test-model",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [{"id": f"call-{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = AsyncOpenAI(api_key="synthetic-test-key", base_url="https://synthetic.example/v1", http_client=http)
    agent = Agent(model=OpenAIModel(client=provider, model_id="synthetic-test-model", stream=False), tools=build_tools(ledger, grouped=grouped, auto_verify=grouped == "auto"), system_prompt=SYSTEM_PROMPT, structured_output_model=AgentSelection, callback_handler=None, hooks=[Budget(ledger)], tool_executor=SequentialToolExecutor(), retry_strategy=None)
    try:
        result = agent("Find one small Python issue.")
        response = ledger.finalize(result.structured_output, FindRequest(description="small Python", count=1), "synthetic-test-model")
        assert len(response.results) == 1
        assert calls[:len(sequence)] == [name for name, args in sequence]
        assert len(calls) == len(sequence) + 1
    finally:
        asyncio.run(provider.close())
