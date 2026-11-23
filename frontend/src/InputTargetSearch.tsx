import { useEffect, useLayoutEffect, useMemo, useState, type ReactNode, type RefObject } from "react";
import { filterInputTargets, locateInputTarget, type InputTarget } from "./inputTargetNavigation";
import type { MappingTreeRow } from "./mappingTree";

export type InputTargetRequest = InputTarget & { handled: () => void };

export function useInputTargetSearch(
  rows: MappingTreeRow[],
  root: RefObject<HTMLDivElement | null>,
  request: InputTargetRequest | undefined,
  expand: (keys: string[]) => void,
  select: (row: MappingTreeRow) => void,
) {
  const [query, setQuery] = useState("");
  const [jump, setJump] = useState<{ key: string }>();
  const filtered = useMemo(() => filterInputTargets(rows, query), [rows, query]);

  useEffect(() => {
    if (!request) return;
    const frame = requestAnimationFrame(() => {
      const row = locateInputTarget(rows, request);
      if (row) {
        setQuery("");
        expand(row.ancestors);
        select(row);
        setJump({ key: row.key });
      }
      request.handled();
    });
    return () => cancelAnimationFrame(frame);
  }, [request, rows, expand, select]);

  useLayoutEffect(() => {
    if (!jump) return;
    const row = root.current?.querySelector<HTMLElement>(`[data-input-row="${CSS.escape(jump.key)}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "nearest", inline: "nearest" });
    const editor = row.querySelector<HTMLElement>("input:not([disabled]):not([readonly]), textarea:not([disabled]):not([readonly])");
    (editor ?? row).focus({ preventScroll: true });
  }, [jump, root]);

  return {
    ...filtered, active: !!query.trim(), query, jumpKey: jump?.key,
    search: (value: string) => { setQuery(value); setJump(undefined); },
  };
}

export default function InputTargetSearch({ query, search, count, collapseAll, expandAll, children }: {
  query: string;
  search: (value: string) => void;
  count: number;
  collapseAll: () => void;
  expandAll: () => void;
  children?: ReactNode;
}) {
  return <div className="mapper-target-search">
    <input type="search" aria-label="Find target field" placeholder="Find target field…" value={query}
      onChange={event => search(event.target.value)} onKeyDown={event => {
        if (event.key === "Escape" && query) { event.stopPropagation(); search(""); }
      }}/>
    <button type="button" onClick={collapseAll}>Collapse all</button>
    <button type="button" onClick={expandAll}>Expand all</button>
    {children}
    {query.trim() && <span role="status" className="input-target-count">{count ? `${count} matching ${count === 1 ? "field" : "fields"}` : "No matching fields"}</span>}
  </div>;
}
