import React, { useEffect, useState } from "react";

export default function DebugPayloadEditor({ title, value }: { title: string; value: any }) {
  const original = value === undefined ? "" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const [draft, setDraft] = useState(original);
  const [message, setMessage] = useState("");
  useEffect(() => { setDraft(original); setMessage(""); }, [original]);
  return <article><header>{title} <button type="button" onClick={async () => {
    try { await navigator.clipboard.writeText(draft); setMessage("Copied"); }
    catch { setMessage("Select the text and press Ctrl+C to copy."); }
  }}>Copy</button><button type="button" onClick={() => { setDraft(original); setMessage(""); }}>Reset</button></header>
    <textarea aria-label={`${title} payload scratch editor`} spellCheck={false} value={draft}
      placeholder={value === undefined ? "Not captured yet" : ""}
      onChange={event => setDraft(event.target.value)} style={{ width: "100%", minHeight: 240, resize: "vertical", fontFamily: "monospace", boxSizing: "border-box" }}/>
    <small role="status">{message || "Copy/paste scratchpad. Edits do not change the running job; use the test bench to inject data."}</small>
  </article>;
}
