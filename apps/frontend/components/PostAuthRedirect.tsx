"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { waitForToken } from "@/lib/wait-for-token";

interface PostAuthRedirectProps {
  /** Where to send the user once Clerk reports a signed-in session. */
  href: string;
}

/**
 * Clerk's prebuilt SignIn can finish auth client-side before `getToken()` is
 * ready. Wait for a JWT, then navigate so protected pages can call the API.
 */
export default function PostAuthRedirect({ href }: PostAuthRedirectProps) {
  const { isSignedIn, isLoaded, getToken } = useAuth();
  const router = useRouter();
  const didRedirectRef = useRef(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || didRedirectRef.current) return;

    let cancelled = false;

    void (async () => {
      try {
        await waitForToken(getToken);
        if (cancelled || didRedirectRef.current) return;
        didRedirectRef.current = true;
        router.replace(href);
        router.refresh();
      } catch {
        // Clerk may still be finishing the handshake — stay on sign-in.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken, href, router]);

  return null;
}
