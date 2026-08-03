import { auth } from "@clerk/nextjs/server";
import { UserButton } from "@clerk/nextjs";

import DashboardClient from "./DashboardClient";

export default async function DashboardPage() {
  await auth.protect();

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h1 className="text-base font-semibold">Dashboard</h1>
          <p className="text-xs text-zinc-500">Your lesson loop lives here.</p>
        </div>
        <UserButton />
      </header>
      <DashboardClient />
    </div>
  );
}
