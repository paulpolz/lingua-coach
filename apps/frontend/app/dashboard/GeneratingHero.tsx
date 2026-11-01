"use client";

import { useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import DeskHero from "./DeskHero";

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** "Generating lesson N…" with an elapsed-time ticker and the timed-out note. */
export default function GeneratingHero({
  lessonNumber,
  startedAt,
  timedOut,
  onCheckAgain,
}: {
  lessonNumber: number;
  startedAt: number;
  timedOut: boolean;
  onCheckAgain: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <DeskHero
      title={`Generating lesson ${lessonNumber}…`}
      helper={formatElapsed(now - startedAt)}
      helperClassName="text-[13px] text-muted"
    >
      {timedOut ? (
        <div className="flex flex-col items-start gap-2">
          <p className="max-w-sm text-sm text-warning">
            This is taking longer than usual. It may still finish in the background.
          </p>
          <Button variant="ghost" onClick={onCheckAgain}>
            Check again
          </Button>
        </div>
      ) : null}
    </DeskHero>
  );
}
