"""
agent.py
========
ORM models for persisting LangGraph agent conversation context.

Tables
------
  agent_sessions   — one row per conversation thread (user × scenario).
  agent_messages   — individual messages within a thread (full history).

Design Notes
------------
* ``raw_payload`` (JSONB) stores the complete serialized LangChain
  ``BaseMessage`` dict.  This allows the agent graph to reconstruct the
  exact ``List[BaseMessage]`` for state restoration without lossy
  round-trips through the text ``content`` column.

* ``token_total`` on the session and ``prompt_tokens`` / ``completion_tokens``
  on each message support per-session cost accounting and throttling.

* ``scenario_id`` is nullable — some conversations are exploratory and not
  yet tied to a concrete scenario.

* A ``tool`` role row is always paired with a previous ``assistant`` row
  via the shared ``tool_call_id`` string (mirrors LangChain's convention).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MessageRole(str, enum.Enum):
    """Mirrors LangChain message types stored in the DB."""

    SYSTEM = "system"       # System prompt injected at graph start
    HUMAN = "human"         # Message from the end user
    AI = "ai"               # LLM response (may contain a tool_call_id)
    TOOL = "tool"           # Result returned by a tool node


class AgentSessionStatus(str, enum.Enum):
    ACTIVE = "active"       # Conversation in progress
    CLOSED = "closed"       # User or system explicitly ended it
    ERROR = "error"         # Terminated due to unrecoverable failure


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------


class AgentSession(Base):
    """
    A single conversation thread between a user and the scheduling agent.

    One session holds the full message list and optional link to the
    scenario being configured.  The LangGraph ``AgentState.messages``
    list is the in-memory projection of the rows in ``agent_messages``.
    """

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # The scenario being configured — nullable for exploratory chats.
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # The user who started this session.  Proper FK now that users table exists.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Auto-generated from the first human message (truncated to 120 chars).
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[AgentSessionStatus] = mapped_column(
        Enum(AgentSessionStatus, name="agent_session_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AgentSessionStatus.ACTIVE,
        server_default=AgentSessionStatus.ACTIVE.value,
    )

    # Running token counter — updated after every AI message for cost tracking.
    token_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Number of self-correction retries the orchestrator has attempted.
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Last solver status seen in this session ("OPTIMAL", "INFEASIBLE", ...).
    last_solver_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------
    messages: Mapped[list["AgentMessage"]] = relationship(
        "AgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentMessage.created_at",
    )

    scenario: Mapped["Scenario | None"] = relationship(  # type: ignore[name-defined]
        "Scenario", foreign_keys=[scenario_id]
    )
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id], back_populates="agent_sessions"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AgentSession id={self.id} user={self.user_id!r} "
            f"scenario={self.scenario_id} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# AgentMessage
# ---------------------------------------------------------------------------


class AgentMessage(Base):
    """
    One message in an agent conversation thread.

    The ``raw_payload`` JSONB column stores the complete LangChain
    ``BaseMessage.dict()`` output so the graph can reconstruct
    ``List[BaseMessage]`` with perfect fidelity — types, ids, and
    additional_kwargs are all preserved.
    """

    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message type — maps 1:1 to LangChain message classes.
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    # Human-readable text body.  For AI messages that are tool calls,
    # this may be empty; the tool call detail lives in raw_payload.
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # LangChain tool call identifier — links an AI tool-call message
    # to its corresponding TOOL response row.
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Name of the tool invoked / responding (non-null when role=TOOL or
    # when role=AI and the message contains a tool_use block).
    tool_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Full LangChain BaseMessage.dict() for lossless state restoration.
    # Shape varies by role — always include "type" and "content" at minimum.
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Token counts for this specific message pair (AI rows only; null otherwise).
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Wall-clock latency for the LLM call that produced this message (ms).
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------
    session: Mapped["AgentSession"] = relationship(
        "AgentSession", back_populates="messages"
    )

    def __repr__(self) -> str:  # pragma: no cover
        snippet = (self.content or "")[:40].replace("\n", " ")
        return (
            f"<AgentMessage id={self.id} role={self.role} "
            f"session={self.session_id} content={snippet!r}>"
        )
