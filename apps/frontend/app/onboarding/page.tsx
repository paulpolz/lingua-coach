import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { syncUser } from "@/lib/api";
import { createChatSession, getChatMessages } from "@/lib/chat";
import AccountMenu from "@/components/AccountMenu";
import OnboardingChat from "./OnboardingChat";

export default async function OnboardingPage() {
  const { getToken } = await auth.protect();
  const token = await getToken();

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

  if (onboardingComplete) {
    redirect("/dashboard");
  }

  // Create/resume the session on the server. The browser often cannot reach
  // the API yet on a full reload (Clerk still hydrating → "Failed to fetch").
  let sessionId: string;
  let initialMessages: Awaited<ReturnType<typeof getChatMessages>>;
  try {
    const session = await createChatSession(token, "onboarding");
    sessionId = session.id;
    initialMessages = await getChatMessages(token, session.id);
  } catch (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center">
        <p className="text-sm text-red-600">
          Could not load onboarding chat. Is the API server running? (
          {error instanceof Error ? error.message : "unknown error"})
        </p>
      </div>
    );
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
        <AccountMenu />
      </header>
      <OnboardingChat initialSessionId={sessionId} initialMessages={initialMessages} />
    </div>
  );
}
