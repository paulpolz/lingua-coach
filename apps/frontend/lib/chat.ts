/**
 * Chat + onboarding client. Types mirror the backend by hand; the roadmap and
 * metadata objects come from the model as-is, so fields may be missing.
 */

import { apiFetch, toApiError } from "@/lib/api";

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
export async function createChatSession(
  token: string | null,
  type: ChatSessionType,
  lessonId?: string
): Promise<ChatSession> {
  const response = await apiFetch("/api/v1/chat/sessions", token, {
    method: "POST",
    body: JSON.stringify(lessonId ? { type, lesson_id: lessonId } : { type }),
  });

  if (!response.ok) {
    throw await toApiError(response, "Failed to create chat session");
  }

  return response.json();
}

/** `GET /api/v1/chat/sessions/{id}/messages` — source of truth for the chat UI; always re-fetched on open. */
export async function getChatMessages(token: string | null, sessionId: string): Promise<ChatMessage[]> {
  const response = await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages`, token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load chat messages");
  }

  const body: GetChatMessagesResponse = await response.json();
  return body.messages;
}

// ---------------------------------------------------------------------------
// Chat message metadata
// ---------------------------------------------------------------------------

export interface TimeBudget {
  minutes_per_session: number;
  sessions_per_week: number;
  intensity: "light" | "moderate" | "intensive" | string;
  optional_partner_minutes?: number;
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
  grammar_mastery?: Record<string, number>;
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

export interface CourseRoadmapWeeklyActivity {
  id: string;
  label: string;
  minutes: number;
}

export interface CourseRoadmapWeeklyTemplate {
  minutes_per_session: number;
  activities: CourseRoadmapWeeklyActivity[];
  partner_session?: unknown;
  weekends?: string;
}

export interface CourseRoadmapThemeDay {
  block_day: number;
  grammar_focus?: string;
  vocab_theme?: string;
  input_type?: string;
  production_focus?: string;
  goal_specific_focus?: string;
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

export interface LessonPlanTask {
  id: string;
  label: string;
  minutes: number;
}

export interface LessonPlan {
  tasks: LessonPlanTask[];
}

export interface TaskUpdate {
  completed_task_ids: string[];
}

/** Chat turn metadata. Onboarding sessions also carry `course_roadmap_draft`. */
export interface ChatMessageMetadata {
  corrections?: Correction[] | null;
  tips?: string[] | null;
  plan_updates?: PlanUpdates | null;
  suggest_finish?: boolean | null;
  course_roadmap_draft?: CourseRoadmap | null;
  lesson_plan?: LessonPlan | null;
  task_update?: TaskUpdate | null;
}

/** Accumulate pinned-checklist tasks and completions from assistant message metadata. */
export function applyChecklistMetadata(
  metadata: ChatMessageMetadata | null | undefined,
  tasks: LessonPlanTask[],
  completedIds: Set<string>
): { tasks: LessonPlanTask[]; completedIds: Set<string> } {
  let nextTasks = tasks;
  const nextCompleted = new Set(completedIds);
  if (metadata?.lesson_plan?.tasks?.length) {
    nextTasks = metadata.lesson_plan.tasks;
    const ids = new Set(nextTasks.map((task) => task.id));
    for (const id of [...nextCompleted]) {
      if (!ids.has(id)) nextCompleted.delete(id);
    }
  }
  for (const id of metadata?.task_update?.completed_task_ids ?? []) {
    nextCompleted.add(id);
  }
  if (metadata?.suggest_finish) {
    for (const task of nextTasks) {
      nextCompleted.add(task.id);
    }
  }
  return { tasks: nextTasks, completedIds: nextCompleted };
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
  let response: Response;
  try {
    response = await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages`, token, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
  } catch (error) {
    // A dropped connection has no HTTP response. `toApiError` needs one, so this
    // stand-in carries the client message. It is not a backend status.
    const detail = error instanceof Error && error.message ? error.message : "Could not reach the server.";
    throw await toApiError(
      new Response(JSON.stringify({ detail, code: "NETWORK_ERROR" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
      "Could not reach the server."
    );
  }

  if (!response.ok) {
    throw await toApiError(response, "Message failed");
  }

  return response.json();
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
export async function acceptOnboarding(
  token: string | null,
  sessionId: string,
  courseRoadmap: CourseRoadmap
): Promise<AcceptOnboardingResponse> {
  const response = await apiFetch("/api/v1/onboarding/accept", token, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, course_roadmap: courseRoadmap }),
  });

  if (!response.ok) {
    throw await toApiError(response, "Failed to accept plan");
  }

  return response.json();
}
