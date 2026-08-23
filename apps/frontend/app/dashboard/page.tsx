import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { syncUser } from "@/lib/api";
import AppHeader from "@/components/AppHeader";
import DashboardClient from "./DashboardClient";

export default async function DashboardPage() {
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

  if (!onboardingComplete) {
    redirect("/onboarding");
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader title="Dashboard" description="Your lesson loop lives here." />
      <DashboardClient />
    </div>
  );
}
