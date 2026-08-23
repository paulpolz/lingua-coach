import enum


class LearningGoalStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class LearningPlanStatus(str, enum.Enum):
    accepted = "accepted"
    superseded = "superseded"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class LessonStatus(str, enum.Enum):
    generating = "generating"
    active = "active"
    accomplished = "accomplished"
    failed = "failed"


class PaceStatus(str, enum.Enum):
    on_pace = "on_pace"
    slipped = "slipped"


class ChatSessionType(str, enum.Enum):
    onboarding = "onboarding"
    lesson = "lesson"


class ChatMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class UserReportType(str, enum.Enum):
    progress = "progress"
    errors_log = "errors_log"
    roadmap = "roadmap"
    four_week_plan = "four_week_plan"
