"""Import all ORM models so `Base.metadata` is fully populated for Alembic."""

from app.db.base import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.job import Job
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.quality_event import QualityEvent
from app.models.user import User
from app.models.user_report import UserReport

__all__ = [
    "Base",
    "User",
    "Profile",
    "LearningGoal",
    "LearningPlan",
    "Job",
    "Lesson",
    "ProgressEvent",
    "Mistake",
    "ChatSession",
    "ChatMessage",
    "UserReport",
    "QualityEvent",
]
