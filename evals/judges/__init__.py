"""LLM-as-judge modules. Scores are informational until agreement is documented.

Replay never calls Gemini here. Load `fixtures/replay/<id>.judge.json` if present;
otherwise omit scores. A rubric change is a new version file — never compare
`lesson_turn_v1` to `lesson_turn_v2`.
"""

from evals.judges.agreement import cohen_kappa, summarize_agreement
from evals.judges.runner import (
    RUBRIC_GENERATION,
    RUBRICS,
    canned_judge_path,
    judge_with_optional_repeats,
    load_canned_judge,
    resolve_rubric,
)
from evals.judges.schema import JudgeParseError, parse_judge_verdict

__all__ = [
    "RUBRIC_GENERATION",
    "RUBRICS",
    "JudgeParseError",
    "canned_judge_path",
    "cohen_kappa",
    "judge_with_optional_repeats",
    "load_canned_judge",
    "parse_judge_verdict",
    "resolve_rubric",
    "summarize_agreement",
]
