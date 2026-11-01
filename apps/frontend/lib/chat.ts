/**
 * Chat + onboarding client. Types mirror the backend by hand; the roadmap and
 * metadata objects come from the model as-is, so fields may be missing.
 */

import { ApiError, apiJson } from "@/lib/api";

// ---------------------------------------------------------------------------
// Chat sessions + messages
// ---------------------------------------------------------------------------

export type ChatSessionType = "onboarding" | "lesson";

/** Assistant markdown links open outside the app. */
export const CHAT_EXTERNAL_LINK = {
  target: "_blank",
  rel: "noopener noreferrer",
} as const;

export interface ChatSession {
  id: string;
  type: ChatSessionType;
  lesson_id: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata?: ChatMessageMetadata | null;
}

interface GetChatMessagesResponse {
  messages: ChatMessage[];
}

/** `POST /api/v1/chat/sessions` — create (or, for lesson sessions, resume) a chat session. */
export function createChatSession(
  token: string | null,
  type: ChatSessionType,
  lessonId?: string
): Promise<ChatSession> {
  return apiJson(
    "/api/v1/chat/sessions",
    token,
    { method: "POST", body: JSON.stringify(lessonId ? { type, lesson_id: lessonId } : { type }) },
    "Failed to create chat session"
  );
}

/** `GET /api/v1/chat/sessions/{id}/messages` — source of truth for the chat UI; always re-fetched on open. */
export async function getChatMessages(token: string | null, sessionId: string): Promise<ChatMessage[]> {
  const body = await apiJson<GetChatMessagesResponse>(
    `/api/v1/chat/sessions/${sessionId}/messages`,
    token,
    {},
    "Failed to load chat messages"
  );
  return body.messages;
}

/** A message rendered in a chat transcript — either persisted or still waiting on the reply. */
export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata?: ChatMessageMetadata | null;
  /** Client-only: the coach reply is in flight. An empty bubble shows the typing dots. */
  isStreaming?: boolean;
  /** Hide this bubble (e.g. silent onboarding Start trigger). */
  hidden?: boolean;
}

// ---------------------------------------------------------------------------
// Chat message metadata
// ---------------------------------------------------------------------------

/** All fields are nullable on the backend; `minutes_per_session` is required before a roadmap. */
export interface TimeBudget {
  minutes_per_session: number | null;
  sessions_per_week: number | null;
  intensity: "light" | "moderate" | "intensive" | string | null;
}

export interface Correction {
  span: string;
  correction: string;
  type: string;
  note?: string;
}

export interface PlanUpdates {
  goal_summary?: string;
  level?: string;
  time_budget?: TimeBudget;
  topics?: string[];
  vocab_priorities?: string[];
  target_plan_days?: number;
  /** Backend values are untyped; the practiced loop writes `"solid"`. */
  grammar_mastery?: Record<string, string | number>;
}

// ---------------------------------------------------------------------------
// course_roadmap v1 (database.md "learning_plans.roadmap")
// ---------------------------------------------------------------------------

/** Native + learning language on a persisted learner profile / roadmap. */
export interface LearnerLanguages {
  native: string;
  target: string;
}

export interface CourseRoadmapSummary {
  goal_outcome: string;
  goal_horizon: string;
  starting_level: string;
  target_plan_days: number;
  target_plan_days_range?: [number, number];
  pace_description?: string;
  /** ISO 639-1 when resolvable (`es`, `ja`); otherwise a stored name. */
  target_language?: string;
  native_language?: string;
  languages?: LearnerLanguages;
}

export interface CourseRoadmapMilestone {
  index: number;
  title: string;
  skill_developed?: string;
  why_now?: string;
  connects_to?: number[];
  success_criteria?: string;
  estimated_plan_days?: number;
}

/** Each lesson is `minutes_per_session` of mixed chat practice; no per-activity split. */
export interface CourseRoadmapWeeklyTemplate {
  minutes_per_session: number;
  sessions_per_week?: number;
  weekends?: string;
}

