import { createPortal } from "react-dom";
import type { HTMLAttributes } from "react";
import "./modal-layer.css";

/** Keep full-screen dialogs outside panel clipping and stacking contexts. */
export default function ModalLayer({ className = "modal-backdrop", ...props }: HTMLAttributes<HTMLDivElement>) {
  return createPortal(<div {...props} className={`${className} viewport-modal-layer`}/>, document.body);
}
