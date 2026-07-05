"""
agent.py
========
Pydantic V2 schemas for the Agent conversation API.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.agent import AgentSessionStatus, MessageRole
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

class AgentChatRequest(BaseModel):
    """Body for POST /agent/chat and POST /agent/stream."""

    message: str = Field(min_length=1, max_length=4000)
    scenario_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Scenario being configured. Null for exploratory queries.",
    )
    session_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Existing session ID to continue. Null to start a new session.",
    )
    auto_fix: bool = Field(
        default=False,
        description=(
            "If True and solver returns INFEASIBLE, the agent automatically "
            "applies constraint relaxations and retriggers the solver "
            "(up to MAX_AUTO_FIX_RETRIES times) without prompting the user."
        ),
    )


class AgentChatResponse(BaseModel):
    """Returned by POST /agent/chat."""

    session_id: uuid.UUID
    message: str = Field(description="Agent's natural-language reply to the user.")
    action_taken: Optional[str] = Field(
        default=None,
        description="Short description of what the agent did, e.g. 'Added Tier 2 rule MAX_DAILY_HOURS'.",
    )
    rules_added: list[str] = Field(
        default_factory=list,
        description="List of rule IDs created during this turn.",
    )
    solver_triggered: bool = False
    solver_status: Optional[str] = Field(
        default=None,
        description="Last solver result if solver was triggered: OPTIMAL, INFEASIBLE, etc.",
    )
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------

class AgentSessionResponse(BaseModel):
    id: uuid.UUID
    scenario_id: Optional[uuid.UUID]
    user_id: uuid.UUID
    title: Optional[str]
    status: AgentSessionStatus
    token_total: int
    retry_count: int
    last_solver_status: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


AgentSessionListResponse = PaginatedResponse[AgentSessionResponse]


# ---------------------------------------------------------------------------
# Message schemas
# ---------------------------------------------------------------------------

class AgentMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    tool_call_id: Optional[str]
    tool_name: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    latency_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


AgentMessageListResponse = PaginatedResponse[AgentMessageResponse]


# ---------------------------------------------------------------------------
# Auth schemas (used by auth routes)
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """Returned by POST /auth/login and POST /auth/register."""

    access_token: str
    refresh_token: str | None = None  # delivered via httpOnly cookie, not body
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str | None = None  # cookie is the primary source
