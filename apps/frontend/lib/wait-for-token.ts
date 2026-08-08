/**
 * Clerk can report `isSignedIn` before `getToken()` returns a JWT. Poll briefly
 * so API calls and post-auth redirects don't race the session handshake.
 */
export async function waitForToken(
  getToken: () => Promise<string | null>,
  options?: { maxAttempts?: number; intervalMs?: number }
): Promise<string> {
  const maxAttempts = options?.maxAttempts ?? 40;
  const intervalMs = options?.intervalMs ?? 100;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const token = await getToken();
    if (token) return token;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error("Session token not ready yet. Please try again.");
}
