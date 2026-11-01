"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";

import { getProgress, type Progress } from "@/lib/progress";

/**
 * `/progress` for the pace strip. Never blocks Start/Resume; a failure just
 * sets `error`. Re-fetches when `reloadKey` changes or on `reload()`.
 */
export function useProgress(reloadKey: number) {
  const { getToken } = useAuth();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [localReloads, setLocalReloads] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await getProgress(await getToken());
        if (cancelled) return;
        setProgress(result);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setProgress(null);
        setError(err instanceof Error ? err.message : "Failed to load progress.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, reloadKey, localReloads]);

  const reload = useCallback(() => setLocalReloads((n) => n + 1), []);

  return { progress, error, reload };
}
