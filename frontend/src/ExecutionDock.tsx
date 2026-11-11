import {useEffect, useRef, type ReactNode} from "react";
import ModalLayer from "./ModalLayer";
import "./execution-dock.css";

export default function ExecutionDock({mode, children}: {mode:"normal"|"expanded"|"fullscreen"; children:ReactNode}) {
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    root.current?.focus({preventScroll:true});
    const log = root.current?.querySelector<HTMLElement>(".execution-log-list");
    if (!log) return;
    let following = true, frame = 0;
    const scrolled = () => {following = log.scrollHeight - log.clientHeight - log.scrollTop < 24;};
    const follow = () => {
      if (!following) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {if (following) log.scrollTop = log.scrollHeight;});
    };
    const observer = new MutationObserver(follow);
    observer.observe(log,{childList:true,characterData:true,subtree:true});
    log.addEventListener("scroll",scrolled);
    follow();
    return () => {observer.disconnect(); log.removeEventListener("scroll",scrolled); cancelAnimationFrame(frame);};
  }, [mode]);
  const panel = <section ref={root} tabIndex={-1} aria-label="Execution and logs"
    role={mode === "normal" ? undefined : "dialog"} aria-modal={mode === "normal" ? undefined : true}
    className={`monitor execution-console execution-console-${mode}`}>{children}</section>;
  return mode === "normal" ? panel : <ModalLayer className="execution-dock-layer">{panel}</ModalLayer>;
}
