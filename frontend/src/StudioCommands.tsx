import { useEffect, useId, useRef, useState, type ComponentType, type KeyboardEvent } from "react";
import { Search, X } from "lucide-react";
import ModalLayer from "./ModalLayer";
import "./studio-commands.css";

export type StudioCommand = {
  label: string;
  detail: string;
  icon: ComponentType<{className?: string; "aria-hidden"?: boolean}>;
  shortcut?: string;
  disabled?: boolean;
  action: () => void;
};

export default function StudioCommands({ groups, onClose }: {
  groups: { label: string; commands: StudioCommand[] }[];
  onClose: () => void;
}) {
  const title = useId();
  const dialog = useRef<HTMLElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const previousFocus = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const results = groups.flatMap(group => group.commands.map(command => ({group: group.label, command})))
    .filter(({group, command}) => terms.every(term => `${group} ${command.label} ${command.detail} ${command.shortcut || ""}`.toLowerCase().includes(term)))
    .sort((a, b) => Number(!!a.command.disabled) - Number(!!b.command.disabled));
  const available = results.filter(item => !item.command.disabled);
  const selected = available[index] ?? available[0];
  const optionId = (position: number) => `${title}-option-${position}`;
  const activeId = selected && optionId(results.indexOf(selected));

  useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView({block: "nearest"});
  }, [activeId]);

  const dismiss = () => {
    onClose();
    requestAnimationFrame(() => previousFocus.current?.focus({preventScroll: true}));
  };
  const run = (command: StudioCommand) => {
    if (command.disabled) return;
    onClose();
    command.action();
    requestAnimationFrame(() => {
      if (document.activeElement === document.body && !document.querySelector(".viewport-modal-layer"))
        previousFocus.current?.focus({preventScroll: true});
    });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
    } else if (event.key === "Tab") {
      const stops = Array.from(dialog.current?.querySelectorAll<HTMLElement>("input, button") || []);
      if (stops.length) {
        event.preventDefault();
        const current = stops.indexOf(document.activeElement as HTMLElement);
        stops[(current + (event.shiftKey ? -1 : 1) + stops.length) % stops.length]?.focus();
      }
    } else if (event.target === input.current) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (available.length) {
          const current = selected ? available.indexOf(selected) : 0;
          setIndex((current + (event.key === "ArrowDown" ? 1 : -1) + available.length) % available.length);
        }
      } else if (event.key === "Enter" && selected && !event.nativeEvent.isComposing) {
        event.preventDefault();
        run(selected.command);
      }
    }
  };

  return <ModalLayer>
    <section className="studio-commands" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={onKeyDown}>
      <header><h2 id={title}>Studio Commands</h2><button type="button" onClick={dismiss} aria-label="Close Studio Commands"><X aria-hidden="true"/></button></header>
      <label className="studio-command-filter"><Search aria-hidden="true"/><input ref={input} autoFocus role="combobox" aria-label="Search Studio commands"
        aria-autocomplete="list" aria-controls={`${title}-results`} aria-expanded="true" aria-activedescendant={activeId}
        placeholder="Search commands, for example Validate Project" value={query} onChange={event => {setQuery(event.target.value); setIndex(0);}}/></label>
      <div className="studio-command-scroll">
        <p role="status">{results.length ? `${results.length} matching commands` : "No matching commands."}</p>
        <ul id={`${title}-results`} role="listbox" aria-label="Studio commands">
          {results.map(({group, command}, position) => <li id={optionId(position)} key={`${group}:${command.label}`}
            role="option" aria-selected={activeId === optionId(position)} aria-disabled={!!command.disabled}
            onMouseDown={event => event.preventDefault()} onClick={() => run(command)}>
            <command.icon aria-hidden={true}/>
            <span><strong>{command.label}</strong><small>{group} · {command.detail}</small></span>
            {command.disabled ? <small>Unavailable</small> : command.shortcut && <kbd>{command.shortcut}</kbd>}
          </li>)}
        </ul>
      </div>
      <footer><span><kbd>↑</kbd> <kbd>↓</kbd> Select</span><span><kbd>Enter</kbd> Run command</span><span><kbd>Esc</kbd> Close</span></footer>
    </section>
  </ModalLayer>;
}
