import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { mapperFunctionCatalog } from "./mapper-functions";
import { completeMapping } from "./mappingCompletion";

export default function MappingExpressionInput({ value, onChange, paths = [], label = "Mapping expression" }: any) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    const close = (event: Event) => { if (!(event.target instanceof Element && event.target.closest('[role="listbox"]'))) setOpen(false); };
    window.addEventListener("scroll", close, true); window.addEventListener("resize", close);
    return () => { window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, []);
  const [open, setOpen] = useState(false), [index, setIndex] = useState(0);
  const text = value == null ? "" : String(value);
  const [caret, setCaret] = useState<number | null>(null);
  const prefix = text.slice(0, caret ?? text.length), suffix = text.slice(caret ?? text.length);
  const token = prefix.match(/(?:\$\{?|)([\w.@\[\]-]+)$/)?.[1] || "";
  const options = token ? [...new Set<string>(paths)].filter(path => path.toLowerCase().startsWith(token.toLowerCase()))
    .map(path => ({ label: path, insert: `\${${path}}` }))
    .concat(mapperFunctionCatalog.filter(fn => fn.name.toLowerCase().startsWith(token.toLowerCase())).map(fn => ({ label: fn.signature, insert: fn.template }))).slice(0, 30) : [];
  const choose = (option: { insert: string }) => {
    onChange(completeMapping(prefix, suffix, option.insert));
    setCaret(null);
    setOpen(false); setIndex(0);
  };
  return <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
    <input ref={input} aria-label={label} role="combobox" aria-autocomplete="list" aria-expanded={open && !!options.length}
      aria-activedescendant={open && options.length ? `${id}-${Math.min(index, options.length - 1)}` : undefined}
      aria-controls={id} value={text} placeholder="Type a data path or function…" style={{ width: "100%", boxSizing: "border-box" }}
      onFocus={() => { setRect(input.current?.getBoundingClientRect() || null); setOpen(true); }} onBlur={() => setOpen(false)}
      onSelect={event => setCaret(event.currentTarget.selectionStart)}
      onChange={event => { setRect(input.current?.getBoundingClientRect() || null); setCaret(event.target.selectionStart); onChange(event.target.value); setIndex(0); setOpen(true); }}
      onKeyDown={event => {
        if (event.key === "Escape") { setOpen(false); event.stopPropagation(); }
        if (!open || !options.length) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); event.stopPropagation(); setIndex((index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length); }
        if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); event.stopPropagation(); choose(options[Math.min(index, options.length - 1)]); }
      }}/>
    {open && !!options.length && rect && createPortal(<div id={id} role="listbox" style={{ position: "fixed", top: rect.bottom + 200 > window.innerHeight ? Math.max(0, rect.top - 200) : rect.bottom, left: rect.left, width: rect.width, zIndex: 100000, maxHeight: 200, overflow: "auto", background: "var(--panel, #102c3b)", color: "var(--text, #e0edf5)", border: "1px solid #528ba3" }}>
      {options.map((option, i) => <div id={`${id}-${i}`} role="option" aria-selected={i === index} key={option.label} onMouseDown={event => { event.preventDefault(); choose(option); }} style={{ padding: "6px 8px", cursor: "pointer", background: i === index ? "#246282" : undefined, color: i === index ? "#ffffff" : undefined }}>{option.label}</div>)}
    </div>, document.body)}
  </div>;
}
