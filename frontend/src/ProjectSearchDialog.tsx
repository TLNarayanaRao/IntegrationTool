import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import ModalLayer from "./ModalLayer";
import { packagePaths, type PackageCatalog } from "./ProjectPackages";
import {
  projectReferences, projectSearchIndex, projectSearchKinds, searchProject,
  type ReferenceTarget, type SearchLocation, type SearchProject,
} from "./projectSearch";
import "./project-search.css";

const RESULT_LIMIT = 100;

export default function ProjectSearch({ project, initialTarget, onOpen, onClose }: {
  project: SearchProject & { object_packages?: PackageCatalog };
  initialTarget?: ReferenceTarget;
  onOpen: (location: SearchLocation) => void;
  onClose: () => void;
}) {
  const [target, setTarget] = useState(initialTarget);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const rows = useMemo(() => projectSearchIndex(project, {
    tasks: packagePaths(project.object_packages?.tasks, project.tasks.filter(item => !item.library_origin)),
    resources: packagePaths(project.object_packages?.resources, project.resources.filter(item => !item.library_origin)),
    schemas: packagePaths(project.object_packages?.schemas, project.schemas.filter(item => !item.library_origin)),
  }), [project]);
  const references = useMemo(() => target ? projectReferences(project, target) : rows, [project, rows, target]);
  const matching = useMemo(() => searchProject(references, query, target ? "" : kind), [references, query, kind, target]);
  const current = target && rows.find(row => row.target?.kind === target.kind && row.target?.id === target.id);
  const switchTarget = (next?: ReferenceTarget) => {
    setTarget(next);
    setQuery("");
  };
  return <ModalLayer><section className="project-search" role="dialog" aria-modal="true" aria-labelledby="project-search-title"
    onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); }
    }}>
    <header>
      <div><h2 id="project-search-title">{target ? "Find References" : "Project Search"}</h2>{current && <span>{current.name} · {current.kind}</span>}</div>
      <button type="button" aria-label="Close project search" onClick={onClose}><X aria-hidden="true"/></button>
    </header>
    <div className="project-search-controls">
      {target && <button type="button" onClick={() => switchTarget()}>Back to search</button>}
      <label><Search aria-hidden="true"/><input autoFocus aria-label={target ? "Filter references" : "Search project"}
        placeholder={target ? "Filter references…" : "Search by name, folder, or activity type…"} value={query}
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter" && matching[0]) { event.preventDefault(); onOpen(matching[0].location); }
        }}/></label>
      {!target && <select aria-label="Object type" value={kind} onChange={event => setKind(event.target.value)}>
        <option value="">All object types</option>
        {projectSearchKinds.map(value => <option key={value}>{value}</option>)}
      </select>}
    </div>
    <div className="project-search-results">
      <p role="status">{matching.length > RESULT_LIMIT ? `Showing ${RESULT_LIMIT} of ${matching.length}` : matching.length} {target ? "references" : "results"}</p>
      {!matching.length && <p>{target ? "No matching configured references." : "No matching project objects."}</p>}
      {matching.length > 0 && <ul>{matching.slice(0, RESULT_LIMIT).map(row => <li key={row.key}>
        <button type="button" className="project-search-open" onClick={() => onOpen(row.location)}>
          <strong>{row.name}</strong><small>{row.kind} · {row.detail}</small>
        </button>
        {row.target && <button type="button" aria-label={`Find references to ${row.name}`}
          onClick={() => switchTarget(row.target)}>Find References</button>}
      </li>)}</ul>}
    </div>
    <footer>{target && <small>Shows configured references. Runtime-generated targets require runtime inspection.</small>}
      <button type="button" onClick={onClose}>Close</button></footer>
  </section></ModalLayer>;
}
