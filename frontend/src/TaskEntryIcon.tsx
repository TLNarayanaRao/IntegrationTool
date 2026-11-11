import { AlertTriangle } from "lucide-react";
import type { taskEntryLabels } from "./taskEntry";
import subtaskIcon from "./assets/activity-icons/call-sub-task.svg";

export default function TaskEntryIcon({ mode }: { mode: keyof typeof taskEntryLabels }) {
  if (mode === "unconfigured") return <AlertTriangle aria-hidden="true" />;
  if (mode === "subtask") return (
    <svg className="task-entry-icon" aria-hidden="true" viewBox="0 0 32 18" width="28" height="16">
      <image href={subtaskIcon} width="32" height="18" />
    </svg>
  );

  return (
    <svg className="task-entry-icon" aria-hidden="true" viewBox="0 0 32 18"
      width="28" height="16" fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round">
      <rect x="6.5" y="2" width="4" height="4" rx=".75" />
      <rect x="1.5" y="12" width="4" height="4" rx=".75" />
      <rect x="11.5" y="12" width="4" height="4" rx=".75" />
      <path d="M8.5 6v3m-5 3V9h10v3" />
      <circle cx="25" cy="9" r="5.5" />
      <path d="m24 6.8 3.2 2.2-3.2 2.2Z" fill="currentColor" stroke="none" />
    </svg>
  );
}
