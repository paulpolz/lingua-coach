import { auth } from "@clerk/nextjs/server";
import { UserButton } from "@clerk/nextjs";
import { redirect } from "next/navigation";

import { syncUser } from "@/lib/api";
import OnboardingChat from "./OnboardingChat";

export default async function OnboardingPage() {
  const { getToken } = await auth.protect();

  let onboardingComplete: boolean;
  try {
    onboardingComplete = (await syncUser(await getToken())).onboarding_complete;
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

  if (onboardingComplete) {
    redirect("/dashboard");
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3">
        <div>
          <h1 className="text-base font-semibold text-foreground">Let&apos;s get you set up</h1>
          <p className="text-xs text-muted">
            Chat with your coach to set your goal, level, and plan.
          </p>
        </div>
        <UserButton />
      </header>
      <OnboardingChat />
    </div>
  );
}
