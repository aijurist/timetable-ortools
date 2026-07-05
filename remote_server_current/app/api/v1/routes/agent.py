"""
app/api/v1/routes/agent.py
===========================
NEXUS agent API — streaming chat and session management.

Endpoints
---------
POST /agent/stream           → SSE streaming (primary)
POST /agent/chat             → Non-streaming (compat fallback)
GET  /agent/sessions         → List sessions for current user
GET  /agent/sessions/{id}    → Session detail
DELETE /agent/sessions/{id}  → Close session
GET  /agent/sessions/{id}/messages → Full message history

SSE event format:

    data: {"type": "token",      "content": "..."}
    data: {"type": "tool_start", "tool": "analyze_conflict", "input": {...}}
    data: {"type": "tool_end",   "tool": "analyze_conflict", "result": {...}}
    data: {"type": "auto_fix",   "retry": 2, "action": "Applied MAX_DAILY_HOURS: 4→5"}
    data: {"type": "done",       "session_id": "...", "message": "..."}
    data: {"type": "error",      "message": "..."}
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, PaginationParams, get_current_user, get_db, get_pagination, require_hod
from app.db.session import AsyncSessionLocal
from app.models.agent import AgentMessage, AgentSession, AgentSessionStatus
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentMessageListResponse,
    AgentMessageResponse,
    AgentSessionListResponse,
    AgentSessionResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(data: dict) -> str:
    """Format a dict as a single SSE ``data:`` line."""
    return f"data: {json.dumps(data)}\n\n"


async def _run_graph_stream(
    body: AgentChatRequest,
    db: AsyncSession,
    current_user: CurrentUser,
    request: Request | None = None,
) -> AsyncIterator[str]:
    """
    Drive the LangGraph agent and yield SSE-formatted strings.

    Maps LangGraph ``astream_events`` (v2) to our SSE event types:
      on_chat_model_stream  → token
      on_tool_start         → tool_start
      on_tool_end           → tool_end
      auto_fix node end     → auto_fix
      graph end             → done

    Uses a dedicated DB session for the graph (decoupled from the HTTP request
    session) so ``astream_events`` event processing never contends with graph
    node DB operations.  Concurrent keepalive pings prevent proxy timeouts.
    """
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agent_service.checkpointer import get_checkpointer
    from agent_service.graph import build_graph
    from agent_service.session_store import (
        get_or_create_session,
        persist_message,
        update_session_metadata,
    )

    # ── Resolve / create session (uses request db) ──────────────────────────
    session = await get_or_create_session(
        db,
        user_id=current_user.user_uuid,
        scenario_id=body.scenario_id,
        session_id=body.session_id,
        first_message=body.message,
    )
    effective_scenario_id = body.scenario_id or session.scenario_id
    if body.scenario_id and session.scenario_id != body.scenario_id:
        session.scenario_id = body.scenario_id
    await db.commit()

    # ── Graph runs in its own DB session ────────────────────────────────────
    async with AsyncSessionLocal() as graph_db:
        checkpointer = await get_checkpointer()
        graph = build_graph(
            graph_db,
            checkpointer,
            actor_context={
                "user_id": current_user.user_id,
                "institution_id": current_user.institution_id,
                "user_role": current_user.role.value,
                "user_department": current_user.department,
                "department_id": current_user.department_id,
                "session_id": str(session.id),
            },
        )

        initial_input = {
            "messages": [HumanMessage(content=body.message)],
            "scenario_id": str(effective_scenario_id) if effective_scenario_id else "",
            "session_id": str(session.id),
            "auto_fix": body.auto_fix,
            "solver_status": None,
            "last_job_id": None,
            "retry_count": 0,
            "telemetry_report": None,
            "final_response": None,
            "institution_id": current_user.institution_id or "",
            "user_role": current_user.role.value,
            "user_department": current_user.department,
            "department_id": current_user.department_id,
            "user_id": current_user.user_id,
        }

        config = {
            "configurable": {
                "thread_id": str(session.id),
                "db": graph_db,
            }
        }

        # ── Persist the human message (uses request db) ────────────────────
        await persist_message(db, session.id, HumanMessage(content=body.message))
        await db.commit()

        # ── Concurrent queue: graph events + keepalive ─────────────────────
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=128)
        _SENTINEL = object()

        async def _feed() -> None:
            """Push graph events into the queue.  Stops on disconnect or error."""
            try:
                async for event in graph.astream_events(initial_input, config, version="v2"):
                    await queue.put(("event", event))
                    if request and await request.is_disconnected():
                        break
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                await queue.put(("error", exc))
            finally:
                await queue.put(("sentinel", _SENTINEL))

        async def _beat() -> None:
            """Push keepalive pings every 30 s until cancelled."""
            try:
                while True:
                    await asyncio.sleep(30)
                    await queue.put(("keepalive", None))
            except asyncio.CancelledError:
                pass

        feed_task = asyncio.create_task(_feed())
        beat_task = asyncio.create_task(_beat())

        final_content = ""
        last_state: dict = {}
        _tool_inputs: dict[str, dict] = {}

        try:
            while True:
                kind, payload = await queue.get()

                if kind == "sentinel":
                    break
                if kind == "error":
                    raise payload
                if kind == "keepalive":
                    yield ": keepalive\n\n"
                    continue

                # ── Process a single graph event ───────────────────────────
                event = payload
                ekind = event.get("event", "")
                data = event.get("data", {})

                if ekind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk:
                        content = chunk.content
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")
                                    if text:
                                        final_content += text
                                        yield _sse({"type": "token", "content": text})
                        elif isinstance(content, str) and content:
                            final_content += content
                            yield _sse({"type": "token", "content": content})

                elif ekind == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = data.get("input", {})
                    run_id = str(event.get("run_id", ""))
                    if run_id:
                        _tool_inputs[run_id] = tool_input
                    yield _sse({
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": tool_input,
                    })

                elif ekind == "on_tool_end":
                    tool_name = event.get("name", "")
                    tool_output = data.get("output")
                    run_id = str(event.get("run_id", ""))
                    result_val = (
                        tool_output.content
                        if hasattr(tool_output, "content")
                        else tool_output
                    )
                    yield _sse({
                        "type": "tool_end",
                        "tool": tool_name,
                        "result": result_val,
                    })

                    tool_call_id_str = (
                        tool_output.tool_call_id
                        if hasattr(tool_output, "tool_call_id") and tool_output.tool_call_id
                        else run_id
                    )
                    content_str = (
                        result_val
                        if isinstance(result_val, str)
                        else json.dumps(result_val)
                        if result_val is not None
                        else ""
                    )
                    tool_input_stored = _tool_inputs.pop(run_id, {})
                    tool_msg = ToolMessage(
                        content=content_str,
                        tool_call_id=tool_call_id_str,
                        name=tool_name,
                        additional_kwargs={"input": tool_input_stored} if tool_input_stored else {},
                    )
                    async with AsyncSessionLocal() as persist_db:
                        await persist_message(persist_db, session.id, tool_msg)
                        await persist_db.commit()

                elif ekind == "on_chain_end" and event.get("name") == "auto_fixer":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        retry = output.get("retry_count", 0)
                        msgs = output.get("messages", [])
                        action = ""
                        if msgs:
                            last_msg = msgs[-1]
                            action = (
                                last_msg.content
                                if hasattr(last_msg, "content")
                                else str(last_msg)
                            )
                        yield _sse({"type": "auto_fix", "retry": retry, "action": action})
                        last_state = output

                elif ekind == "on_chain_end" and event.get("name") == "LangGraph":
                    output = data.get("output")
                    if isinstance(output, dict):
                        last_state = output
                    elif hasattr(output, "values") and isinstance(output.values, dict):
                        last_state = output.values
                    else:
                        logging.getLogger("nexus.agent").warning(
                            "LangGraph on_chain_end output is neither dict nor StateSnapshot: %s",
                            type(output).__name__ if output is not None else "None",
                        )

        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(exc)})
            await db.rollback()
            return
        finally:
            feed_task.cancel()
            beat_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                pass
            try:
                await beat_task
            except asyncio.CancelledError:
                pass

    # ── Fallback: extract content from last_state messages ────────────────
    if not final_content:
        msgs = last_state.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = last.get("content", "") if isinstance(last, dict) else getattr(last, "content", "") or ""
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                ]
                final_content = "".join(text_parts)
            elif isinstance(content, str):
                final_content = content
            else:
                final_content = str(content) if content is not None else ""
        logging.getLogger("nexus.agent").warning(
            "Fallback content extraction triggered — final_content was empty. "
            "Extracted %d chars from last_state messages.",
            len(final_content),
        )

    # ── Persist AI response + update session (uses request db) ────────────
    final_msg = AIMessage(content=final_content)
    await persist_message(db, session.id, final_msg)

    solver_status = last_state.get("solver_status")
    retry_count = last_state.get("retry_count", 0)
    await update_session_metadata(
        db,
        session.id,
        solver_status=solver_status,
        retry_count=retry_count,
    )
    await db.commit()

    yield _sse({
        "type": "done",
        "session_id": str(session.id),
        "message": final_content,
        "solver_status": solver_status,
        "retry_count": retry_count,
    })


# ---------------------------------------------------------------------------
# CSV pre-processing helper
# ---------------------------------------------------------------------------


async def _augment_message_with_csv(
    message: str,
    file: Optional[UploadFile],
    db: AsyncSession,
    current_user: CurrentUser,
) -> str:
    """If a CSV/XLSX file is attached, parse it, run preview_import, and inject
    a <csv_preview> block into the message so the agent can render a preview
    table without any tool calls."""
    import logging
    _log = logging.getLogger("nexus.csv_preview")

    if not file or not file.filename:
        return message

    filename = file.filename

    from app.services.bulk.base import cleanup_temp, parse_file, save_upload_to_temp
    from app.services.bulk.teaching_assignment_import import preview_import
    from agent_service.tools.planning._utils import resolve_academic_term

    institution_id_str = current_user.institution_id
    dept_id_str = current_user.department_id
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)

    if not institution_id_str:
        _log.warning("csv_preview: no institution_id on current_user — skipping preview")
        return f"{message}\n\n<csv_upload filename=\"{filename}\" error=\"no institution context\"/>"

    try:
        inst_id = uuid.UUID(str(institution_id_str))
    except (ValueError, TypeError) as exc:
        _log.warning("csv_preview: bad institution_id %r: %s", institution_id_str, exc)
        return message

    dept_id = None
    try:
        if dept_id_str:
            dept_id = uuid.UUID(str(dept_id_str))
    except (ValueError, TypeError):
        pass

    rows: list = []
    try:
        tmp = await save_upload_to_temp(file)
        try:
            rows = parse_file(tmp)
        finally:
            cleanup_temp(tmp)
    except Exception as exc:
        _log.warning("csv_preview: file parse failed for %r: %s", filename, exc, exc_info=True)
        return f"{message}\n\n<csv_upload filename=\"{filename}\" error=\"{exc}\"/>"

    resolved_term = await resolve_academic_term(db, inst_id, None)
    term_id = resolved_term[0] if resolved_term else None

    if not term_id:
        _log.warning("csv_preview: no active term found for institution %s", inst_id)
        return (
            f"{message}\n\n<csv_upload filename=\"{filename}\" rows=\"{len(rows)}\""
            " error=\"No active academic term — ask the user to select one\"/>"
        )

    if not rows:
        return f"{message}\n\n<csv_upload filename=\"{filename}\" rows=\"0\" error=\"File appears to be empty\"/>"

    try:
        preview = await preview_import(
            db,
            rows=rows,
            institution_id=inst_id,
            academic_term_id=term_id,
            dept_id=dept_id,
            role=role,
            auto_assign=False,
        )
    except Exception as exc:
        _log.error("csv_preview: preview_import failed for %r: %s", filename, exc, exc_info=True)
        return (
            f"{message}\n\n<csv_upload filename=\"{filename}\" rows=\"{len(rows)}\""
            f" error=\"Preview processing failed: {exc}\"/>"
        )

    def _clean_preview_row(r) -> dict:
        d = r.data
        clean: dict = {
            "row_number": r.row_number,
            "status": r.status.value,
            "course_code": d.get("course_code", ""),
            "faculty_name": d.get("faculty_name", ""),
            "section_count": d.get("section_count", 1),
        }
        if d.get("study_year"):
            clean["study_year"] = d["study_year"]
        if d.get("study_semester"):
            clean["study_semester"] = d["study_semester"]
        if d.get("notes"):
            clean["notes"] = d["notes"]
        if d.get("requested_dept_id"):
            clean["requested_dept_id"] = d["requested_dept_id"]
        if r.errors:
            clean["errors"] = r.errors
        return clean

    csv_context = json.dumps({
        "filename": filename,
        "total": preview.total_rows,
        "to_create": [_clean_preview_row(r) for r in preview.to_create],
        "to_update": [_clean_preview_row(r) for r in preview.to_update],
        "errors": [_clean_preview_row(r) for r in preview.errors],
        "workload_deltas": preview.workload_deltas,
    })
    return f"{message}\n\n<csv_preview>\n{csv_context}\n</csv_preview>"


# ---------------------------------------------------------------------------
# Primary: SSE streaming endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/stream",
    summary="Stream agent response via SSE",
    description=(
        "Send a message to NEXUS and receive a streaming Server-Sent Events response. "
        "Accepts multipart/form-data when a CSV/XLSX file is attached, "
        "or application/json when no file is present. "
        "POST body required — proxy via /api/agent-stream/[sessionId] on the frontend."
    ),
    response_class=StreamingResponse,
)
async def agent_stream(
    message: str = Form(..., max_length=4000),
    scenario_id: Optional[str] = Form(default=None),
    session_id: Optional[str] = Form(default=None),
    auto_fix: bool = Form(default=False),
    file: Optional[UploadFile] = File(default=None),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_hod),
) -> StreamingResponse:
    augmented = await _augment_message_with_csv(message, file, db, current_user)
    body = AgentChatRequest(
        message=augmented,
        scenario_id=scenario_id,
        session_id=session_id,
        auto_fix=auto_fix,
    )

    async def _safe_stream() -> AsyncIterator[str]:
        """Wrap the generator so any pre-yield exception is surfaced as an SSE error
        instead of resetting the TCP connection (which causes a 502 at the proxy)."""
        try:
            async for chunk in _run_graph_stream(body, db, current_user, request):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"Agent stream error: {exc}"})

    return StreamingResponse(
        _safe_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Fallback: non-streaming endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a message to the scheduling agent (non-streaming)",
)
async def agent_chat(
    message: str = Form(..., max_length=4000),
    scenario_id: Optional[str] = Form(default=None),
    session_id: Optional[str] = Form(default=None),
    auto_fix: bool = Form(default=False),
    file: Optional[UploadFile] = File(default=None),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_hod),
) -> AgentChatResponse:
    """Collects the full SSE stream internally and returns a single JSON response."""
    augmented = await _augment_message_with_csv(message, file, db, current_user)
    body = AgentChatRequest(
        message=augmented,
        scenario_id=scenario_id,
        session_id=session_id,
        auto_fix=auto_fix,
    )

    final_data: dict = {}
    full_message = ""

    async for chunk in _run_graph_stream(body, db, current_user, request):
        if not chunk.startswith("data: "):
            continue
        try:
            event = json.loads(chunk[6:].strip())
        except json.JSONDecodeError:
            continue
        if event.get("type") == "token":
            full_message += event.get("content", "")
        elif event.get("type") == "done":
            final_data = event

    session_id_str = final_data.get("session_id")
    if not session_id_str:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent did not complete successfully",
        )

    return AgentChatResponse(
        session_id=uuid.UUID(session_id_str),
        message=full_message or final_data.get("message", ""),
        solver_triggered=final_data.get("solver_status") is not None,
        solver_status=final_data.get("solver_status"),
        retry_count=final_data.get("retry_count", 0),
    )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=AgentSessionListResponse,
    summary="List agent sessions for the current user",
)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    pagination: PaginationParams = Depends(get_pagination),
) -> AgentSessionListResponse:
    from sqlalchemy import func as sa_func  # noqa: PLC0415

    count_q = await db.execute(
        select(sa_func.count(AgentSession.id)).where(
            AgentSession.user_id == current_user.user_uuid,
            AgentSession.status != AgentSessionStatus.CLOSED,
        )
    )
    total = count_q.scalar_one()

    result = await db.execute(
        select(AgentSession)
        .where(
            AgentSession.user_id == current_user.user_uuid,
            AgentSession.status != AgentSessionStatus.CLOSED,
        )
        .order_by(AgentSession.updated_at.desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    )
    sessions = result.scalars().all()

    return AgentSessionListResponse(
        items=[AgentSessionResponse.model_validate(s) for s in sessions],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=AgentSessionResponse,
    summary="Get a single agent session",
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AgentSessionResponse:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.user_id == current_user.user_uuid,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return AgentSessionResponse.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Close an agent session",
)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.user_id == current_user.user_uuid,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await db.delete(session)
    await db.commit()


@router.get(
    "/sessions/{session_id}/messages",
    response_model=AgentMessageListResponse,
    summary="Get full message history for a session",
)
async def list_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    pagination: PaginationParams = Depends(get_pagination),
) -> AgentMessageListResponse:
    from sqlalchemy import func as sa_func  # noqa: PLC0415

    # Verify ownership
    sess_result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.user_id == current_user.user_uuid,
        )
    )
    if not sess_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    count_q = await db.execute(
        select(sa_func.count(AgentMessage.id)).where(
            AgentMessage.session_id == session_id
        )
    )
    total = count_q.scalar_one()

    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at)
        .offset(pagination.skip)
        .limit(pagination.limit)
    )
    messages = result.scalars().all()

    return AgentMessageListResponse(
        items=[AgentMessageResponse.model_validate(m) for m in messages],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )
