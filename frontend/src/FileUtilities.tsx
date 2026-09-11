import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Braces, CheckCircle2, ClipboardPaste, CodeXml, Columns3, Copy, Edit3, FileJson, FilePlus2, FileText, FolderOpen, Save, Search, Undo2, WrapText, X } from "lucide-react";
import "./file-utilities.css";
import "./file-utilities-layout.css";

export type UtilityMode = "xml" | "json" | "compare";
type FileReference = { id: string; name: string; size: number; modified?: number; file?: File; scratch?: boolean };
type FileWindow = { reference: FileReference; offset: number; bytes: Uint8Array; text: string; binary: boolean; eof: boolean };
const DEFAULT_WINDOW = 1024 * 1024, MAX_WINDOW = 4 * 1024 * 1024, MAX_PRETTY = 16 * 1024 * 1024, MAX_COMPARE_ROWS = 10000;

const bytesFromBase64 = (value: string) => { const raw = atob(value), output = new Uint8Array(raw.length); for (let index = 0; index < raw.length; index += 1) output[index] = raw.charCodeAt(index); return output; };
const bytesToBase64 = (bytes: Uint8Array) => { let binary = ""; for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768)); return btoa(binary); };
const looksBinary = (bytes: Uint8Array) => { const sample = bytes.subarray(0, Math.min(bytes.length, 8192)); if (sample.includes(0)) return true; let controls = 0; sample.forEach((value) => { if (value < 9 || (value > 13 && value < 32)) controls += 1; }); return sample.length > 0 && controls / sample.length > .08; };
const decode = (bytes: Uint8Array) => new TextDecoder("utf-8", { fatal: false }).decode(bytes);
const alignUtf8Window = (bytes: Uint8Array, offset: number, eof: boolean) => {
  let start = 0, end = bytes.length;
  if (offset > 0) while (start < Math.min(4, end) && (bytes[start] & 0xc0) === 0x80) start += 1;
  if (!eof && end > start) {
    let lead = end - 1;
    while (lead > start && end - lead <= 4 && (bytes[lead] & 0xc0) === 0x80) lead -= 1;
    const first = bytes[lead], expected = first < 0x80 ? 1 : first >= 0xf0 ? 4 : first >= 0xe0 ? 3 : first >= 0xc0 ? 2 : 1;
    if (end - lead < expected) end = lead;
  }
  return { bytes: bytes.subarray(start, end), offset: offset + start };
};
const formatBytes = (value: number) => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : value < 1073741824 ? `${(value / 1048576).toFixed(1)} MB` : `${(value / 1073741824).toFixed(2)} GB`;
const hexLines = (bytes: Uint8Array, start: number) => Array.from({ length: Math.ceil(bytes.length / 16) }, (_, row) => { const slice = bytes.subarray(row * 16, row * 16 + 16), hex = Array.from(slice).map((value) => value.toString(16).padStart(2, "0")).join(" ").padEnd(47), ascii = Array.from(slice).map((value) => value >= 32 && value < 127 ? String.fromCharCode(value) : ".").join(""); return `${(start + row * 16).toString(16).padStart(8, "0")}  ${hex}  ${ascii}`; }).join("\n");
const bytesFromHexLines = (value: string) => { const output: number[] = []; for (const line of value.split("\n")) { if (!line.trim()) continue; const match = line.match(/^[0-9a-fA-F]{8}\s{2}(.{2,47})/); if (!match) throw new Error("Invalid hexadecimal row. Keep the address and byte columns intact."); const pairs = match[1].match(/[0-9a-fA-F]{2}/g) || []; output.push(...pairs.map((pair) => Number.parseInt(pair, 16))); } return new Uint8Array(output); };
const decodeAngleEntities = (value: string) => value.replaceAll("&lt;", "<").replaceAll("&gt;", ">");
const prettyXml = (source: string) => {
  const document = new DOMParser().parseFromString(source, "application/xml"), error = document.querySelector("parsererror");
  if (error) throw new Error(error.textContent?.split("\n")[0] || "XML is not well formed.");
  const compact = new XMLSerializer().serializeToString(document).replace(/>\s*</g, "><"), tokens = compact.replace(/></g, ">\n<").split("\n");
  let depth = 0;
  return tokens.map((token) => { const closing = /^<\//.test(token), declaration = /^<\?|^<!/.test(token), selfClosing = /\/>$/.test(token) || /<[^>]+>.*<\/[^>]+>$/.test(token); if (closing) depth = Math.max(0, depth - 1); const line = `${"  ".repeat(depth)}${token}`; if (!closing && !declaration && !selfClosing) depth += 1; return line; }).join("\n");
};
const prettyXmlWindow = (source: string) => { const tokens = source.replace(/>\s*</g, "><").replace(/></g, ">\n<").split("\n"); let depth = 0; return tokens.map((token) => { if (/^<\//.test(token)) depth = Math.max(0, depth - 1); const line = `${"  ".repeat(depth)}${token}`; if (/^<[^!?/][^>]*>$/.test(token) && !/\/>$/.test(token) && !/<\/[^>]+>$/.test(token)) depth += 1; return line; }).join("\n"); };
const prettyJsonWindow = (source: string) => { let output = "", depth = 0, quoted = false, escaped = false; for (const char of source) { if (quoted) { output += char; if (escaped) escaped = false; else if (char === "\\") escaped = true; else if (char === '"') quoted = false; continue; } if (char === '"') { quoted = true; output += char; } else if (char === "{" || char === "[") { depth += 1; output += `${char}\n${"  ".repeat(depth)}`; } else if (char === "}" || char === "]") { depth = Math.max(0, depth - 1); output += `\n${"  ".repeat(depth)}${char}`; } else if (char === ",") output += `,\n${"  ".repeat(depth)}`; else if (char === ":") output += ": "; else if (!/\s/.test(char)) output += char; } return output; };

async function chooseBrowserFile(accept = ""): Promise<FileReference | null> {
  return new Promise((resolve) => { let settled = false; const finish = (value: FileReference | null) => { if (!settled) { settled = true; resolve(value); } }; const input = document.createElement("input"); input.type = "file"; input.accept = accept; input.oncancel = () => finish(null); input.onchange = () => { const file = input.files?.[0]; finish(file ? { id: `browser-${crypto.randomUUID()}`, name: file.name, size: file.size, modified: file.lastModified, file } : null); }; window.addEventListener("focus", () => setTimeout(() => { if (!input.files?.length) finish(null); }, 250), { once: true }); input.click(); });
}

function alignLines(left: string[], right: string[]) {
  const rows: Array<{ leftNumber?: number; rightNumber?: number; left: string; right: string; kind: "same" | "changed" | "added" | "removed" }> = [], lookahead = 24;
  let a = 0, b = 0;
  while (a < left.length || b < right.length) {
    if (left[a] === right[b]) { rows.push({ leftNumber: a + 1, rightNumber: b + 1, left: left[a] || "", right: right[b] || "", kind: "same" }); a += 1; b += 1; continue; }
    let nextLeft = -1, nextRight = -1;
    for (let distance = 1; distance <= lookahead && nextLeft < 0 && nextRight < 0; distance += 1) { if (a + distance < left.length && left[a + distance] === right[b]) nextLeft = distance; if (b + distance < right.length && right[b + distance] === left[a]) nextRight = distance; }
    if (nextLeft > 0 && (nextRight < 0 || nextLeft <= nextRight)) { rows.push({ leftNumber: a + 1, left: left[a], right: "", kind: "removed" }); a += 1; continue; }
    if (nextRight > 0) { rows.push({ rightNumber: b + 1, left: "", right: right[b], kind: "added" }); b += 1; continue; }
    if (a < left.length && b < right.length) { rows.push({ leftNumber: a + 1, rightNumber: b + 1, left: left[a], right: right[b], kind: "changed" }); a += 1; b += 1; }
    else if (a < left.length) { rows.push({ leftNumber: a + 1, left: left[a], right: "", kind: "removed" }); a += 1; }
    else { rows.push({ rightNumber: b + 1, left: "", right: right[b], kind: "added" }); b += 1; }
  }
  return rows;
}

function useChunkReader() {
  const browserFiles = useRef(new Map<string, File>());
  const choose = async (mode: UtilityMode): Promise<FileReference | null> => {
    const extensions = mode === "xml" ? ["xml", "xsd", "wsdl"] : mode === "json" ? ["json", "jsonl"] : [];
    if (window.fabricDesktop) return window.fabricDesktop.openUtilityFile({ title: mode === "compare" ? "Select file to compare" : `Open ${mode.toUpperCase()} file`, filterName: `${mode.toUpperCase()} files`, extensions });
    const reference = await chooseBrowserFile(extensions.length ? extensions.map((item) => `.${item}`).join(",") : "");
    if (reference?.file) browserFiles.current.set(reference.id, reference.file);
    return reference;
  };
  const read = async (reference: FileReference, offset: number, length: number): Promise<FileWindow> => {
    let bytes: Uint8Array, size = reference.size;
    if (reference.file || browserFiles.current.has(reference.id)) bytes = new Uint8Array(await (reference.file || browserFiles.current.get(reference.id))!.slice(offset, offset + length).arrayBuffer());
    else {
      const result = await window.fabricDesktop!.readUtilityFileChunk({ id: reference.id, offset, length });
      bytes = bytesFromBase64(result.base64); size = result.size;
    }
    const binary = looksBinary(bytes), fileEof = offset + bytes.length >= size;
    if (!binary) { const aligned = alignUtf8Window(bytes, offset, fileEof); bytes = aligned.bytes; offset = aligned.offset; }
    return { reference: { ...reference, size }, offset, bytes, binary, text: binary ? hexLines(bytes, offset) : decode(bytes), eof: fileEof };
  };
  const close = (reference?: FileReference) => { if (!reference) return; browserFiles.current.delete(reference.id); if (window.fabricDesktop) void window.fabricDesktop.closeUtilityFile(reference.id); };
  const save = async (reference: FileReference, offset: number, originalLength: number, replacement: string | Uint8Array): Promise<FileReference> => {
    const bytes = typeof replacement === "string" ? new TextEncoder().encode(replacement) : replacement;
    if (window.fabricDesktop) {
      const result = await window.fabricDesktop.saveUtilityFileWindow({ id: reference.id, offset, originalLength, base64: bytesToBase64(bytes), expectedModified: reference.modified });
      return { ...reference, ...result };
    }
    const source = reference.file || browserFiles.current.get(reference.id);
    if (!source) throw new Error("The browser file handle is no longer available.");
    const replacementBuffer = Uint8Array.from(bytes).buffer;
    const updatedFile = new File([source.slice(0, offset), replacementBuffer, source.slice(offset + originalLength)], reference.name, { type: source.type, lastModified: Date.now() });
    browserFiles.current.set(reference.id, updatedFile);
    const url = URL.createObjectURL(updatedFile), anchor = document.createElement("a");
    anchor.href = url; anchor.download = reference.name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    return { ...reference, size: updatedFile.size, modified: updatedFile.lastModified, file: updatedFile };
  };
  const saveAs = async (name: string, replacement: string | Uint8Array, mode: UtilityMode): Promise<FileReference | null> => {
    const bytes = typeof replacement === "string" ? new TextEncoder().encode(replacement) : replacement;
    const extensions = mode === "xml" ? ["xml", "xsd", "wsdl"] : mode === "json" ? ["json", "jsonl"] : [name.includes(".") ? name.split(".").pop()! : "txt"];
    if (window.fabricDesktop) return window.fabricDesktop.saveUtilityFileAs({ filename: name, title: "Save editor content as", filterName: mode === "compare" ? "Document" : `${mode.toUpperCase()} file`, extensions, base64: bytesToBase64(bytes) });
    const file = new File([Uint8Array.from(bytes).buffer], name, { type: "text/plain", lastModified: Date.now() }), url = URL.createObjectURL(file), anchor = document.createElement("a"), id = `browser-${crypto.randomUUID()}`;
    anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); browserFiles.current.set(id, file);
    return { id, name, size: file.size, modified: file.lastModified, file };
  };
  return { choose, read, save, saveAs, close };
}

function FilePager({ value, pageSize, setPageSize, navigate, locked = false }: { value?: FileWindow; pageSize: number; setPageSize: (value: number) => void; navigate: (offset: number) => void; locked?: boolean }) {
  if (!value) return null;
  const end = value.offset + value.bytes.length;
  return <div className="utility-pager"><button disabled={locked || !value.offset} onClick={() => navigate(Math.max(0, value.offset - pageSize))}><ArrowLeft/> Previous</button><span>{formatBytes(value.offset)}–{formatBytes(end)} of {formatBytes(value.reference.size)}</span><select disabled={locked} value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option value={262144}>256 KB window</option><option value={1048576}>1 MB window</option><option value={4194304}>4 MB window</option></select><button disabled={locked || value.eof} onClick={() => navigate(end)}>Next <ArrowRight/></button></div>;
}

function Viewer({ mode }: { mode: "xml" | "json" }) {
  const reader = useChunkReader(), [view, setView] = useState<FileWindow>(), [pageSize, setPageSize] = useState(DEFAULT_WINDOW), [draft, setDraft] = useState<string | null>(null), [decodeAngles, setDecodeAngles] = useState(false), [wrapLines, setWrapLines] = useState(true), [query, setQuery] = useState(""), [message, setMessage] = useState("Select a file to begin."), [busy, setBusy] = useState(false);
  const closeRef = useRef(reader.close), activeReference = useRef<FileReference | undefined>(undefined), editorRef = useRef<HTMLTextAreaElement | null>(null); activeReference.current = view?.reference;
  useEffect(() => () => closeRef.current(activeReference.current), []);
  const base = mode === "xml" && decodeAngles ? decodeAngleEntities(view?.text || "") : view?.text || "", displayed = draft ?? base, dirty = Boolean(view && (draft !== null || decodeAngles));
  const canDiscard = () => !dirty || window.confirm("Discard the unsaved editor changes?");
  const load = async (reference: FileReference, offset = 0, length = pageSize) => { setBusy(true); try { const next = await reader.read(reference, offset, length); setView(next); setDraft(null); setDecodeAngles(false); setMessage(next.binary ? "Binary content detected; displaying a bounded hexadecimal window." : next.reference.size > MAX_PRETTY ? "Large-file mode: edit and save the current bounded window." : "File window loaded and ready to edit."); } catch (error: any) { setMessage(error.message || "Unable to read file."); } finally { setBusy(false); } };
  const open = async () => { if (!canDiscard()) return; const next = await reader.choose(mode); if (next) { reader.close(view?.reference); await load(next); } };
  const create = () => { if (!canDiscard()) return; reader.close(view?.reference); const name = `untitled.${mode}`, reference: FileReference = { id: `scratch-${crypto.randomUUID()}`, name, size: 0, scratch: true }; setView({ reference, offset: 0, bytes: new Uint8Array(), text: "", binary: false, eof: true }); setDraft(""); setDecodeAngles(false); setMessage(`New ${mode.toUpperCase()} document. Type or paste content, then choose Save or Save As.`); setTimeout(() => editorRef.current?.focus(), 0); };
  const pretty = async () => { if (!view || view.binary) return; setBusy(true); try { let source = draft ?? view.text, completeFile = view.offset === 0 && view.eof, activeView = view; if (draft === null && view.reference.size <= MAX_PRETTY && !completeFile) { activeView = await reader.read(view.reference, 0, view.reference.size); source = activeView.text; completeFile = true; setView(activeView); } const transformed = mode === "xml" ? (completeFile ? prettyXml(source) : prettyXmlWindow(source)) : (completeFile ? JSON.stringify(JSON.parse(source), null, 2) : prettyJsonWindow(source)); setDraft(mode === "xml" && decodeAngles ? decodeAngleEntities(transformed) : transformed); setMessage(completeFile ? "Pretty print prepared. Save to write the changes." : "Pretty-printed the current bounded window. Save before navigating."); } catch (error: any) { setMessage(`${mode.toUpperCase()} formatting failed: ${error.message}`); } finally { setBusy(false); } };
  const saveAs = async () => { if (!view) return; setBusy(true); try { const replacement = view.binary ? bytesFromHexLines(displayed) : displayed, reference = await reader.saveAs(view.reference.name, replacement, mode); if (!reference) { setMessage("Save As canceled."); return; } reader.close(view.reference); const next = await reader.read(reference, 0, pageSize); setView(next); setDraft(null); setDecodeAngles(false); setMessage(window.fabricDesktop ? `Saved as ${reference.name}.` : `Downloaded ${reference.name}.`); } catch (error: any) { setMessage(`Save As failed: ${error.message}`); } finally { setBusy(false); } };
  const save = async () => { if (!view || !dirty) return; if (view.reference.scratch) { await saveAs(); return; } setBusy(true); try { const replacement = view.binary ? bytesFromHexLines(displayed) : displayed, reference = await reader.save(view.reference, view.offset, view.bytes.length, replacement); const next = await reader.read(reference, view.offset, pageSize); setView(next); setDraft(null); setDecodeAngles(false); setMessage(window.fabricDesktop ? "Changes saved safely to the file." : "Edited file downloaded by the browser."); } catch (error: any) { setMessage(`Save failed: ${error.message}`); } finally { setBusy(false); } };
  const paste = async () => { try { const value = await navigator.clipboard.readText(); if (!view) { const reference: FileReference = { id: `scratch-${crypto.randomUUID()}`, name: `untitled.${mode}`, size: 0, scratch: true }; setView({ reference, offset: 0, bytes: new Uint8Array(), text: "", binary: false, eof: true }); setDraft(value); } else { const editor = editorRef.current, start = editor?.selectionStart ?? displayed.length, end = editor?.selectionEnd ?? start; setDraft(`${displayed.slice(0, start)}${value}${displayed.slice(end)}`); setTimeout(() => { if (editorRef.current) { editorRef.current.focus(); editorRef.current.selectionStart = editorRef.current.selectionEnd = start + value.length; } }, 0); } setMessage("Clipboard content inserted into the editor."); } catch { setMessage("Clipboard access was unavailable. Focus the editor and use Ctrl+V."); } };
  const highlighted = query ? displayed.split("\n").filter((line) => line.toLowerCase().includes(query.toLowerCase())) : [];
  return <section className="utility-viewer"><div className="utility-toolbar"><button className="primary" onClick={create}><FilePlus2/> New {mode.toUpperCase()}</button><button onClick={open}><FolderOpen/> Open</button><button onClick={() => void paste()}><ClipboardPaste/> Paste</button><button disabled={!view || view.binary || busy} onClick={pretty}><Braces/> Pretty print</button><button disabled={!dirty || busy} onClick={() => void save()}><Save/> Save</button><button disabled={!view || busy} onClick={() => void saveAs()}><Save/> Save As</button><button disabled={!dirty || busy} onClick={() => { setDraft(null); setDecodeAngles(false); setMessage("Unsaved changes discarded."); }}><Undo2/> Revert</button><button className={wrapLines ? "active" : ""} aria-pressed={wrapLines} onClick={() => setWrapLines((current) => !current)}><WrapText/> Wrap lines</button>{mode === "xml" && <label><input type="checkbox" checked={decodeAngles} disabled={!view?.text} onChange={(event) => { setDecodeAngles(event.target.checked); if (draft !== null && event.target.checked) setDraft(decodeAngleEntities(draft)); }}/> Decode &amp;lt; and &amp;gt;</label>}<label className="utility-search"><Search/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find in current window…"/></label></div>{view ? <><header className="utility-file-heading"><span>{mode === "xml" ? <CodeXml/> : <FileJson/>}<b>{view.reference.name}</b><small>{view.reference.scratch ? "new document" : `${formatBytes(view.reference.size)} · editable ${view.binary ? "binary/hex" : "UTF-8 text"}`}</small></span><i>{dirty ? "UNSAVED" : view.reference.size > pageSize ? "WINDOWED" : "COMPLETE"}</i></header><textarea ref={editorRef} aria-label={`${mode.toUpperCase()} document editor`} className={`utility-code${wrapLines ? " wrap" : ""}`} spellCheck={false} wrap={wrapLines ? "soft" : "off"} value={displayed} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void save(); } }}/>{!view.reference.scratch && <FilePager value={view} pageSize={pageSize} setPageSize={setPageSize} locked={dirty} navigate={(offset) => void load(view.reference, offset)}/>} {query && <div className="utility-findings">{highlighted.length} matching lines in this window</div>}</> : <div className="utility-empty"><FileText/><b>No {mode.toUpperCase()} document open</b><span>Choose New to type or paste content, or Open to edit a filesystem document in bounded windows.</span></div>}<footer className="utility-message">{busy ? "Working…" : message}{dirty ? " · Unsaved changes" : ""}</footer></section>;
}

function CompareViewer() {
  const reader = useChunkReader(), [left, setLeft] = useState<FileWindow>(), [right, setRight] = useState<FileWindow>(), [leftDraft, setLeftDraft] = useState<string | null>(null), [rightDraft, setRightDraft] = useState<string | null>(null), [pageSize, setPageSize] = useState(DEFAULT_WINDOW), [offset, setOffset] = useState(0), [differencesOnly, setDifferencesOnly] = useState(false), [selected, setSelected] = useState<Set<number>>(new Set()), [editMode, setEditMode] = useState(false), [message, setMessage] = useState("Select two files of any type."), [busy, setBusy] = useState(false);
  const closeRef = useRef(reader.close), activeReferences = useRef<{ left?: FileReference; right?: FileReference }>({}); activeReferences.current = { left: left?.reference, right: right?.reference };
  useEffect(() => () => { closeRef.current(activeReferences.current.left); closeRef.current(activeReferences.current.right); }, []);
  const content = (view?: FileWindow, draft?: string | null) => draft ?? (view ? (view.binary ? hexLines(view.bytes, view.offset) : view.text) : "");
  const leftText = content(left, leftDraft), rightText = content(right, rightDraft), leftDirty = leftDraft !== null, rightDirty = rightDraft !== null, dirty = leftDirty || rightDirty;
  const sideDirty = (side: "left" | "right") => side === "left" ? leftDirty : rightDirty;
  const canReplaceSide = (side: "left" | "right") => !sideDirty(side) || window.confirm(`Discard unsaved changes in the ${side} editor?`);
  const createSide = (side: "left" | "right") => { if (!canReplaceSide(side)) return; const reference: FileReference = { id: `scratch-${crypto.randomUUID()}`, name: `untitled-${side}.txt`, size: 0, scratch: true }, view: FileWindow = { reference, offset: 0, bytes: new Uint8Array(), text: "", binary: false, eof: true }; if (side === "left") { reader.close(left?.reference); setLeft(view); setLeftDraft(""); } else { reader.close(right?.reference); setRight(view); setRightDraft(""); } setOffset(0); setSelected(new Set()); setEditMode(true); setMessage(`New ${side} document. Type or paste content directly into the editor.`); };
  const open = async (side: "left" | "right") => { if (!canReplaceSide(side)) return; const reference = await reader.choose("compare"); if (!reference) return; setBusy(true); try { const view = await reader.read(reference, 0, pageSize); if (side === "left") { reader.close(left?.reference); setLeft(view); setLeftDraft(null); } else { reader.close(right?.reference); setRight(view); setRightDraft(null); } setOffset(0); setSelected(new Set()); setMessage("Comparison window loaded. Select differing rows to synchronize them."); } catch (error: any) { setMessage(error.message || "Unable to read comparison file."); } finally { setBusy(false); } };
  const navigate = async (nextOffset: number) => { if (!left || !right || dirty) return; setBusy(true); try { const [a, b] = await Promise.all([reader.read(left.reference, nextOffset, pageSize), reader.read(right.reference, nextOffset, pageSize)]); setLeft(a); setRight(b); setLeftDraft(null); setRightDraft(null); setSelected(new Set()); setOffset(nextOffset); } finally { setBusy(false); } };
  const allRows = useMemo(() => !left || !right ? [] : alignLines(leftText.split("\n"), rightText.split("\n")), [left, right, leftText, rightText]);
  const rows = allRows.map((row, index) => ({ ...row, index })).filter((row) => !differencesOnly || row.kind !== "same").slice(0, MAX_COMPARE_ROWS), changes = allRows.filter((row) => row.kind !== "same").length, maxSize = Math.max(left?.reference.size || 0, right?.reference.size || 0), eof = offset + pageSize >= maxSize;
  const selectable = rows.filter((row) => row.kind !== "same").map((row) => row.index), compatible = Boolean(left && right && left.binary === right.binary);
  const copySelected = (direction: "left-to-right" | "right-to-left") => {
    if (!selected.size || !compatible) return;
    const sourceLeft = direction === "left-to-right";
    const next = allRows.flatMap((row, index) => {
      const useSource = selected.has(index);
      const number = useSource ? (sourceLeft ? row.leftNumber : row.rightNumber) : (sourceLeft ? row.rightNumber : row.leftNumber);
      const value = useSource ? (sourceLeft ? row.left : row.right) : (sourceLeft ? row.right : row.left);
      return number === undefined ? [] : [value];
    }).join("\n");
    if (sourceLeft) setRightDraft(next); else setLeftDraft(next);
    setSelected(new Set()); setMessage(sourceLeft ? "Selected differences copied from left to right. Save the right file to persist." : "Selected differences copied from right to left. Save the left file to persist.");
  };
  const saveAsSide = async (side: "left" | "right") => {
    const view = side === "left" ? left : right, value = side === "left" ? leftText : rightText;
    if (!view) return;
    setBusy(true);
    try {
      const replacement = view.binary ? bytesFromHexLines(value) : value, reference = await reader.saveAs(view.reference.name, replacement, "compare");
      if (!reference) { setMessage("Save As canceled."); return; }
      reader.close(view.reference); const next = await reader.read(reference, 0, pageSize);
      if (side === "left") { setLeft(next); setLeftDraft(null); } else { setRight(next); setRightDraft(null); }
      setSelected(new Set()); setMessage(window.fabricDesktop ? `${side === "left" ? "Left" : "Right"} document saved as ${reference.name}.` : `Downloaded ${reference.name}.`);
    } catch (error: any) { setMessage(`Save As failed: ${error.message}`); } finally { setBusy(false); }
  };
  const saveSide = async (side: "left" | "right") => {
    const view = side === "left" ? left : right, draft = side === "left" ? leftDraft : rightDraft;
    if (!view || draft === null) return;
    if (view.reference.scratch) { await saveAsSide(side); return; }
    setBusy(true);
    try {
      const replacement = view.binary ? bytesFromHexLines(draft) : draft, reference = await reader.save(view.reference, view.offset, view.bytes.length, replacement), next = await reader.read(reference, view.offset, pageSize);
      if (side === "left") { setLeft(next); setLeftDraft(null); } else { setRight(next); setRightDraft(null); }
      setSelected(new Set()); setMessage(window.fabricDesktop ? `${side === "left" ? "Left" : "Right"} file saved safely.` : `Edited ${side} file downloaded by the browser.`);
    } catch (error: any) { setMessage(`Save failed: ${error.message}`); } finally { setBusy(false); }
  };
  return <section className="utility-viewer compare-viewer">
    <div className="utility-toolbar compare-toolbar"><button className="primary" onClick={() => createSide("left")}><FilePlus2/> New left</button><button onClick={() => void open("left")}><FolderOpen/> Open left</button><button className="primary" onClick={() => createSide("right")}><FilePlus2/> New right</button><button onClick={() => void open("right")}><FolderOpen/> Open right</button><button disabled={!leftDirty || busy} onClick={() => void saveSide("left")}><Save/> Save left</button><button disabled={!left || busy} onClick={() => void saveAsSide("left")}><Save/> Left As</button><button disabled={!rightDirty || busy} onClick={() => void saveSide("right")}><Save/> Save right</button><button disabled={!right || busy} onClick={() => void saveAsSide("right")}><Save/> Right As</button><button className={editMode ? "active" : ""} disabled={!left && !right} onClick={() => setEditMode((value) => !value)}><Edit3/> {editMode ? "Show differences" : "Edit files"}</button><label><input type="checkbox" checked={differencesOnly} onChange={(event) => setDifferencesOnly(event.target.checked)}/> Differences only</label></div>
    <div className="compare-syncbar"><button disabled={!compatible || !selected.size} onClick={() => copySelected("left-to-right")}><Copy/> Copy selected →</button><button disabled={!compatible || !selected.size} onClick={() => copySelected("right-to-left")}><Copy/> ← Copy selected</button><button disabled={!selectable.length} onClick={() => setSelected(new Set(selectable))}>Select all differences</button><button disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear selection</button><span className={changes ? "compare-changed" : "compare-equal"}>{left && right ? `${changes} differing rows · ${selected.size} selected` : "Waiting for two files"}</span></div>
    <div className="compare-headings"><span><b>{left?.reference.name || "Left document"}</b><small>{left ? `${left.reference.scratch ? "new document" : formatBytes(left.reference.size)}${leftDirty ? " · UNSAVED" : ""}` : "Create new or open a file"}</small></span><span><b>{right?.reference.name || "Right document"}</b><small>{right ? `${right.reference.scratch ? "new document" : formatBytes(right.reference.size)}${rightDirty ? " · UNSAVED" : ""}` : "Create new or open a file"}</small></span></div>
    {editMode ? <div className="compare-editors"><textarea aria-label="Edit left document" placeholder="Choose New left, open a file, or paste content here…" disabled={!left} spellCheck={false} value={leftText} onChange={(event) => setLeftDraft(event.target.value)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void saveSide("left"); } }}/><textarea aria-label="Edit right document" placeholder="Choose New right, open a file, or paste content here…" disabled={!right} spellCheck={false} value={rightText} onChange={(event) => setRightDraft(event.target.value)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void saveSide("right"); } }}/></div> : left && right ? <div className="compare-grid" role="table">{rows.map((row) => <React.Fragment key={`${row.leftNumber || "x"}-${row.rightNumber || "x"}-${row.index}`}><label className={`diff-select ${row.kind}`}><input type="checkbox" aria-label={`Select difference row ${row.index + 1}`} disabled={row.kind === "same" || !compatible} checked={selected.has(row.index)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(row.index); else next.delete(row.index); return next; })}/></label><div className={`${row.kind} line-number`}>{row.leftNumber || ""}</div><pre className={row.kind}>{row.left || " "}</pre><div className={`${row.kind} line-number`}>{row.rightNumber || ""}</div><pre className={row.kind}>{row.right || " "}</pre></React.Fragment>)}</div> : <div className="utility-empty"><Columns3/><b>Side-by-side file comparison</b><span>Create blank left and right documents to type or paste content, or open filesystem files. Then edit, compare, synchronize, and save.</span></div>}
    {!(left?.reference.scratch && right?.reference.scratch) && <div className="utility-pager"><button disabled={dirty || !left || !right || !offset} onClick={() => void navigate(Math.max(0, offset - pageSize))}><ArrowLeft/> Previous</button><span>{left && right ? `${formatBytes(offset)} window${dirty ? " · save or revert before navigating" : ""}` : "No comparison loaded"}</span><select disabled={dirty} value={pageSize} onChange={(event) => setPageSize(Math.min(MAX_WINDOW, Number(event.target.value)))}><option value={262144}>256 KB window</option><option value={1048576}>1 MB window</option><option value={4194304}>4 MB window</option></select><button disabled={dirty || !left || !right || eof} onClick={() => void navigate(offset + pageSize)}>Next <ArrowRight/></button></div>}
    <footer className="utility-message">{busy ? "Working…" : message}{!compatible && left && right ? " Copying rows is disabled when one side is binary and the other is text." : ""}</footer>
  </section>;
}

