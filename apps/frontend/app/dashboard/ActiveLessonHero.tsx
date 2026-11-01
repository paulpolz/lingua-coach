import Button from "@/components/ui/Button";
import type { Lesson } from "@/lib/lessons";

/**
 * Resume card for an active lesson. The goal plus a short grammar/vocab
 * preview tell the learner what's waiting; the lesson chat itself shows
 * only the goal and the time card.
 */
export default function ActiveLessonHero({
  lesson,
  onResume,
  onStop,
  isStopping,
  stopError,
  onFinish,
  isFinishing,
  finishError,
}: {
  lesson: Lesson;
  onResume: () => void;
  onStop: () => void;
  isStopping: boolean;
  stopError: string | null;
  onFinish: () => void;
  isFinishing: boolean;
  finishError: string | null;
}) {
  const curriculum = lesson.payload?.curriculum;
  const targetMinutes = lesson.payload?.target_minutes;
  const details = [
    curriculum?.lesson_goal,
    curriculum?.grammar_focus ? `Grammar: ${curriculum.grammar_focus}` : null,
    curriculum?.vocab_theme ? `Vocab: ${curriculum.vocab_theme}` : null,
    targetMinutes ? `About ${targetMinutes} min` : null,
  ].filter((line): line is string => Boolean(line));

  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">
        Resume lesson {lesson.lesson_number}?
      </h1>
      {details.length > 0 ? (
        <div className="flex flex-col gap-1">
          {details.map((line) => (
            <p key={line} className="text-sm leading-[22px] text-muted">
              {line}
            </p>
          ))}
        </div>
      ) : null}

      {stopError ? <p className="text-sm text-danger">{stopError}</p> : null}
      {finishError ? <p className="text-sm text-danger">{finishError}</p> : null}

      <div className="flex flex-wrap gap-2">
        <Button onClick={onResume}>Resume</Button>
        <Button
          variant="ghost"
          onClick={onStop}
          disabled={isStopping}
          title="Leaves the session — the lesson stays active and you can resume anytime."
        >
          {isStopping ? "Stopping…" : "Stop session"}
        </Button>
        <Button
          variant="ghost"
          onClick={onFinish}
          disabled={isFinishing}
          title="Always available while the lesson is active — marks it accomplished and unlocks the next lesson."
        >
          {isFinishing ? "Finishing…" : "Finish lesson"}
        </Button>
      </div>
    </div>
  );
}
