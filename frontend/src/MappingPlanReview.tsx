import {useState} from "react";

export default function MappingPlanReview({plan, query = "", manualBinding = false, onApply, onDiscard, onChoose}: any) {
  const [limit,setLimit] = useState(100);
  const rows = plan.recommendations.filter((row:any) => row.status !== "protected" &&
    (!query || `${row.target} ${row.selected || ""}`.toLowerCase().includes(query.toLowerCase())));
  const counts = plan.summary;
  return <section className="mapper-plan-review" aria-label="Review mapping suggestions">
    <header><b>Review mapping plan</b><button type="button" onClick={onDiscard}>Discard plan</button></header>
    <p>{counts.suggested} suggested · {counts.loops} repeating structures · {counts.reusedLoops || 0} loops reused · {counts.copies || 0} repeated value copies · {counts.protected} protected · {counts.ambiguous} ambiguous · {counts.unmatched} unmatched</p>
    {counts.requiredUnmapped > 0 && <p className="mapper-plan-warning">{counts.requiredUnmapped} required fields still need a mapping.</p>}
    <p className="mapper-plan-engine">{plan.engine}</p>
    {manualBinding && <p className="mapper-plan-warning">A manual XSLT stylesheet supplies runtime output. Choose Use visual mappings or Use generated XSLT before applying these suggestions.</p>}
    <button type="button" disabled={!counts.suggested || manualBinding} onClick={onApply}>Apply reviewed suggestions</button>
    <div className="mapper-plan-rows">{rows.slice(0,limit).map((row:any) => <article key={row.target}>
      <b>{row.target}{row.required ? " · required" : ""}</b><span>{row.status} · {row.confidence || 0}%</span>
      {row.selected && <code>{row.selected}</code>}
      {row.alternatives?.map((option:any) => <div key={option.source}>
        <small>{option.source} · {option.score}% · {option.reasons.join("; ")}</small>
        {!row.selected && <button type="button" onClick={() => onChoose(row.target,option.source)}>Choose this source</button>}
      </div>)}
      {!row.alternatives?.length && <small>No safe source found. Map manually, adjust vocabulary or select a narrower branch.</small>}
    </article>)}</div>
    {rows.length>limit && <button type="button" onClick={() => setLimit(value=>value+100)}>Show more suggestions ({rows.length-limit} remaining)</button>}
  </section>;
}