export interface CourseRoadmapThemeDay {
  block_day: number;
  grammar_focus?: string;
  vocab_theme?: string;
  goal_context?: string;
}

export interface CourseRoadmapCurrentBlock {
  milestone_index: number;
  weeks?: number;
  focus_summary?: string;
  themes?: CourseRoadmapThemeDay[];
}

/** Full `course_roadmap` v1 object — draft (`done.metadata.course_roadmap_draft`) or accepted (`learning_plans.roadmap`). */
export interface CourseRoadmap {
  version: number;
  summary: CourseRoadmapSummary;
  milestones: CourseRoadmapMilestone[];
  weekly_template?: CourseRoadmapWeeklyTemplate;
  current_block?: CourseRoadmapCurrentBlock;
  learning_principles?: string[];
  adaptation_rules?: Record<string, string>;
  current_milestone_index?: number;
}

/** Lesson time measured by the backend: active chat minutes vs the profile's lesson length. */
export interface LessonTiming {
  active_minutes: number;
  target_minutes: number;
}

/** What the tutor saw practiced this turn (`LessonReply.practiced`). */
export interface PracticeResult {
  aspect: "grammar" | "vocabulary" | "review";
  item: string;
  result: "solid" | "shaky";
}

/**
 * Chat turn metadata. Onboarding sessions also carry `course_roadmap_draft`;
 * lesson sessions carry `timing`. Messages stored before `timing` existed lack it.
 */
export interface ChatMessageMetadata {
  corrections?: Correction[] | null;
  tips?: string[] | null;
  plan_updates?: PlanUpdates | null;
  suggest_finish?: boolean | null;
  course_roadmap_draft?: CourseRoadmap | null;
  practiced?: PracticeResult[] | null;
  timing?: LessonTiming | null;
}

/** Metadata of the newest assistant message that has `key` set, or `null`. */
export function latestAssistantMetadata<K extends keyof ChatMessageMetadata>(
  messages: readonly DisplayMessage[],
  key: K
): NonNullable<ChatMessageMetadata[K]> | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant" || message.isStreaming) continue;
    const value = message.metadata?.[key];
    if (value !== undefined && value !== null) return value as NonNullable<ChatMessageMetadata[K]>;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Send a chat turn
// ---------------------------------------------------------------------------

/** `POST /api/v1/chat/sessions/{id}/messages` — `ChatTurnResponse`, status 200. */
export interface ChatTurnResponse {
  message_id: string;
  content: string;
  metadata: ChatMessageMetadata;
}

/** `POST /api/v1/chat/sessions/{id}/messages` with `{content}`. Returns the JSON body. */
export async function sendChatMessage(
  token: string | null,
  sessionId: string,
  content: string
): Promise<ChatTurnResponse> {
  try {
    return await apiJson<ChatTurnResponse>(
      `/api/v1/chat/sessions/${sessionId}/messages`,
      token,
      { method: "POST", body: JSON.stringify({ content }) },
      "Message failed"
    );
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // A dropped connection has no HTTP response. The 503 carries the client
    // message; it is not a backend status.
    const detail = error instanceof Error && error.message ? error.message : "Could not reach the server.";
    throw new ApiError(503, detail, "NETWORK_ERROR");
  }
}

// ---------------------------------------------------------------------------
// Onboarding accept
// ---------------------------------------------------------------------------

export interface AcceptOnboardingResponse {
  onboarding_complete: boolean;
  plan_accepted_at: string;
}

/**
 * `POST /api/v1/onboarding/accept` — sends the session id plus the *cached*
 * `course_roadmap_draft` (verbatim, as last received on a chat turn)
 * back to the backend, which persists it as given.
 */
export function acceptOnboarding(
  token: string | null,
  sessionId: string,
  courseRoadmap: CourseRoadmap
): Promise<AcceptOnboardingResponse> {
  return apiJson(
    "/api/v1/onboarding/accept",
    token,
    { method: "POST", body: JSON.stringify({ session_id: sessionId, course_roadmap: courseRoadmap }) },
    "Failed to accept plan"
  );
}
