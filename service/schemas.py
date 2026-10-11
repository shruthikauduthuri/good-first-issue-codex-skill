from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class FindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, min_length=1, max_length=40)
    count: int = Field(default=5, ge=1, le=10)


class Pick(BaseModel):
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    issue_number: int = Field(gt=0)
    fit_reason: str = Field(min_length=1, max_length=500)
    difficulty: Literal["easy", "medium", "hard"]
    match_type: Literal["requested", "related"] = "requested"


class AgentSelection(BaseModel):
    # Agent only nominates identifiers. Server supplies all verified facts.
    results: list[Pick] = Field(default_factory=list, max_length=10)


class IssueResult(BaseModel):
    repo: str
    issue_url: str
    title: str
    difficulty: Literal["easy", "medium", "hard"]
    difficulty_reason: str
    availability: str
    fit_reason: str
    contributing_notes: str
    verified_at: str
    checks_passed: list[str]
    match_type: Literal["requested", "related"] = "requested"


class Rejection(BaseModel):
    repo: str
    issue_number: int
    reason: str


class FindResponse(BaseModel):
    query: str
    results: list[IssueResult]
    rejections: list[Rejection]
    trace: list[dict]
    provider: str = "Akamai hosted inference / Strands Agents"
    model: str
    metrics: dict = Field(default_factory=dict)
