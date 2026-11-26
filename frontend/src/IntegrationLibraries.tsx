import { useEffect, useRef, useState } from "react";
import ModalLayer from "./ModalLayer";
import "./integration-libraries.css";

export type LibraryOrigin = { alias: string; id: string; version: string; sha256: string; public: boolean };
export type LibraryPin = { alias: string; sha256: string; library: Release };
export type LibraryDialogMode = "install" | "publish" | "export";
type Category = "tasks" | "resources" | "schemas";
type Asset = { id: string; name: string; kind?: string; library_origin?: LibraryOrigin | null };
type Release = { id: string; name: string; version: string; description: string };
type CatalogRelease = Release & {
  sha256: string;
  exports: Record<Category, Asset[]>;
  settings: { key: string; required: boolean }[];
};
type RemoteRelease = Release & { sha256: string; teamId: string };
type LibraryProject = Record<Category, Asset[]> & { id: string; libraries?: LibraryPin[] };
type VersionReview = { breakingChanges: string[]; blockedBy?: string };
const categories: [Category, string][] = [["tasks", "Subtasks"], ["resources", "Connections"], ["schemas", "Schemas"]];
const emptyExports = (): Record<Category, string[]> => ({ tasks: [], resources: [], schemas: [] });
const versionKey = (release: Release) => `${release.id}/${release.version}`;
const downloadUrl = (release: Release) => `/api/libraries/${versionKey(release)}/archive`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/libraries${path}`, init);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join(". ") : "Library request failed.");
  }
  return data;
}

function post<T>(path: string, body: unknown) {
  return request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export default function IntegrationLibraries<P extends LibraryProject>({ project, initialMode, onChange, onClose }:
  { project: P; initialMode: LibraryDialogMode; onChange: (project: P) => void; onClose: () => void }) {
  const [catalog, setCatalog] = useState<CatalogRelease[]>([]);
  const [selected, setSelected] = useState("");
  const [alias, setAlias] = useState("");
  const [mode, setMode] = useState(initialMode);
  const [archiveSelection, setArchiveSelection] = useState("");
  const [name, setName] = useState("");
  const [identity, setIdentity] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [description, setDescription] = useState("");
  const [exports, setExports] = useState(emptyExports);
  const [published, setPublished] = useState<CatalogRelease>();
  const [review, setReview] = useState<VersionReview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [controlPlaneUrl, setControlPlaneUrl] = useState("");
  const [credential, setCredential] = useState("");
  const [teamId, setTeamId] = useState("");
  const [remoteReleases, setRemoteReleases] = useState<RemoteRelease[]>([]);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const connection = { controlPlaneUrl, credential, teamId };
  const pins = project.libraries || [];
  const release = catalog.find(entry => versionKey(entry) === selected);
  const installed = pins.find(pin => pin.alias === alias);
  const archivePin = pins.find(pin => `pin:${pin.alias}` === archiveSelection);
  const archiveRelease = catalog.find(entry => `catalog:${versionKey(entry)}` === archiveSelection);
  const hasSelection = Object.values(exports).some(ids => ids.length);

  useEffect(() => {
    mounted.current = true;
    request<CatalogRelease[]>("").then(entries => {
      if (mounted.current) setCatalog(current => [...entries.filter(entry => !current.some(item => versionKey(item) === versionKey(entry))), ...current]);
    })
      .catch(error => { if (mounted.current) setError(error.message); });
    return () => { mounted.current = false; };
  }, []);

  function selectRelease(entry: CatalogRelease) {
    setSelected(versionKey(entry));
    setAlias(pins.find(pin => pin.library.id === entry.id)?.alias || entry.id);
    setReview(undefined);
  }

  async function perform(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try { await action(); }
    catch (error) { setError(error instanceof Error ? error.message : "Library request failed."); }
    finally { inFlight.current = false; setBusy(false); }
  }

  async function addRelease(file: File) {
    await perform(async () => {
      const form = new FormData();
      form.append("file", file);
      const entry = await request<CatalogRelease>("/install", { method: "POST", body: form });
      setCatalog(items => [...items.filter(item => versionKey(item) !== versionKey(entry)), entry]);
      selectRelease(entry);
      setNotice("Library added to the catalog.");
    });
  }

  async function attach() {
    if (!release) return;
    await perform(async () => {
      const body = { project, library_id: release.id, version: release.version, alias, sha256: release.sha256 };
      if (installed && !review) {
        setReview(await post<VersionReview>("/attach", { ...body, preview: true }));
        return;
      }
      const result = await post<{ project: P }>("/attach", { ...body, allow_breaking: Boolean(review?.breakingChanges.length) });
      if (mounted.current) onChange(result.project);
      setReview(undefined);
      setNotice(`${release.name} ${release.version} added to the project.`);
    });
  }

  async function downloadArchive(path: string, release: Release, options?: RequestInit) {
    await perform(async () => {
      const response = await fetch(path, options);
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw Error(typeof error?.detail === "string" ? error.detail : "Unable to export the library release.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${release.id}-${release.version}.mlib`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  function exportPin(pin: LibraryPin) {
    return downloadArchive("/api/libraries/pin/archive", pin.library, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...pin, project_id: project.id }),
    });
  }

  async function publish() {
    await perform(async () => {
      const entry = await post<CatalogRelease>("/publish", { project, id: identity, name, version, description, exports });
      setPublished(entry);
      setCatalog(items => [...items.filter(item => versionKey(item) !== versionKey(entry)), entry]);
      setNotice(`${entry.name} ${entry.version} published.`);
    });
  }

  return <ModalLayer><section className="integration-libraries" role="dialog" aria-modal="true" aria-labelledby="library-title">
    <header><h2 id="library-title">Integration Libraries</h2><button autoFocus type="button" onClick={onClose} aria-label="Close Integration Libraries">×</button></header>
    <nav aria-label="Library actions">
      <button type="button" aria-pressed={mode === "install"} onClick={() => setMode("install")}>Use a library</button>
      <button type="button" aria-pressed={mode === "publish"} onClick={() => setMode("publish")}>Create a library</button>
      <button type="button" aria-pressed={mode === "export"} onClick={() => setMode("export")}>Export a library</button>
    </nav>
    <main>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {mode === "install" ? <>
        <h3>Installed in this project</h3>
        {pins.length === 0 && <p>Add a release from the catalog or import an .mlib file.</p>}
        {pins.length > 0 && <p>Use exported subtasks from Call Sub Task and map their public inputs and outputs.</p>}
        {pins.map(pin => <details key={pin.alias}>
          <summary>{pin.library.name} {pin.library.version} · {pin.alias}</summary>
          {categories.map(([category, label]) => {
            const assets = project[category].filter(item => item.library_origin?.alias === pin.alias && item.library_origin.public);
            return assets.length > 0 && <section key={category}><h4>{label}</h4><ul>{assets.map(item => <li key={item.id}>
              {item.name}
            </li>)}</ul></section>;
          })}
          <div className="library-actions"><button type="button" disabled={busy} onClick={() => void exportPin(pin)}>Export .mlib</button>
          <button type="button" disabled={busy} onClick={() => void perform(async () => {
            const updated = await post<P>("/remove", { project, alias: pin.alias });
            if (mounted.current) onChange(updated);
            setNotice(`${pin.library.name} removed from the project.`);
            setReview(undefined);
          })}>Remove from project</button></div>
        </details>)}
        <h3>Library catalog</h3>
        <label>Import .mlib file <input type="file" accept=".mlib" disabled={busy} onChange={event => {
          const file = event.target.files?.[0];
          if (file) void addRelease(file);
          event.target.value = "";
        }} /></label>
        <label>Library release <select value={selected} disabled={busy} onChange={event => {
          const entry = catalog.find(item => versionKey(item) === event.target.value);
          if (entry) selectRelease(entry);
          else setSelected("");
        }}><option value="">Select a library release</option>{catalog.map(entry =>
          <option key={versionKey(entry)} value={versionKey(entry)}>{entry.name} {entry.version}</option>
        )}</select></label>
        {release && <>
          {release.description && <p>{release.description}</p>}
          <label>Project alias <input value={alias} disabled={busy} onChange={event => { setAlias(event.target.value); setReview(undefined); }} /></label>
          {release.settings.length > 0 && <p>Set {release.settings.map(setting => `library.${alias}.${setting.key}`).join(", ")} in the project’s environment properties.</p>}
          {review && <div><h4>Version review</h4>{review.breakingChanges.length ? <ul>{review.breakingChanges.map(change => <li key={change}>{change}</li>)}</ul> : <p>The exported contracts match.</p>}
            {review.blockedBy && <p role="alert">{review.blockedBy} Update the reference in the project before applying this version.</p>}</div>}
          <div className="library-actions">
            <button type="button" className="primary" disabled={busy || !alias || Boolean(review?.blockedBy)} onClick={() => void attach()}>
              {review ? "Apply version change" : installed ? "Review version change" : "Add to project"}
            </button>
            <a href={downloadUrl(release)} download>Export .mlib</a>
          </div>
        </>}
        <details>
          <summary>Control Plane catalog</summary>
          <label>Control Plane URL <input type="url" value={controlPlaneUrl} disabled={busy} onChange={event => {
            setControlPlaneUrl(event.target.value); setRemoteReleases([]);
          }} /></label>
          <label>Credential <input type="password" autoComplete="off" value={credential} disabled={busy} onChange={event => { setCredential(event.target.value); setRemoteReleases([]); }} /></label>
          <label>Team ID <input value={teamId} disabled={busy} onChange={event => { setTeamId(event.target.value); setRemoteReleases([]); }} /></label>
          <div className="library-actions">
            <button type="button" disabled={busy || !controlPlaneUrl} onClick={() => void perform(async () => {
              setRemoteReleases(await post<RemoteRelease[]>("/control-plane/list", connection));
            })}>Load catalog</button>
            <button type="button" disabled={busy || !controlPlaneUrl || !release} onClick={() => void perform(async () => {
              if (!release) return;
              await post("/control-plane/publish", { ...connection, library_id: release.id, version: release.version, sha256: release.sha256 });
              setNotice(`${release.name} ${release.version} published to Control Plane.`);
            })}>Publish selected release</button>
          </div>
          {remoteReleases.map(entry => <div className="library-actions" key={`${entry.teamId}/${versionKey(entry)}`}>
            <span>{entry.name} {entry.version} · {entry.teamId}</span>
            <button type="button" disabled={busy} onClick={() => void perform(async () => {
              const item = await post<CatalogRelease>("/control-plane/install", {
                ...connection, teamId: entry.teamId, library_id: entry.id, version: entry.version, sha256: entry.sha256,
              });
              setCatalog(items => [...items.filter(previous => versionKey(previous) !== versionKey(item)), item]);
              selectRelease(item);
              setNotice("Library downloaded. Add it to the project to use it.");
            })}>Download to Studio</button>
          </div>)}
        </details>
      </> : mode === "export" ? <form onSubmit={event => {
        event.preventDefault();
        if (archivePin) void exportPin(archivePin);
        else if (archiveRelease) void downloadArchive(downloadUrl(archiveRelease), archiveRelease);
      }}>
        <label>Library release to export <select value={archiveSelection} disabled={busy} onChange={event => setArchiveSelection(event.target.value)}>
          <option value="">Select a library release</option>
          {pins.length > 0 && <optgroup label="Installed in this project">{pins.map(pin =>
            <option key={pin.alias} value={`pin:${pin.alias}`}>{pin.library.name} {pin.library.version} · {pin.alias}</option>
          )}</optgroup>}
          {catalog.length > 0 && <optgroup label="Library catalog">{catalog.map(entry =>
            <option key={versionKey(entry)} value={`catalog:${versionKey(entry)}`}>{entry.name} {entry.version}</option>
          )}</optgroup>}
        </select></label>
        <button type="submit" className="primary" disabled={busy || (!archivePin && !archiveRelease)}>Export .mlib</button>
      </form> : <form onSubmit={event => { event.preventDefault(); void publish(); }}>
        <label>Library name <input required value={name} onChange={event => {
          setName(event.target.value);
          setIdentity(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48));
        }} /></label>
        <label>Library ID <input required pattern="[a-z][a-z0-9\-]{0,47}" value={identity} onChange={event => setIdentity(event.target.value)} /></label>
        <label>Version <input required value={version} onChange={event => setVersion(event.target.value)} /></label>
        <label>Description <textarea value={description} onChange={event => setDescription(event.target.value)} /></label>
        {categories.map(([category, label]) => {
          const assets = project[category].filter(item => !item.library_origin && (category !== "tasks" || item.kind === "subtask"));
          return assets.length > 0 && <fieldset key={category}><legend>{label} to expose</legend>{assets.map(item => <label key={item.id}>
            <input type="checkbox" checked={exports[category].includes(item.id)} onChange={event => setExports(previous => ({
              ...previous, [category]: event.target.checked ? [...previous[category], item.id] : previous[category].filter(id => id !== item.id),
            }))} />{item.name}
          </label>)}</fieldset>;
        })}
        <div className="library-actions"><button className="primary" disabled={busy || !hasSelection}>Publish version</button>
          {published && <a href={downloadUrl(published)} download>Export {published.version} .mlib</a>}
        </div>
      </form>}
    </main>
    <footer><button type="button" onClick={onClose}>Close</button></footer>
  </section></ModalLayer>;
}
