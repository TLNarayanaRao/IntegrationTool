import {useState} from "react";
import ModalLayer from "./ModalLayer";
import "./integration-libraries.css";

type Review = {
  document: Record<string, unknown>;
  operations: {id: string; action: string; address?: string; messages: string[]}[];
};

export default function EventContracts({onClose, onDownload, onApply}: {
  onClose: () => void;
  onDownload: (blob: Blob, name: string) => void;
  onApply?: (configuration: {asyncApiDocument: string; operationId: string; messageName: string}) => void;
}) {
  const [document, setDocument] = useState("");
  const [result, setResult] = useState<Review>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [operationId, setOperationId] = useState("");
  const [messageName, setMessageName] = useState("");
  const operation = result?.operations.find(item => item.id === operationId);
  function change(value: string) {
    setDocument(value);
    setResult(undefined);
    setOperationId("");
    setMessageName("");
    setError("");
  }

  async function review() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/event-contracts/review", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({document}),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Contract could not be validated.");
      setResult(body);
      if (body.operations.length === 1) {
        setOperationId(body.operations[0].id);
        setMessageName(body.operations[0].messages.length === 1 ? body.operations[0].messages[0] : "");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Contract could not be validated.");
    } finally {
      setBusy(false);
    }
  }

  return <ModalLayer><section className="integration-libraries" role="dialog" aria-modal="true" aria-labelledby="event-contract-title"
    style={{gridTemplateRows: "auto minmax(0, 1fr) auto"}}>
    <header><h2 id="event-contract-title">Event Contracts</h2><button autoFocus type="button" aria-label="Close Event Contracts" onClick={onClose}>×</button></header>
    <main>
      <label>Import AsyncAPI JSON or YAML <input type="file" accept=".json,.yaml,.yml" disabled={busy}
        onChange={async event => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          if (file.size > 1048576) { setError("Choose a contract of up to 1 MiB."); return; }
          setBusy(true);
          try { change(await file.text()); }
          catch { setError("Unable to read the contract file."); }
          finally { setBusy(false); }
        }}/></label>
      <label>AsyncAPI document <textarea rows={10} value={document} disabled={busy}
        onChange={event => change(event.target.value)}/></label>
      {error && <p role="alert">{error}</p>}
      {result && <>
        <h3>Operations</h3>
        {result.operations.length ? <ul>{result.operations.map(item =>
          <li key={item.id}><b>{item.id}</b> · {item.action} · {item.address || "Channel without an address"}
            {item.messages.length > 0 && <div>{item.messages.join(", ")}</div>}</li>
        )}</ul> : <p>No operations declared.</p>}
        {onApply && result.operations.length > 0 && <>
          <label>Operation for validation <select value={operationId} onChange={event => {
            const selected = result.operations.find(item => item.id === event.target.value);
            setOperationId(event.target.value);
            setMessageName(selected?.messages.length === 1 ? selected.messages[0] : "");
          }}><option value="">Select an operation</option>{result.operations.map(item =>
            <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
          {operation && <label>Message <select value={messageName} onChange={event => setMessageName(event.target.value)}>
            <option value="">Select a message</option>{operation.messages.map(name => <option key={name}>{name}</option>)}
          </select></label>}
        </>}
      </>}
    </main>
    <footer>
      <button type="button" onClick={onClose}>Close</button>
      {result && <button type="button" onClick={() => onDownload(
        new Blob([JSON.stringify(result.document, null, 2)], {type: "application/json"}), "asyncapi.json"
      )}>Export AsyncAPI</button>}
      {onApply && result && operation && messageName && <button type="button" onClick={() => onApply({
        asyncApiDocument: JSON.stringify(result.document, null, 2), operationId, messageName,
      })}>Apply to selected activity</button>}
      <button type="button" className="primary" onClick={() => void review()} disabled={busy || !document.trim()}>Validate contract</button>
    </footer>
  </section></ModalLayer>;
}
