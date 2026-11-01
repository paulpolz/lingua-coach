"""Stdlib checks for structured Gemini output. ChatGoogleGenerativeAI is mocked."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.chat import post_chat_message
from app.config import settings
from app.core.errors import APIError
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatMessageRole, ChatSessionType, JobStatus, LessonStatus, UserReportType
from app.models.job import Job
from app.models.lesson import Lesson
from app.models.llm_usage import LlmUsageEvent
from app.models.user import User
from app.models.user_report import UserReport
from app.schemas.chat import ChatMessageCreateRequest
from app.schemas.llm import (
    CourseRoadmap,
    CourseRoadmapMilestone,
    CourseRoadmapSummary,
    CurriculumSlot,
    GoalSpecificTask,
    InputTask,
    LessonCurriculum,
    LessonReply,
    OnboardingReply,
    ReportOp,
    ReportPatch,
)
from app.services.gemini import ChatTurn, generate_structured
from app.services.lesson_generation import run_lesson_generation_job
from app.services.llm_usage import metered_structured_call
from app.services.report_seed import blank_progress_markdown
from app.services.report_writer import _update

RAW_INPUT_TOKENS = 42


def _raw_message(*, input_tokens: int = RAW_INPUT_TOKENS) -> SimpleNamespace:
    return SimpleNamespace(usage_metadata={"input_tokens": input_tokens, "output_tokens": 7})


def _curriculum() -> LessonCurriculum:
    return LessonCurriculum(
        lesson_goal="Order a coffee.",
        grammar_focus="Polite requests.",
        vocab_theme="Cafe",
        milestone_index=0,
        slots=[CurriculumSlot(id="warmup", label="Warmup", exercise_set="reading")],
        input_task=InputTask(type="reading", topic="Menus", focus="vocab"),
        goal_specific_task=GoalSpecificTask(label="Write an order", format="writing"),
        exit_criteria=["Writes a short order"],
    )


def _roadmap() -> CourseRoadmap:
    return CourseRoadmap(
        version=1,
        summary=CourseRoadmapSummary(
            goal_outcome="Travel",
            goal_horizon="3 months",
            starting_level="A2",
            target_plan_days=30,
        ),
        milestones=[CourseRoadmapMilestone(index=0, title="Basics")],
    )


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class MemoryDB:
    """In-memory stand-in for the session methods these tests reach."""

    def __init__(self, gets: dict | None = None, executes: list[list] | None = None) -> None:
        self.gets = gets or {}
        self.executes = list(executes or [])
        self.added: list = []
        self.commits = 0

    async def get(self, model, ident):
        return self.gets.get((model, ident))

    async def execute(self, _stmt):
        rows = self.executes.pop(0) if self.executes else []
        return _Rows(rows)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _SessionCM:
    def __init__(self, db: MemoryDB) -> None:
        self._db = db

    async def __aenter__(self) -> MemoryDB:
        return self._db

    async def __aexit__(self, *_exc) -> bool:
        return False


class UsageRows:
    """Reserve and complete without Postgres. complete still writes the row object."""

    def __init__(self) -> None:
        self.events: dict[uuid.UUID, LlmUsageEvent] = {}

    @contextmanager
    def installed(self):
        rows = self

        async def reserve(db, user_id, call_type, *, estimated_input_tokens):
            event = LlmUsageEvent(
                id=uuid.uuid4(),
                user_id=user_id,
                call_type=call_type,
                input_tokens=estimated_input_tokens,
                status="reserved",
            )
            rows.events[event.id] = event
            return event

        class Side:
            async def get(self, model, ident):
                if model is not LlmUsageEvent:
                    return None
                return rows.events.get(ident)

            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def side_session(_db):
            yield Side()

        with (
            patch("app.services.llm_usage.reserve_gemini_call", reserve),
            patch("app.services.llm_usage._side_session", side_session),
        ):
            yield


@contextmanager
def patched_gemini(result: dict):
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    client = MagicMock()
    client.with_structured_output.return_value = structured
    cls = MagicMock(return_value=client)
    with (
        patch.object(settings, "gemini_api_key", "test-key"),
        patch("app.services.gemini.ChatGoogleGenerativeAI", cls),
    ):
        yield SimpleNamespace(cls=cls, client=client)


def _user() -> User:
    return User(id=uuid.uuid4(), clerk_user_id="clerk_test", onboarding_complete=False)


def _onboarding_session(user: User) -> tuple[ChatSession, MemoryDB]:
    session = ChatSession(id=uuid.uuid4(), user_id=user.id, type=ChatSessionType.onboarding)
    db = MemoryDB(gets={(ChatSession, session.id): session})
    return session, db


class StructuredOutputTests(IsolatedAsyncioTestCase):
    async def test_parsed_curriculum_reports_raw_input_tokens(self) -> None:
        curriculum = _curriculum()
        seen: list[int] = []

        async def on_usage(count: int) -> None:
            seen.append(count)

        with patched_gemini({"raw": _raw_message(), "parsed": curriculum, "parsing_error": None}) as gemini:
            parsed = await generate_structured(
                model_id="gemini-test",
                schema=LessonCurriculum,
                system_instruction="system",
                history=[ChatTurn(role="user", text="next lesson")],
                call_type="lesson_json",
                on_usage=on_usage,
            )

        self.assertIs(parsed, curriculum)
        self.assertEqual(seen, [RAW_INPUT_TOKENS])
        self.assertEqual(gemini.cls.call_args.kwargs["max_retries"], 0)
        schema_args, schema_kwargs = gemini.client.with_structured_output.call_args
        self.assertIs(schema_args[0], LessonCurriculum)
        self.assertEqual(schema_kwargs["method"], "json_schema")
        self.assertIs(schema_kwargs["include_raw"], True)

    async def test_parse_failure_reports_tokens_and_complete_stores_error_count(self) -> None:
        rows = UsageRows()
        with (
            patched_gemini(
                {"raw": _raw_message(), "parsed": None, "parsing_error": ValueError("schema")}
            ),
            rows.installed(),
        ):
            with self.assertRaises(Exception) as caught:
                await metered_structured_call(
                    MemoryDB(),
                    uuid.uuid4(),
                    "lesson_json",
                    model_id="gemini-test",
                    schema=LessonCurriculum,
                    system_instruction="system",
                    history=[ChatTurn(role="user", text="next lesson")],
                )

        self.assertEqual(caught.exception.code, "LLM_SCHEMA_ERROR")
        self.assertEqual(len(rows.events), 1)
        event = next(iter(rows.events.values()))
        self.assertEqual(event.status, "error")
        self.assertEqual(event.input_tokens, RAW_INPUT_TOKENS)
        self.assertNotEqual(event.input_tokens, 0)

    async def test_lesson_job_stores_model_dump(self) -> None:
        curriculum = _curriculum()
        user_id = uuid.uuid4()
        job = Job(id=uuid.uuid4(), user_id=user_id, type="lesson_generation", status=JobStatus.pending)
        lesson = Lesson(
            id=uuid.uuid4(),
            user_id=user_id,
            lesson_number=2,
            payload={},
            status=LessonStatus.generating,
        )
        db = MemoryDB(gets={(Job, job.id): job, (Lesson, lesson.id): lesson})
        rows = UsageRows()
        with (
            patched_gemini({"raw": _raw_message(), "parsed": curriculum, "parsing_error": None}),
            rows.installed(),
            patch("app.services.lesson_generation.AsyncSessionLocal", return_value=_SessionCM(db)),
        ):
            await run_lesson_generation_job(job_id=job.id, lesson_id=lesson.id, user_id=user_id)

        dumped = curriculum.model_dump()
        self.assertEqual(job.status, JobStatus.done)
        self.assertEqual(lesson.status, LessonStatus.active)
        self.assertEqual(lesson.payload["version"], 1)
        self.assertIsNone(lesson.payload["session_summary"])
        self.assertEqual(lesson.payload["curriculum"], dumped)
        self.assertIn("partner_session", dumped)
        self.assertIsNone(dumped["partner_session"])

    async def test_report_writer_applies_ops_from_model(self) -> None:
        user = _user()
        lesson = Lesson(
            id=uuid.uuid4(),
            user_id=user.id,
            lesson_number=1,
            payload={},
            status=LessonStatus.accomplished,
        )
        progress = UserReport(
            user_id=user.id,
            report_type=UserReportType.progress,
            body=blank_progress_markdown(),
        )
        db = MemoryDB(executes=[[progress], []])
        patch_model = ReportPatch(
            ops=[
                ReportOp(
                    report_type="progress",
                    op="append_entry",
                    section_id="update_log",
                    markdown="Noted the cafe order.",
                )
            ]
        )
        rows = UsageRows()
        with (
            patched_gemini({"raw": _raw_message(), "parsed": patch_model, "parsing_error": None}) as gemini,
            rows.installed(),
        ):
            await _update(
                db,
                user=user,
                lesson=lesson,
                session_summary={"worked_on": "orders"},
                profile=None,
                now=datetime(2026, 10, 28, tzinfo=timezone.utc),
            )

        schema_args, _schema_kwargs = gemini.client.with_structured_output.call_args
        self.assertIs(schema_args[0], ReportPatch)
        self.assertIn("Noted the cafe order.", progress.body)
        self.assertIn("<!-- section:update_log -->", progress.body)
        self.assertEqual(next(iter(rows.events.values())).status, "ok")

    async def test_onboarding_reply_keeps_content_and_roadmap_draft(self) -> None:
        roadmap = _roadmap()
        reply = OnboardingReply(content="  Here is your plan.  ", course_roadmap=roadmap)
        user = _user()
        session, db = _onboarding_session(user)
        rows = UsageRows()
        with (
            patched_gemini({"raw": _raw_message(), "parsed": reply, "parsing_error": None}) as gemini,
            rows.installed(),
            patch("app.api.v1.chat.check_and_record_user_limit", AsyncMock()),
        ):
            response = await post_chat_message(
                str(session.id),
                ChatMessageCreateRequest(content="I want to travel."),
                user,
                db,
            )

        schema_args, _schema_kwargs = gemini.client.with_structured_output.call_args
        self.assertIs(schema_args[0], OnboardingReply)
        self.assertEqual(response.content, "Here is your plan.")
        self.assertEqual(response.metadata["course_roadmap_draft"], roadmap.model_dump())
        assistants = [
            item
            for item in db.added
            if isinstance(item, ChatMessage) and item.role == ChatMessageRole.assistant
        ]
        self.assertEqual(len(assistants), 1)
        self.assertEqual(assistants[0].content, "Here is your plan.")
        self.assertEqual(assistants[0].metadata_json["course_roadmap_draft"], roadmap.model_dump())

    async def test_lesson_reply_completed_task_ids_become_task_update(self) -> None:
        reply = LessonReply(content="Nice work on the order.", completed_task_ids=["warmup", "exit"])
        user = _user()
        user.onboarding_complete = True
        lesson = Lesson(
            id=uuid.uuid4(),
            user_id=user.id,
            lesson_number=1,
            payload={"curriculum": {}},
            status=LessonStatus.active,
        )
        session = ChatSession(
            id=uuid.uuid4(),
            user_id=user.id,
            type=ChatSessionType.lesson,
            lesson_id=lesson.id,
        )
        db = MemoryDB(gets={(ChatSession, session.id): session, (Lesson, lesson.id): lesson})
        rows = UsageRows()
        with (
            patched_gemini({"raw": _raw_message(), "parsed": reply, "parsing_error": None}) as gemini,
            rows.installed(),
            patch("app.api.v1.chat.check_and_record_user_limit", AsyncMock()),
        ):
            response = await post_chat_message(
                str(session.id),
                ChatMessageCreateRequest(content="I would like a coffee."),
                user,
                db,
            )

        schema_args, _schema_kwargs = gemini.client.with_structured_output.call_args
        self.assertIs(schema_args[0], LessonReply)
        self.assertEqual(response.content, "Nice work on the order.")
        self.assertEqual(response.metadata["task_update"], {"completed_task_ids": ["warmup", "exit"]})

    async def test_schema_error_completes_usage_as_error_and_skips_assistant_row(self) -> None:
        user = _user()
        session, db = _onboarding_session(user)
        rows = UsageRows()
        with (
            patched_gemini(
                {"raw": _raw_message(), "parsed": None, "parsing_error": ValueError("schema")}
            ),
            rows.installed(),
            patch("app.api.v1.chat.check_and_record_user_limit", AsyncMock()),
        ):
            with self.assertRaises(APIError) as caught:
                await post_chat_message(
                    str(session.id),
                    ChatMessageCreateRequest(content="Hello"),
                    user,
                    db,
                )

        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(caught.exception.code, "LLM_SCHEMA_ERROR")
        event = next(iter(rows.events.values()))
        self.assertEqual(event.status, "error")
        self.assertEqual(event.input_tokens, RAW_INPUT_TOKENS)
        roles = [item.role for item in db.added if isinstance(item, ChatMessage)]
        self.assertEqual(roles, [ChatMessageRole.user])
