import { useMemo, useState } from "react";
import { ChevronRight, ShieldCheck, X } from "lucide-react";
import ModalLayer from "./ModalLayer";
import type { InputTarget } from "./inputTargetNavigation";
import "./validation-review.css";

export type ValidationIssue = {
  id: string;
  severity: "error" | "warning" | "mapping";
  category: string;
  message: string;
  remedy: string;
  taskId?: string;
  activityId?: string;
  target?: { kind: "transition" | "resource" | "schema" | "properties"; id: string }
    | { kind: "packaging" | "application" }
    | { kind: "input"; field?: InputTarget };
};

const filters = [
  { value: "all", label: "All findings" },
  { value: "error", label: "Errors" },
  { value: "warning", label: "Warnings" },
  { value: "mapping", label: "Mappings" },
] as const;
const PAGE_SIZE = 50;

export default function ValidationReview({ title, issues, open, onClose, onRefresh, onOpen }: {
  title: string;
  issues: { issue: ValidationIssue; location?: string }[];
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onOpen: (issue: ValidationIssue) => void;
}) {
  const [filter, setFilter] = useState<typeof filters[number]["value"]>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const counts = useMemo(() => {
    const totals = { all: issues.length, error: 0, warning: 0, mapping: 0 };
    for (const { issue } of issues) totals[issue.severity]++;
    return totals;
  }, [issues]);
  if (!open) return null;
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = issues.filter(({ issue, location }) => {
    if (filter !== "all" && issue.severity !== filter) return false;
    const text = `${location ?? ""} ${issue.category} ${issue.message} ${issue.remedy}`.toLowerCase();
    return terms.every(term => text.includes(term));
  });
  const pageCount = Math.ceil(matches.length / PAGE_SIZE);
  const currentPage = Math.max(0, Math.min(page, pageCount - 1));

  return <ModalLayer><section className="validation-review" role="dialog" aria-modal="true" aria-labelledby="validation-review-title"
    onKeyDown={event => {
      event.stopPropagation();
      if (event.key === "Escape") { onClose(); return; }
      if (event.key !== "Tab") return;
      const controls = event.currentTarget.querySelectorAll<HTMLElement>("button:enabled, input");
      const next = event.shiftKey ? controls[controls.length - 1] : controls[0];
      const boundary = event.shiftKey ? controls[0] : controls[controls.length - 1];
      if (document.activeElement === boundary) { event.preventDefault(); next?.focus(); }
    }}>
    <header>
      <ShieldCheck aria-hidden="true"/>
      <h2 id="validation-review-title">{title}</h2>
      <button type="button" aria-label="Close validation" onClick={onClose}><X aria-hidden="true"/></button>
    </header>
    <div className="validation-review-controls">
      <input autoFocus type="search" aria-label="Search findings" placeholder="Search by location or issue…" value={query}
        onChange={event => { setQuery(event.target.value); setPage(0); }}/>
      <div className="validation-review-filters" role="group" aria-label="Finding severity">
        {filters.map(({ value, label }) => <button key={value} type="button" aria-pressed={filter === value}
          onClick={() => { setFilter(value); setPage(0); }}>{label} · {counts[value]}</button>)}
      </div>
    </div>
    <div className="validation-review-results" key={currentPage}>
      <p role="status">{issues.length === 0 ? "Validation successful. No findings." : `${matches.length} of ${issues.length} findings`}</p>
      {issues.length > 0 && matches.length === 0 && <p>No findings match your search and severity filter.</p>}
      <ul>{matches.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(({ issue, location }) => <li key={issue.id} data-severity={issue.severity}>
        <div>
          <strong>{issue.category}</strong><span className="validation-review-severity">{issue.severity}</span>
          {location && <small>{location}</small>}
          <p>{issue.message}</p>
          <small>{issue.remedy}</small>
        </div>
        {location && <button type="button" aria-label={`Open ${location} · ${issue.message}`} onClick={() => onOpen(issue)}>
          Open <ChevronRight aria-hidden="true"/>
        </button>}
      </li>)}</ul>
    </div>
    <footer>
      {pageCount > 1 && <div className="validation-review-pages" role="group" aria-label="Finding pages">
        <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
        <span role="status">{currentPage + 1} / {pageCount}</span>
        <button type="button" disabled={currentPage === pageCount - 1} onClick={() => setPage(currentPage + 1)}>Next</button>
      </div>}
      <button type="button" onClick={onRefresh}>Revalidate</button>
      <button type="button" onClick={onClose}>Close</button>
    </footer>
  </section></ModalLayer>;
}
