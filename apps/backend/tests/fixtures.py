"""Shared fixture payloads mirroring skills/course_composer.md and
skills/onboarding_interviewer.md's documented output shapes."""

from __future__ import annotations

VALID_COURSE_ROADMAP: dict = {
    "version": 1,
    "summary": {
        "goal_outcome": "Confident B2 English for daily work communication",
        "goal_horizon": "6 months",
        "starting_level": "B1",
        "target_language": "en",
        "native_language": "en",
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
            "success_criteria": "Write a 15-minute status update without a script",
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
                "production_focus": "Write a short self-intro paragraph",
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


VALID_LISTENING_RESOURCE: dict = {
    "id": "en-voa-lle-work-a2",
    "kind": "video",
    "title": "VOA Let's Learn English Level 2 — Budget Cuts",
    "url": "https://www.youtube.com/watch?v=fUmNAGJBLSA",
    "duration_sec": 480,
    "source": "VOA Learning English",
    "captions": "target",
    "synopsis": (
        "Studio staff overhear talk of budget cuts and worry about jobs. "
        "The meeting is actually about new assignments."
    ),
    "notice_points": [
        "Job titles and workplace nouns",
        "Going to for rumors and plans",
        "How the misunderstanding is resolved",
    ],
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
            "id": "writing",
            "label": "Written standup — last sprint blockers",
            "exercise_set": "Write a teammate standup note; target grammar: past simple vs present perfect",
        },
    ],
    "input_task": {
        "type": "listening",
        "topic": "A team retrospective meeting",
        "focus": "Listen for past simple vs present perfect usage",
        "resource": VALID_LISTENING_RESOURCE,
    },
    "goal_specific_task": {"label": "Write a retro summary email", "format": "email"},
    "exit_criteria": [
        "Produce 5 sentences with past simple + time marker",
        "Rewrite the standup note with <=2 repeats of the focus pattern",
    ],
    "partner_session": None,
}


VALID_LEARNER_PROFILE: dict = {
    "languages": {"native": "en", "target": "en"},
    "goal": {
        "outcome": "Write confidently in daily work meetings",
        "horizon": "6 months",
        "success_criteria": ["Can write a 15-minute status update without a script"],
    },
    "level": {
        "self_assessed": "B1",
        "strengths": ["reading"],
        "weaknesses": ["articles under time pressure"],
        "diagnostic_notes": "Solid grammar, hesitant in long written turns",
    },
    "time_budget": {
        "minutes_per_session": 60,
        "sessions_per_week": 5,
        "optional_partner_minutes": 30,
        "intensity": "sustainable",
    },
    "focus": {
        "skill_priorities": ["writing", "listening"],
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


# Non-English pair for persist / snapshot tests (tester-owned coverage).
VALID_LEARNER_PROFILE_ES: dict = {
    "languages": {"native": "en", "target": "es"},
    "goal": {
        "outcome": "Hablar con confianza en reuniones de trabajo diarias",
        "horizon": "6 months",
        "success_criteria": ["Puede dirigir una actualización de 15 minutos sin script"],
    },
    "level": {
        "self_assessed": "B1",
        "strengths": ["reading"],
        "weaknesses": ["articles under time pressure"],
        "diagnostic_notes": "Solid grammar, hesitant in long written turns",
    },
    "time_budget": {
        "minutes_per_session": 60,
        "sessions_per_week": 5,
        "optional_partner_minutes": 30,
        "intensity": "sustainable",
    },
    "focus": {
        "skill_priorities": ["writing", "listening"],
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
        "why_now": "New role requires client-facing Spanish",
        "past_blockers": ["lack of consistent practice"],
    },
}
