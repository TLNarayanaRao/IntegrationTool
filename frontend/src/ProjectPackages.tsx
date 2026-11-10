import { useState, type MouseEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Folder, FolderOpen } from "lucide-react";
import ModalLayer from "./ModalLayer";

export const DEFAULT_PACKAGE = "Default";
export type PackageCategory = "tasks" | "resources" | "schemas";
export type PackageCatalog = Partial<Record<PackageCategory, string[]>>;
type PackageItem = { id: string; package_path?: string };
const packagePattern = /^[\p{L}\p{N}_-]+(?:\/[\p{L}\p{N}_-]+){0,15}$/u;
const windowsDevice = /^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])$/i;

export function packagePath(value?: string) {
  return value && value.length <= 1024 && packagePattern.test(value) ? value : DEFAULT_PACKAGE;
}

export function packagePaths(explicit: string[] = [], items: PackageItem[] = [], includeDefault = true) {
  const paths = new Set(includeDefault ? [DEFAULT_PACKAGE] : []);
  for (const candidate of [...explicit, ...items.map(item => item.package_path)]) {
    const segments = packagePath(candidate).split("/");
    segments.forEach((_, index) => paths.add(segments.slice(0, index + 1).join("/")));
  }
  return [...paths].sort((left, right) => left.localeCompare(right));
}

export function renamedPackagePath(path: string, from: string, to: string) {
  return path === from || path.startsWith(from + "/") ? to + path.slice(from.length) : path;
}

export const artifactNamePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

export function PackageTree<T extends PackageItem>({ paths, items, indent, isCollapsed, toggle, onMenu, renderItem }: {
  paths: string[];
  items: T[];
  indent: number;
  isCollapsed: (path: string) => boolean;
  toggle: (path: string) => void;
  onMenu: (event: MouseEvent, path: string) => void;
  renderItem: (item: T) => ReactNode;
}) {
  const children = new Map<string, string[]>();
  const contents = new Map<string, T[]>();
  for (const path of paths) {
    const parent = path.slice(0, Math.max(0, path.lastIndexOf("/")));
    children.set(parent, [...(children.get(parent) || []), path]);
  }
  for (const item of items) {
    const path = packagePath(item.package_path);
    const entries = contents.get(path);
    if (entries) entries.push(item);
    else contents.set(path, [item]);
  }
  const render = (parent: string, depth: number): ReactNode => children.get(parent)?.map(path => {
    const expanded = !isCollapsed(path);
    return <div className="explorer-package" key={path}>
      <button type="button" className="tree-row explorer-package-row" aria-expanded={expanded} title={path}
        style={{paddingInlineStart: `min(${indent + depth * 12}px, 55%)`}}
        onClick={() => toggle(path)} onContextMenu={event => { event.preventDefault(); onMenu(event, path); }}>
        {expanded ? <ChevronDown/> : <ChevronRight/>}{expanded ? <FolderOpen/> : <Folder/>}
        <span className="explorer-item-name">{path.slice(path.lastIndexOf("/") + 1)}</span>
      </button>
      {expanded && <>
        {render(path, depth + 1)}
        <div className="explorer-package-items" style={{paddingInlineStart: `min(${indent + depth * 12 + 24}px, 60%)`}}>
          {contents.get(path)?.map(renderItem)}
        </div>
      </>}
    </div>;
  });
  return <>{render("", 0)}</>;
}

export function PackageDialog({ paths, parent, moving, renaming, artifact = false, onClose, onSave }: {
  paths: string[];
  parent?: string;
  moving?: string;
  renaming?: string;
  artifact?: boolean;
  onClose: () => void;
  onSave: (path: string) => void;
}) {
  const [name, setName] = useState(renaming?.split("/").pop() || "");
  const [destination, setDestination] = useState(moving || DEFAULT_PACKAGE);
  const segment = name.trim().replace(/\s+/g, "-");
  const candidate = parent ? `${parent}/${segment}` : segment;
  const renamedPaths = renaming ? paths.filter(path => path === renaming || path.startsWith(renaming + "/")) : [];
  const unaffected = new Set(paths.filter(path => !renamedPaths.includes(path)).map(path => path.toLowerCase()));
  const valid = moving ? destination !== moving && paths.includes(destination) : artifact ?
    artifactNamePattern.test(segment) && !windowsDevice.test(segment.split(".")[0]) && segment !== renaming :
    !!segment && !segment.includes("/") && !windowsDevice.test(segment) && candidate.length <= 1024 && packagePattern.test(candidate) &&
    (renaming ? candidate !== renaming && renamedPaths.every(path => {
      const next = renamedPackagePath(path, renaming, candidate);
      return next.length <= 1024 && !unaffected.has(next.toLowerCase());
    }) :
      !paths.some(path => path.toLowerCase() === candidate.toLowerCase()));
  const title = moving ? "Move to package" : artifact ? "Rename deployment package" : renaming ? "Rename package" : "Create package";
  return <ModalLayer className="modal-backdrop">
    <form className="runtime-modal rename-modal" role="dialog" aria-modal="true" aria-labelledby="object-package-title"
      onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}
      onSubmit={event => { event.preventDefault(); if (valid) onSave(moving ? destination : candidate); }}>
      <header><b id="object-package-title">{title}</b>
        <button type="button" aria-label="Close package dialog" onClick={onClose}>×</button></header>
      <main>{moving ? <label>Destination package<select autoFocus value={destination} onChange={event => setDestination(event.target.value)}>
        {paths.map(path => <option key={path}>{path}</option>)}
      </select></label> : <>
        {parent && <small>Parent package · {parent}</small>}
        <label>{artifact ? "Artifact name" : "Package name"}<input autoFocus onFocus={event => event.target.select()} value={name} onChange={event => setName(event.target.value)} maxLength={artifact ? undefined : 64} required/></label>
        <small>{artifact ? "This changes the name of future exports. The version and other settings are kept." : "Use letters, numbers, underscores, or hyphens. Spaces become hyphens."}</small>
        {segment && segment !== renaming?.split("/").pop() && !valid && <small role="alert">{artifact ? "Use a valid artifact name: letters, numbers, dots, underscores, or hyphens." : "Enter a valid package name that is unique in this folder."}</small>}
      </>}</main>
      <footer><button type="button" onClick={onClose}>Cancel</button>
        <button type="submit" className="primary" disabled={!valid}>{moving ? "Move" : renaming ? "Rename" : "Create package"}</button></footer>
    </form>
  </ModalLayer>;
}
