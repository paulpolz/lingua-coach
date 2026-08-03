import { clerkMiddleware } from "@clerk/nextjs/server";

// Next.js 16 renamed `middleware.ts` to `proxy.ts` (same runtime behavior).
// We keep this bare — Clerk now recommends protecting resources individually
// (via `auth.protect()` in each page/layout) rather than path-matching here.
// See app/page.tsx, app/onboarding/page.tsx, app/dashboard/page.tsx.
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes.
    "/(api|trpc)(.*)",
  ],
};
