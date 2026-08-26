import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { syncUser } from "@/lib/api";
import { createChatSession, getChatMessages } from "@/lib/chat";
import AppHeader from "@/components/AppHeader";
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
        <p className="text-sm text-danger">
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
        <p className="text-sm text-danger">
          Could not load onboarding chat. Is the API server running? (
          {error instanceof Error ? error.message : "unknown error"})
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader
        title="Let's get you set up"
        description="Goal, level, and a plan you can change."
      />
      <OnboardingChat initialSessionId={sessionId} initialMessages={initialMessages} />
    </div>
  );
}
