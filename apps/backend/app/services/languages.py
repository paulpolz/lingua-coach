"""Language-code normalization and the short policy block injected into Gemini calls.

Pedagogy stays in `skills/*.md`. This module is backend wiring: map common
language names to ISO 639-1 when we can, persist unknown strings instead of
rejecting them, and remind the model which language to speak on each surface.
"""

from __future__ import annotations

from typing import Literal

LanguageSurface = Literal["onboarding", "lesson", "lesson_generation", "report"]

# alias (already lowercased) → ISO 639-1. Unknown inputs are stored as the
# stripped lowercase string rather than rejected.
_LANGUAGE_ALIASES: dict[str, str] = {}


def _register(code: str, *aliases: str) -> None:
    _LANGUAGE_ALIASES[code] = code
    for alias in aliases:
        _LANGUAGE_ALIASES[alias.lower()] = code


_register(
    "en",
    "eng",
    "english",
    "inglés",
    "ingles",
    "anglais",
    "american english",
    "british english",
)
_register(
    "es",
    "spa",
    "spanish",
    "español",
    "espanol",
    "castellano",
    "castilian",
    "castellano español",
)
_register("ja", "jpn", "japanese", "japonés", "japones", "日本語", "nihongo")
_register("fr", "fra", "fre", "french", "français", "francais")
_register("de", "deu", "ger", "german", "deutsch", "alemán", "aleman")
_register("it", "ita", "italian", "italiano")
_register(
    "pt",
    "por",
    "portuguese",
    "português",
    "portugues",
    "brazilian portuguese",
    "português brasileiro",
)
_register("zh", "zho", "chi", "chinese", "mandarin", "中文", "汉语", "漢語", "putonghua")
_register("ko", "kor", "korean", "한국어", "조선어", "hangul")
_register("ru", "rus", "russian", "русский", "russkiy")
_register("ar", "ara", "arabic", "العربية")
_register("hi", "hin", "hindi", "हिन्दी", "हिंदी")
_register("nl", "nld", "dut", "dutch", "nederlands")
_register("pl", "pol", "polish", "polski")
_register("tr", "tur", "turkish", "türkçe", "turkce")
_register("sv", "swe", "swedish", "svenska")
_register("no", "nor", "norwegian", "norsk")
_register("da", "dan", "danish", "dansk")
_register("fi", "fin", "finnish", "suomi")
_register("cs", "ces", "cze", "czech", "čeština", "cestina")
_register("el", "ell", "gre", "greek", "ελληνικά")
_register("he", "heb", "hebrew", "עברית")
_register("th", "tha", "thai", "ไทย")
_register("vi", "vie", "vietnamese", "tiếng việt", "tieng viet")
_register("id", "ind", "indonesian", "bahasa indonesia")
_register("uk", "ukr", "ukrainian", "українська")
_register("ro", "ron", "rum", "romanian", "română", "romana")
_register("hu", "hun", "hungarian", "magyar")
_register("ca", "cat", "catalan", "català", "catala")
_register("sk", "slk", "slo", "slovak", "slovenčina")
_register("bg", "bul", "bulgarian", "български")
_register("hr", "hrv", "croatian", "hrvatski")
_register("sr", "srp", "serbian", "српски", "srpski")
_register("sl", "slv", "slovenian", "slovenski")
_register("lt", "lit", "lithuanian", "lietuvių")
_register("lv", "lav", "latvian", "latviešu")
_register("et", "est", "estonian", "eesti")
_register("fa", "fas", "per", "persian", "farsi", "فارسی")
_register("ur", "urd", "urdu", "اردو")
_register("bn", "ben", "bengali", "bangla", "বাংলা")
_register("ta", "tam", "tamil", "தமிழ்")
_register("te", "tel", "telugu", "తెలుగు")
_register("ml", "mal", "malayalam", "മലയാളം")
_register("ms", "msa", "may", "malay", "bahasa melayu")
_register("tl", "tgl", "fil", "filipino", "tagalog")
_register("sw", "swa", "swahili", "kiswahili")


def normalize_language(value: str) -> str:
    """Map a language name or code to ISO 639-1 when known.

    Unknown values are stored as stripped lowercase text — never rejected.
    """
    cleaned = " ".join(value.strip().strip(".,;:!? ").split()).lower()
    if not cleaned:
        return cleaned
    mapped = _LANGUAGE_ALIASES.get(cleaned)
    if mapped is not None:
        return mapped
    return cleaned


def language_policy_block(
    *,
    surface: LanguageSurface,
    native: str | None = None,
    target: str | None = None,
) -> str:
    """Short wiring block appended to Gemini `system_instruction` per surface."""
    native_n = (native or "").strip() or None
    target_n = (target or "").strip() or None

    if surface == "onboarding" and (native_n is None or target_n is None):
        return (
            "---\n"
            "Language policy (backend wiring; follow exactly):\n"
            "Start this interview in English. Collect the learner's native "
            "language, then the language they want to learn — one question per "
            "turn. After both are known, switch all further interviewer and "
            "course-composer text to the learning language. Accept answers in "
            "any language. Do not emit learner_profile without languages.native "
            "and languages.target."
        )

    effective_target = target_n or "en"
    native_display = native_n or "(not set)"
    pair = f"Native: {native_display} / Target: {effective_target}"

    if surface == "onboarding":
        return (
            "---\n"
            "Language policy (backend wiring; follow exactly):\n"
            f"{pair}\n"
            f"Speak only {effective_target} in learner-facing text. Native "
            f"({native_display}) is L1 interference context only — do not speak it. "
            "JSON keys stay English; JSON field values are in the learning language."
        )
    if surface == "lesson":
        return (
            "---\n"
            "Language policy (backend wiring; follow exactly):\n"
            f"{pair}\n"
            f"Conduct this lesson only in {effective_target}. Coach, exercises, "
            "corrections, and explanations must be in the learning language only. "
            f"Native ({native_display}) is L1 interference context only — do not speak it."
        )
    if surface == "lesson_generation":
        return (
            "---\n"
            "Language policy (backend wiring; follow exactly):\n"
            f"{pair}\n"
            f"Write the entire curriculum in {effective_target} (goals, slot prompts, "
            "grammar labels, exercise_set descriptions). JSON keys stay English. "
            f"Native ({native_display}) is L1 interference context only."
        )
    return (
        "---\n"
        "Language policy (backend wiring; follow exactly):\n"
        f"{pair}\n"
        f"Write learner-facing report patches in {effective_target}. Native "
        f"({native_display}) is L1 context only. Keep section ids and JSON keys "
        "in English."
    )
