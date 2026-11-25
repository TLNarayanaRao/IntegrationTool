import { ChevronDown } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { createPortal } from "react-dom";

type RibbonSection = {
  label: string;
  caption?: string;
  icon: ComponentType;
  commands: ReactNode;
};

// Start with a dropdown for every section, then expand what fits in order.
export function expandedRibbonSections(width: number, expanded: number[], collapsed: number[]) {
  let remaining = width - collapsed.reduce((total, size) => total + size, 0);
  return expanded.map((size, index) => {
    const extra = size - collapsed[index];
    if (extra > remaining) return false;
    remaining -= extra;
    return true;
  });
}

export default function ResponsiveRibbon({ label, sections, status }: {
  label: string;
  sections: RibbonSection[];
  status?: ReactNode;
}) {
  const ribbon = useRef<HTMLElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const [expanded, setExpanded] = useState<boolean[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const root = ribbon.current;
    if (!root) return;
    const fit = () => {
      const style = getComputedStyle(root);
      const available = Math.min(root.clientWidth, window.innerWidth) -
        parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) -
        (root.querySelector(".debug-ribbon-status")?.getBoundingClientRect().width ?? 0);
      const widths = (selector: string) => Array.from(root.querySelectorAll(selector), element =>
        Math.ceil(element.getBoundingClientRect().width));
      const expandedWidths = widths(".ribbon-expanded");
      const compactWidth = parseFloat(style.getPropertyValue("--ribbon-compact-width"));
      const next = expandedRibbonSections(Math.floor(available), expandedWidths, expandedWidths.map(() => compactWidth));
      setExpanded(previous => previous.join() === next.join() ? previous : next);
      setOpen(previous => previous !== null && next[previous] ? null : previous);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(root);
    root.querySelectorAll(".ribbon-expanded, .debug-ribbon-status").forEach(element => observer.observe(element));
    window.addEventListener("resize", fit);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, []);

  function close(restoreFocus = false) {
    if (restoreFocus) anchor.current?.focus();
    setOpen(null);
  }

  useLayoutEffect(() => {
    if (open === null || !menu.current || !anchor.current) return;
    const panel = menu.current;
    const trigger = anchor.current;
    const place = () => {
      const margin = 8;
      const bounds = trigger.getBoundingClientRect();
      const below = window.innerHeight - bounds.bottom - margin;
      const above = bounds.top - margin;
      const opensAbove = panel.scrollHeight > below && above > below;
      panel.style.left = `${Math.max(margin, Math.min(bounds.left, window.innerWidth - panel.offsetWidth - margin))}px`;
      panel.style.maxHeight = `${Math.max(0, (opensAbove ? above : below) - 4)}px`;
      panel.style.top = opensAbove ? "" : `${bounds.bottom + 4}px`;
      panel.style.bottom = opensAbove ? `${window.innerHeight - bounds.top + 4}px` : "";
    };
    place();
    (panel.querySelector<HTMLElement>("button:enabled, select:enabled") ?? panel).focus({preventScroll:true});
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  useEffect(() => {
    if (open === null) return;
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menu.current?.contains(target) && !anchor.current?.contains(target)) setOpen(null);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  const active = open === null ? undefined : sections[open];
  return <section ref={ribbon} className={`studio-ribbon${status ? " debug-ribbon" : ""}`} aria-label={label}>
    {status}
    {sections.map(({label, caption, icon: Icon, commands}, index) =>
      <div className="ribbon-group" data-expanded={!!expanded[index]} role="group" aria-label={label} key={label}>
        <button type="button" className="ribbon-trigger" aria-expanded={open === index} aria-controls={open === index ? menuId : undefined} title={label}
          onClick={event => { anchor.current = event.currentTarget; setOpen(open === index ? null : index); }}>
          <Icon/><span>{label}</span><ChevronDown className="ribbon-chevron"/>
        </button>
        <div className="ribbon-expanded">
          <div className="ribbon-commands">{commands}</div>
          <b>{caption ?? label}</b>
        </div>
      </div>)}
    {active && createPortal(<div ref={menu} id={menuId} className="ribbon-dropdown" role="group" aria-label={active.label} tabIndex={-1}
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); close(true); } }}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== anchor.current) close(); }}
      onClickCapture={event => { if ((event.target as Element).closest("button:enabled")) close(true); }}
      onChangeCapture={event => { if (event.target instanceof HTMLSelectElement) close(true); }}>
      {active.commands}
    </div>, document.body)}
  </section>;
}
