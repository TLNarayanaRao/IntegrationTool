import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { mapperFunctionCatalog } from "./mapper-functions";
import { completeMapping, mappingPathSuggestions } from "./mappingCompletion";
import { focusNextMapping } from "./mappingFocus";

export default function MappingExpressionInput({ value, onChange, onCommit, error = "", paths = [], label = "Mapping expression", multiline = false }: any) {
  const id = useId();
  const input = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [open, setOpen] = useState(false), [index, setIndex] = useState(0);
  const [completionSelected, setCompletionSelected] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => { if (!(event.target instanceof Element && event.target.closest('[role="listbox"]'))) setOpen(false); };
    window.addEventListener("scroll", close, true); window.addEventListener("resize", close);
    return () => { window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, [open]);
  const text = value == null ? "" : String(value);
  const Input = multiline ? "textarea" : "input";
  useEffect(() => {
    if (!multiline || !input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = `${input.current.scrollHeight}px`;
  }, [text, multiline]);
  useEffect(() => {
    if (!multiline || !input.current?.parentElement) return;
    let previousWidth = -1, frame = 0;
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (width === previousWidth) return;
      previousWidth = width;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!input.current) return;
        input.current.style.height = "auto";
        input.current.style.height = `${input.current.scrollHeight}px`;
      });
    });
    observer.observe(input.current.parentElement);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [multiline]);
  const [caret, setCaret] = useState<number | null>(null);
  const prefix = text.slice(0, caret ?? text.length), suffix = text.slice(caret ?? text.length);
  const token = prefix.match(/(?:\$\{?|)([\w.@\[\]-]+)$/)?.[1] || "";
  const options = open && token ? mappingPathSuggestions(paths, prefix)
    .map(path => ({ label: path, insert: `\${${path}}` }))
    .concat(mapperFunctionCatalog.filter(fn => fn.name.toLowerCase().startsWith(token.toLowerCase())).map(fn => ({ label: fn.signature, insert: fn.template }))).slice(0, 30) : [];
  const choose = (option: { insert: string }) => {
    const current = input.current?.value ?? text;
    const position = Math.min(input.current?.selectionStart ?? current.length, current.length);
    const completed = completeMapping(current.slice(0, position), current.slice(position), option.insert);
    onChange(completed);
    setCaret(null);
    setOpen(false); setIndex(0);
    return completed;
  };
  const commitAndAdvance = (raw: string) => {
    setOpen(false);
    if (onCommit?.(raw) === false) { input.current?.focus(); return; }
    const current = input.current;
    if (current) requestAnimationFrame(() => focusNextMapping(current));
  };
  return <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
    <Input ref={input} data-mapping-input rows={multiline ? 1 : undefined} className={multiline ? "mapping-expression-multiline" : undefined} aria-label={label} role="combobox" aria-autocomplete="list" aria-expanded={open && !!options.length}
      aria-activedescendant={open && options.length ? `${id}-${Math.min(index, options.length - 1)}` : undefined}
      aria-controls={id} value={text} placeholder="Type a data path or function…" style={{ width: "100%", boxSizing: "border-box" }}
      aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} title={error || text || undefined}
      onFocus={event => { setCompletionSelected(false); setCaret(event.currentTarget.selectionStart); setRect(input.current?.getBoundingClientRect() || null); setOpen(true); }} onBlur={() => setOpen(false)}
      onSelect={event => setCaret(event.currentTarget.selectionStart)}
      onChange={event => { setCompletionSelected(false); setRect(input.current?.getBoundingClientRect() || null); setCaret(event.target.selectionStart); onChange(event.target.value); setIndex(0); setOpen(true); }}
      onKeyDown={event => {
        if (multiline && event.key === "Enter" && event.shiftKey) { event.stopPropagation(); return; }
        if (event.ctrlKey && event.code === "Space") { event.preventDefault(); event.stopPropagation(); setCompletionSelected(true); setRect(input.current?.getBoundingClientRect() || null); setCaret(event.currentTarget.selectionStart); setOpen(true); setIndex(0); return; }
        if (event.key === "Escape") { setOpen(false); event.stopPropagation(); }
        if (event.key === "Enter" && (!open || !options.length || !completionSelected)) { event.preventDefault(); event.stopPropagation(); commitAndAdvance(event.currentTarget.value); return; }
        if (!open || !options.length) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); event.stopPropagation(); setCompletionSelected(true); setIndex((index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length); }
        if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); event.stopPropagation(); const option = options[Math.min(index, options.length - 1)]; const completed = choose(option); if (event.key === "Enter") commitAndAdvance(completed); }
      }}/>
    {error && <small id={`${id}-error`} className="mapping-validation-error" role="alert">{error}</small>}
    {open && !!options.length && rect && createPortal(<div id={id} role="listbox" style={{ position: "fixed", top: rect.bottom + 200 > window.innerHeight ? Math.max(0, rect.top - 200) : rect.bottom, left: rect.left, width: rect.width, zIndex: 100000, maxHeight: 200, overflow: "auto", background: "var(--panel, #102c3b)", color: "var(--text, #e0edf5)", border: "1px solid #528ba3" }}>
      {options.map((option, i) => <div id={`${id}-${i}`} role="option" aria-selected={i === index} key={option.label} onMouseDown={event => { event.preventDefault(); choose(option); }} style={{ padding: "6px 8px", cursor: "pointer", background: i === index ? "#246282" : undefined, color: i === index ? "#ffffff" : undefined }}>{option.label}</div>)}
    </div>, document.body)}
  </div>;
}
