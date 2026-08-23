import { auth } from "@clerk/nextjs/server";
import AppHeader from "@/components/AppHeader";

import { getLesson, type Lesson } from "@/lib/lessons";
import LessonChat from "./LessonChat";

/**
 * Server component: protects the route and does the initial
 * `GET /lessons/{lessonId}` fetch (same auth/data-fetching plumbing as the
 * Phase 3 placeholder this replaces). The interactive chat body — session
 * create/resume, transcript load, SSE streaming — lives in the client
 * component `LessonChat`, mirroring the onboarding page/`OnboardingChat`
 * split from Phase 2.
 */
export default async function LessonPage({
  params,
}: {
  params: Promise<{ lessonId: string }>;
}) {
  await auth.protect();
  const { lessonId } = await params;
  const { getToken } = await auth();

  let lesson: Lesson | null = null;
  let errorMessage: string | null = null;
  try {
    const token = await getToken();
    lesson = await getLesson(token, lessonId);
  } catch (error) {
    errorMessage =
      error instanceof Error ? error.message : "Could not reach the server. Is the backend running?";
  }

  if (errorMessage || !lesson) {
    return (
      <div className="flex h-dvh flex-col overflow-hidden">
        <AppHeader title="Lesson" />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="max-w-md text-sm text-red-600 dark:text-red-400">
            Couldn&apos;t load this lesson. ({errorMessage ?? "Not found"})
          </p>
          <a
            href="/dashboard"
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Back to dashboard
          </a>
        </div>
      </div>
    );
  }

  if (lesson.status !== "active") {
    return (
      <div className="flex h-dvh flex-col overflow-hidden">
        <AppHeader title={`Lesson ${lesson.lesson_number}`} />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="max-w-md text-sm text-zinc-500">
            {lesson.status === "generating"
              ? "This lesson is still generating — head back to the dashboard to check progress."
              : lesson.status === "accomplished"
                ? "This lesson is already finished."
                : "This lesson isn't available for chat right now."}
          </p>
          <a
            href="/dashboard"
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Back to dashboard
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader
        title={`Lesson ${lesson.lesson_number}`}
        description="Chat with your tutor to practice this lesson."
      />
      <LessonChat lessonId={lessonId} lesson={lesson} />
    </div>
  );
}
