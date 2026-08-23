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

  return (
    <aside className="w-56 max-w-[calc(100vw-2rem)] rounded-xl border border-zinc-200 bg-white/95 p-3 shadow-md backdrop-blur dark:border-zinc-700 dark:bg-zinc-900/95">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left sm:pointer-events-none"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
      >
        <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Lesson plan
        </span>
        <span className="text-[11px] text-zinc-400">
          {doneCount}/{tasks.length}
        </span>
      </button>
      <ul className={`mt-2 space-y-1.5 ${collapsed ? "hidden sm:block" : "block"}`}>
        {tasks.map((task) => {
          const done = completedIds.has(task.id);
          return (
            <li
              key={task.id}
              className={`text-xs leading-snug ${
                done ? "text-zinc-400 line-through" : "text-zinc-700 dark:text-zinc-200"
              }`}
            >
              <span className="font-medium">{task.label}</span>
              <span className="ml-1 text-[11px] text-zinc-400">~{task.minutes} min</span>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}