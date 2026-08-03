"""Shared fixture payloads mirroring skills/course_composer.md and
skills/onboarding_interviewer.md's documented output shapes."""

from __future__ import annotations

VALID_COURSE_ROADMAP: dict = {
    "version": 1,
    "summary": {
        "goal_outcome": "Confident B2 English for daily work communication",
        "goal_horizon": "6 months",
        "starting_level": "B1",
        "target_plan_days": 90,
        "target_plan_days_range": [80, 100],
        "pace_description": "60 min/day, 5 days/week -> ~90 plan days on pace",
    },
    "milestones": [
        {
            "index": 0,
            "title": "Diagnostic & System Setup",
            "skill_developed": "Honest baseline, error logging, warm-up habits",
            "why_now": "Calibrate difficulty before building on assumptions",
            "connects_to": [],
            "success_criteria": "Progress dashboard started; 5 weekday sessions completed",
            "estimated_plan_days": 5,
        },
        {
            "index": 1,
            "title": "Foundation Fluency",
            "skill_developed": "Automatic self-description and daily-life talk",
            "why_now": "Every real conversation starts here",
            "connects_to": [0],
            "success_criteria": "90s unscripted self-intro with follow-ups",
            "estimated_plan_days": 20,
        },
    ],
    "weekly_template": {
        "minutes_per_session": 60,
        "activities": [
            {"id": "warmup", "label": "Warm-up & spaced repetition", "minutes": 5},
            {"id": "grammar", "label": "Grammar", "minutes": 8},
        ],
        "partner_session": {
            "minutes": 30,
            "phases": [
                {"id": "warmup", "minutes": 5},
                {"id": "main", "minutes": 15},
            ],
        },
        "weekends": "optional spaced-repetition review only",
    },
    "current_block": {
        "milestone_index": 0,
        "weeks": 1,
        "focus_summary": "Diagnostic + present/past foundations for self-description",
        "themes": [
            {
                "block_day": 1,
                "grammar_focus": "Present simple vs continuous",
                "vocab_theme": "Self-intro & role vocabulary",
                "input_type": "listening",
                "production_focus": "Tell me about yourself",
                "goal_specific_focus": "Opening technique for stated goal",
            }
        ],
    },
    "learning_principles": ["active_recall", "spaced_repetition"],
    "adaptation_rules": {
        "failed_weekly_test": "repeat_milestone_content",
        "recurring_error_pattern": "inject_retrieval_drill",
    },
    "current_milestone_index": 0,
}


VALID_LESSON_CURRICULUM: dict = {
    "lesson_goal": "Practice past tense in workplace retrospectives",
    "grammar_focus": "Past simple vs present perfect",
    "vocab_theme": "Workplace retrospectives",
    "milestone_index": 0,
    "slots": [
        {
            "id": "warmup",
            "label": "Active recall — past tense timelines",
            "exercise_set": "3 quick prompts recalling yesterday's work in past simple",
        },
        {
            "id": "production",
            "label": "90s monologue — last sprint blockers",
            "exercise_set": "Role: teammate standup; target grammar: past simple vs present perfect",
        },
    ],
    "input_task": {
        "type": "listening",
        "topic": "A team retrospective meeting",
        "focus": "Listen for past simple vs present perfect usage",
    },
    "goal_specific_task": {"label": "Write a retro summary email", "format": "email"},
    "exit_criteria": [
        "Produce 5 sentences with past simple + time marker",
        "90s monologue with <=2 repeats of focus pattern",
    ],
    "partner_session": None,
}


VALID_LEARNER_PROFILE: dict = {
    "goal": {
        "outcome": "Speak confidently in daily work meetings",
        "horizon": "6 months",
        "success_criteria": ["Can lead a 15-minute status update unscripted"],
    },
    "level": {
        "self_assessed": "B1",
        "strengths": ["reading"],
        "weaknesses": ["speaking under pressure"],
        "diagnostic_notes": "Solid grammar, hesitant speech",
    },
    "time_budget": {
        "minutes_per_session": 60,
        "sessions_per_week": 5,
        "optional_partner_minutes": 30,
        "intensity": "sustainable",
    },
    "focus": {
        "skill_priorities": ["speaking", "listening"],
        "topic_priorities": ["meetings", "email"],
        "vocab_priorities": ["workplace phrasal verbs"],
        "avoid": [],
    },
    "constraints": {
        "budget": "none",
        "practice_partner": {"available": True, "minutes": 30, "relationship": "spouse"},
        "learning_style": "correction-heavy",
    },
    "motivation": {
        "why_now": "New role requires client-facing English",
        "past_blockers": ["lack of consistent practice"],
    },
}
