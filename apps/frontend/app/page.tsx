import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { syncUser } from "@/lib/api";

/**
 * Root route — Clerk sign-in is the MVP entry point (see
 * docs/tech_requirements/frontend.md "Auth UX").
 *
 * Signed out -> /sign-in. Signed in -> sync user with the backend, then
 * route-guard on `onboarding_complete` -> /onboarding or /dashboard.
 */
export default async function RootPage() {
  const { userId, getToken } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  const token = await getToken();

  // `redirect()` must be called outside the try/catch — it throws a special
  // NEXT_REDIRECT control-flow error that we don't want to swallow below.
  let onboardingComplete: boolean;
  try {
    onboardingComplete = (await syncUser(token)).onboarding_complete;
  } catch (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center">
        <p className="text-sm text-red-600">
          Could not reach the backend to sync your account. Is the API server
          running? ({error instanceof Error ? error.message : "unknown error"})
        </p>
      </div>
    );
  }

  redirect(onboardingComplete ? "/dashboard" : "/onboarding");
}
