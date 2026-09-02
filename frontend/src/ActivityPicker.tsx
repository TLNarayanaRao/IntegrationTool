import React, { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";

type Entry = { label: string; asset?: string; type?: string; operation?: string; children?: Entry[] };
const icon = (asset?: string) => asset ? <img src={`/activity-icons/${asset.includes(".") ? asset : `${asset}.png`}`} alt="" /> : null;
const searchableText = (entry: Entry & { path?: string }) =>
  [entry.label, entry.path, entry.type, entry.operation]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
function flatten(entries: Entry[], parents: string[] = []): Array<Entry & { path: string }> {
  return entries.flatMap((entry) => entry.children?.length ? flatten(entry.children, [...parents, entry.label]) : [{ ...entry, path: parents.join(" / ") }]);
}

export default function ActivityPicker({ menu, packs, addActivity, close }: any) {
  const groups: Entry[] = useMemo(() => packs.map((pack: any) => ({ label: pack.name, children: pack.items })), [packs]);
  const [query, setQuery] = useState(""), [trail, setTrail] = useState<Entry[]>(groups.length ? [groups[0]] : []);
  const current = trail[trail.length - 1], entries = current?.children || groups;
  const results = useMemo(() => {
    const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return terms.length ? flatten(groups).filter((entry) => terms.every((term) => searchableText(entry).includes(term))) : [];
  }, [groups, query]);
  const width = Math.min(720, window.innerWidth - 16), height = Math.min(500, window.innerHeight - 16);
  const left = Math.max(8, Math.min(menu.x, window.innerWidth - width - 8)), top = Math.max(8, Math.min(menu.y, window.innerHeight - height - 8));
  const add = (entry: Entry) => { addActivity(entry, { x: menu.cx, y: menu.cy, connectFrom: menu.connectFrom }); close(); };
  const openEntry = (entry: Entry) => entry.children?.length ? setTrail((items) => [...items, entry]) : add(entry);
  return <div className="activity-picker simple-picker" style={{ left, top, width, height }} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
    <header><Search/><input type="search" autoFocus autoComplete="off" spellCheck={false} aria-label="Search activities" placeholder="Search activities…" value={query} onInput={(event) => setQuery(event.currentTarget.value)} onKeyDown={(event) => event.stopPropagation()}/>{query && <button type="button" aria-label="Clear search" onClick={() => setQuery("")}><X/></button>}<button type="button" aria-label="Close activity picker" onClick={close}><X/></button></header>
    {query ? <div className="activity-search-results simple-search"><small>{results.length} MATCHES</small><div className="picker-card-grid">{results.map((entry, index) => <button key={`${entry.path}-${entry.label}-${index}`} onClick={() => add(entry)}>{icon(entry.asset)}<span><b>{entry.label}</b><small>{entry.path}</small></span></button>)}</div>{!results.length && <p>No activity matches “{query}”.</p>}</div> : <div className="picker-browser">
      <aside><b>ACTIVITY GROUPS</b>{groups.map((group) => <button key={group.label} className={trail[0]?.label === group.label ? "active" : ""} onClick={() => setTrail([group])}><span>{group.label}</span><small>{flatten(group.children || []).length}</small><ChevronRight/></button>)}</aside>
      <section><header>{trail.length > 1 && <button aria-label="Back one activity level" onClick={() => setTrail((items) => items.slice(0, -1))}><ChevronLeft/></button>}<span><b>{current?.label || "Activities"}</b>{trail.length > 1 && <small>{trail.slice(0, -1).map((entry) => entry.label).join(" / ")}</small>}</span></header><div className="picker-card-grid">{entries.map((entry, index) => <button key={`${entry.label}-${index}`} onClick={() => openEntry(entry)}>{icon(entry.asset)}<span><b>{entry.label}</b>{entry.children?.length ? <small>{flatten(entry.children).length} activities</small> : null}</span>{entry.children?.length ? <ChevronRight/> : null}</button>)}</div></section>
    </div>}
  </div>;
}
