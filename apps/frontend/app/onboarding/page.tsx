import { auth } from "@clerk/nextjs/server";
import { UserButton } from "@clerk/nextjs";

import OnboardingChat from "./OnboardingChat";

export default async function OnboardingPage() {
  await auth.protect();

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h1 className="text-base font-semibold">Let&apos;s get you set up</h1>
          <p className="text-xs text-zinc-500">
            Chat with your coach to set your goal, level, and plan.
          </p>
        </div>
        <UserButton />
      </header>
      <OnboardingChat />
    </div>
  );
}
