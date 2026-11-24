import {useEffect, useRef, type ReactNode} from "react";
import ModalLayer from "./ModalLayer";
import "./execution-dock.css";

export default function ExecutionDock({mode, children}: {mode:"normal"|"expanded"|"fullscreen"; children:ReactNode}) {
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    root.current?.focus({preventScroll:true});
  }, [mode]);
  const panel = <section ref={root} tabIndex={-1} aria-label="Execution and logs"
    role={mode === "normal" ? undefined : "dialog"} aria-modal={mode === "normal" ? undefined : true}
    className={`monitor execution-console execution-console-${mode}`}>{children}</section>;
  return mode === "normal" ? panel : <ModalLayer className="execution-dock-layer">{panel}</ModalLayer>;
}
