"use client";

import { useState } from "react";

import type { LessonPlanTask } from "@/lib/chat";

export default function LessonChecklist({
  tasks,
  completedIds,
}: {
  tasks: LessonPlanTask[];
  completedIds: Set<string>;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const doneCount = tasks.filter((task) => completedIds.has(task.id)).length;
  const currentId = tasks.find((task) => !completedIds.has(task.id))?.id;

  return (
    <aside className="w-[168px] max-w-[calc(100vw-2rem)] bg-surface-muted p-3">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left sm:pointer-events-none"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
      >
        <span className="text-[11px] leading-4 text-muted">Lesson plan</span>
        <span className="text-[11px] text-muted">
          {doneCount}/{tasks.length}
        </span>
      </button>
      <ul className={`mt-2 space-y-1.5 ${collapsed ? "hidden sm:block" : "block"}`}>
        {tasks.map((task) => {
          const done = completedIds.has(task.id);
          const current = task.id === currentId;
          return (
            <li
              key={task.id}
              className={`text-xs leading-5 ${
                done ? "text-muted line-through" : current ? "text-foreground" : "text-muted"
              }`}
            >
              <span className={current ? "font-[550]" : undefined}>{task.label}</span>
              <span className="ml-1 text-[11px] text-muted">~{task.minutes} min</span>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
