#!/usr/bin/env python3
"""Exercise actual Strands tool use on the configured workshop model."""
import os
from dotenv import load_dotenv
from pydantic import BaseModel
from strands import Agent, tool
from strands.models.openai import OpenAIModel


class SmokeResult(BaseModel):
    tool_answer: int


def main():
    load_dotenv()
    key = os.getenv("AKAMAI_API_KEY")
    if not key:
        raise SystemExit("Set AKAMAI_API_KEY in the local .env; do not paste it in chat.")
    calls = []

    @tool
    def add_numbers(left: int, right: int) -> int:
        """Add two numbers. Args: left and right are the numbers to add."""
        calls.append((left, right))
        return left + right

    model = OpenAIModel(client_args={"base_url": os.getenv("AKAMAI_BASE_URL", "https://ws.akamai-workshops.com/v1"), "api_key": key, "timeout": 30, "max_retries": 0}, model_id=os.getenv("AKAMAI_MODEL", "hackathon-chat"), stream=False, params={"max_tokens": 512})
    agent = Agent(model=model, tools=[add_numbers], callback_handler=None, structured_output_model=SmokeResult)
    result = agent("Use add_numbers to add 17 and 25. Return its answer in tool_answer.")
    if calls != [(17, 25)] or not result.structured_output or result.structured_output.tool_answer != 42:
        raise SystemExit("FAIL: inference answered but real tool use / structured output was not verified.")
    print("PASS: Strands called a Python tool through Akamai inference and returned validated structured output.")


if __name__ == "__main__":
    main()
