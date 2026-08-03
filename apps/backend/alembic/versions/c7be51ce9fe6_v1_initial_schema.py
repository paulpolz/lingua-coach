"""v1 initial schema

Creates all 10 MVP entities per docs/tech_requirements/database.md:
users, profiles, learning_goals, learning_plans, jobs, lessons,
progress_events, mistakes, chat_sessions, chat_messages.

Revision ID: c7be51ce9fe6
Revises:
Create Date: 2026-08-01 14:05:44.991594

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7be51ce9fe6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # --- users --------------------------------------------------------
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("onboarding_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("plan_accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"], unique=True)

    # --- learning_goals -------------------------------------------------
    op.create_table(
        "learning_goals",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_statement", sa.Text(), nullable=True),
        sa.Column("horizon", sa.Text(), nullable=True),
        sa.Column("success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("draft", "active", "archived", name="learning_goal_status"),
            server_default="draft",
            nullable=False,
        ),
        *_timestamps(),
    )
    op.create_index("ix_learning_goals_user_id", "learning_goals", ["user_id"])

    # --- learning_plans -------------------------------------------------
    op.create_table(
        "learning_plans",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "learning_goal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("accepted", "superseded", name="learning_plan_status"),
            server_default="accepted",
            nullable=False,
        ),
        sa.Column("roadmap", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_milestone_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_learning_plans_user_id", "learning_plans", ["user_id"])

    # --- profiles ---------------------------------------------------------
    op.create_table(
        "profiles",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_outcome", sa.Text(), nullable=True),
        sa.Column("goal_horizon", sa.Text(), nullable=True),
        sa.Column("goal_success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("english_level", sa.Text(), nullable=True),
        sa.Column("level_strengths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("level_weaknesses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("diagnostic_notes", sa.Text(), nullable=True),
        sa.Column("time_budget", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("focus", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("motivation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("interview_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("grammar_mastery", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("vocabulary_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("target_plan_days", sa.Integer(), nullable=True),
        sa.Column(
            "active_learning_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("projected_completion_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("plan_slip_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pace_window_hours", sa.Integer(), server_default="24", nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)

    # --- lessons ----------------------------------------------------------
    op.create_table(
        "lessons",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "learning_goal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "learning_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lesson_number", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("generating", "active", "accomplished", "failed", name="lesson_status"),
            server_default="generating",
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accomplished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "pace_status",
            postgresql.ENUM("on_pace", "slipped", name="pace_status"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_unique_constraint("uq_lessons_user_id_lesson_number", "lessons", ["user_id", "lesson_number"])
    op.create_index(
        "ix_lessons_user_id_active",
        "lessons",
        ["user_id"],
        postgresql_where=sa.text("status IN ('generating', 'active')"),
    )

    # --- jobs ---------------------------------------------------------------
    op.create_table(
        "jobs",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "running", "done", "failed", name="job_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.String(length=255), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_jobs_user_id_created_at", "jobs", ["user_id", "created_at"])

    # --- chat_sessions ---------------------------------------------------
    op.create_table(
        "chat_sessions",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "type",
            postgresql.ENUM("onboarding", "lesson", name="chat_session_type"),
            nullable=False,
        ),
        *_timestamps(),
    )

    # --- chat_messages -----------------------------------------------------
    op.create_table(
        "chat_messages",
        _uuid_pk(),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM("user", "assistant", name="chat_message_role"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_chat_messages_session_id_created_at", "chat_messages", ["session_id", "created_at"])

    # --- progress_events -----------------------------------------------
    op.create_table(
        "progress_events",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_progress_events_user_id_created_at", "progress_events", ["user_id", "created_at"])

    # --- mistakes -----------------------------------------------------------
    op.create_table(
        "mistakes",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pattern_type", sa.String(length=255), nullable=False),
        sa.Column("example_text", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_review_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_mistakes_user_id_created_at", "mistakes", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("mistakes")
    op.drop_table("progress_events")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("jobs")
    op.drop_table("lessons")
    op.drop_table("profiles")
    op.drop_table("learning_plans")
    op.drop_table("learning_goals")
    op.drop_table("users")

    for enum_name in (
        "pace_status",
        "lesson_status",
        "job_status",
        "chat_session_type",
        "chat_message_role",
        "learning_plan_status",
        "learning_goal_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
