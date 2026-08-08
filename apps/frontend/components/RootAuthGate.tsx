"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { waitForToken } from "@/lib/wait-for-token";

/**
 * Root `/` fallback when the server has no session yet (or user is signed out).
 * Wait for a JWT before sending signed-in users to onboarding.
 */
export default function RootAuthGate() {
  const { isSignedIn, isLoaded, getToken } = useAuth();
  const router = useRouter();
  const didRedirectRef = useRef(false);

  useEffect(() => {
    if (!isLoaded || didRedirectRef.current) return;

    let cancelled = false;

    void (async () => {
      if (isSignedIn) {
        try {
          await waitForToken(getToken);
          if (cancelled || didRedirectRef.current) return;
          didRedirectRef.current = true;
          router.replace("/onboarding");
          router.refresh();
        } catch {
          // Keep showing spinner — token should arrive shortly.
        }
        return;
      }

      didRedirectRef.current = true;
      router.replace("/sign-in");
    })();

    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken, router]);

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-foreground" />
    </div>
  );
}
