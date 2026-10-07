import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Search } from "lucide-react";
import "./canvas-magnifier.css";

export function magnifierPosition(x: number, y: number, width: number, height: number, viewportWidth: number, viewportHeight: number) {
  const left = x + width + 18 <= viewportWidth ? x + 18 : x - width - 18;
  const top = y + height + 18 <= viewportHeight ? y + 18 : y - height - 18;
  return { left: Math.max(8, Math.min(left, viewportWidth - width - 8)), top: Math.max(8, Math.min(top, viewportHeight - height - 8)) };
}

export default function CanvasMagnifier({ canvas, zoom, taskId }: { canvas: RefObject<HTMLDivElement | null>; zoom: number; taskId: string }) {
  const [enabled, setEnabled] = useState(false);
  const lens = useRef<HTMLDivElement>(null);
  const snapshot = useRef<HTMLDivElement>(null);
  const label = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!enabled || !canvas.current || !lens.current || !snapshot.current) return;
    const surface = canvas.current;
    lens.current.style.visibility = "hidden";
    const content = surface.querySelector<HTMLElement>(".canvas-content");
    if (!content) return;
    let frame = 0;
    let dirty = true;
    let lastPoint: { x: number; y: number; target: Element | null } | null = null;
    const hide = () => { lastPoint = null; if (lens.current) lens.current.style.visibility = "hidden"; };
    const position = () => {
      if (!lastPoint || !lens.current || !snapshot.current) return;
      const bounds = content.getBoundingClientRect();
      const viewport = lens.current.querySelector<HTMLElement>(".canvas-magnifier-view")!;
      const scale = zoom * 2;
      const x = (lastPoint.x - bounds.left) / zoom;
      const y = (lastPoint.y - bounds.top) / zoom;
      snapshot.current.style.transform = `translate(${viewport.clientWidth / 2 - x * scale}px, ${viewport.clientHeight / 2 - y * scale}px) scale(${scale})`;
      const name = lastPoint.target?.closest(".node")?.querySelector("strong")?.textContent
        || lastPoint.target?.closest(".execution-group")?.querySelector(".execution-group-header b")?.textContent;
      if (label.current) label.current.textContent = name || "Move over an activity to read its full name";
      const size = lens.current.getBoundingClientRect();
      const place = magnifierPosition(lastPoint.x, lastPoint.y, size.width, size.height, window.innerWidth, window.innerHeight);
      lens.current.style.left = `${place.left}px`;
      lens.current.style.top = `${place.top}px`;
      lens.current.style.visibility = "visible";
    };
    const refresh = () => {
      frame = 0;
      if (!snapshot.current) return;
      dirty = false;
      const clone = content.cloneNode(true) as HTMLElement;
      clone.removeAttribute("style");
      clone.style.position = "relative";
      clone.style.width = `${content.offsetWidth}px`;
      clone.style.height = `${content.offsetHeight}px`;
      // SVG definitions must not collide with the live diagram's IDs.
      const ids = new Map<string, string>();
      clone.querySelectorAll<HTMLElement>("[id]").forEach(element => {
        const id = element.id;
        ids.set(id, `magnifier-${id}`);
        element.id = `magnifier-${id}`;
      });
      clone.querySelectorAll("*").forEach(element => {
        for (const attribute of Array.from(element.attributes)) {
          let value = attribute.value;
          ids.forEach((replacement, id) => { value = value.replaceAll(`url(#${id})`, `url(#${replacement})`); if (value === `#${id}`) value = `#${replacement}`; });
          if (value !== attribute.value) element.setAttribute(attribute.name, value);
        }
        element.removeAttribute("tabindex");
        if (element instanceof HTMLButtonElement || element instanceof HTMLInputElement) element.tabIndex = -1;
      });
      snapshot.current.replaceChildren(clone);
      position();
    };
    const observer = new MutationObserver(() => {
      dirty = true;
      if (lastPoint && !frame) frame = requestAnimationFrame(refresh);
    });
    observer.observe(content, { childList: true, subtree: true, attributes: true, characterData: true });
    refresh();
    const move = (event: PointerEvent) => {
      if (event.buttons || event.pointerType === "touch") { hide(); return; }
      lastPoint = { x: event.clientX, y: event.clientY, target: event.target instanceof Element ? event.target : null };
      if (dirty) refresh(); else position();
    };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setEnabled(false); };
    surface.addEventListener("pointermove", move);
    surface.addEventListener("pointerleave", hide);
    surface.addEventListener("pointerdown", hide);
    surface.addEventListener("scroll", hide);
    window.addEventListener("resize", hide);
    window.addEventListener("keydown", key);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      surface.removeEventListener("pointermove", move);
      surface.removeEventListener("pointerleave", hide);
      surface.removeEventListener("pointerdown", hide);
      surface.removeEventListener("scroll", hide);
      window.removeEventListener("resize", hide);
      window.removeEventListener("keydown", key);
    };
  }, [enabled, canvas, zoom, taskId]);
  return <>
    <button className="canvas-magnifier-toggle" type="button" aria-label="Magnify orchestrator" aria-pressed={enabled} title="Magnify on hover · Escape to turn off" onClick={() => setEnabled(value => !value)}><Search /></button>
    {enabled && createPortal(<div ref={lens} className="canvas-magnifier-lens" aria-hidden="true">
      <div className="canvas-magnifier-heading"><Search /> 2× magnifier</div>
      <div className="canvas-magnifier-view"><div ref={snapshot} className="canvas-magnifier-snapshot" /></div>
      <div ref={label} className="canvas-magnifier-name" />
    </div>, document.body)}
  </>;
}