export default function FileUtilities({ initialMode, onClose }: { initialMode: UtilityMode; onClose: () => void }) {
  const [mode, setMode] = useState<UtilityMode>(initialMode);
  useEffect(() => setMode(initialMode), [initialMode]);
  return <div className="utility-workbench"><header><span><Columns3/><span><b>Data &amp; File Utilities</b><small>Bounded-memory viewers, editors, and side-by-side synchronization</small></span></span><button title="Close utility workspace" onClick={onClose}><X/></button></header><nav><button className={mode === "xml" ? "active" : ""} onClick={() => setMode("xml")}><CodeXml/> XML Viewer</button><button className={mode === "json" ? "active" : ""} onClick={() => setMode("json")}><FileJson/> JSON Viewer</button><button className={mode === "compare" ? "active" : ""} onClick={() => setMode("compare")}><Columns3/> Compare Files</button></nav><main><div className="utility-panel" hidden={mode !== "xml"}><Viewer mode="xml"/></div><div className="utility-panel" hidden={mode !== "json"}><Viewer mode="json"/></div><div className="utility-panel" hidden={mode !== "compare"}><CompareViewer/></div></main><footer><CheckCircle2/> File content is edited and saved in bounded windows; large files are never transferred to the UI as one unbounded payload.</footer></div>;
}
