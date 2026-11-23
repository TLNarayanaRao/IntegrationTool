import type { Dispatch, SetStateAction } from "react";
import type { SubtaskInputReport } from "./executionSetup";
import { exampleFieldValue, inputControl, readSubtaskInput, selectedSubtaskFile, type FileInputMethod, type InputField, type InputMethod, type SubtaskInputDraft } from "./subtaskInput";

export default function SubtaskInputEditor({ report, fields, draft, update, loadFile, disabled, onError, validate, validationDisabled }: {
  report: SubtaskInputReport;
  fields: InputField[];
  draft: SubtaskInputDraft;
  update: Dispatch<SetStateAction<SubtaskInputDraft>>;
  loadFile: (file: File, method: FileInputMethod) => void;
  disabled: boolean;
  onError: (message: string) => void;
  validate: () => void;
  validationDisabled: boolean;
}) {
  const setValue = (field: InputField, value?: string) => update(current => {
    const values = {...current.values};
    if (value === undefined) delete values[field.key];
    else values[field.key] = value;
    return {...current, values};
  });
  const editAsJson = () => {
    try {
      const input = readSubtaskInput(draft, fields);
      update(current => ({...current, method:"json", json: JSON.stringify(input, null, 2)}));
    } catch (problem) {
      onError(problem instanceof Error ? problem.message : String(problem));
    }
  };
  const file = selectedSubtaskFile(draft);
  const isXmlFile = draft.method === "xml-file";
  const fileLabel = isXmlFile ? "XML" : "JSON";
  const loadingFile = !!file && file.text === undefined && !file.error;
  return <section className="subtask-input-editor" aria-label="Subtask input">
    <label>Input source<select disabled={disabled} value={draft.method} onChange={event => {
      const method = event.target.value as InputMethod;
      update(current => ({...current, method}));
    }}>
      {!!fields.length && <option value="form">Start fields</option>}
      <option value="json">Paste or edit JSON</option>
      <option value="file">Load JSON file</option>
      {report.format === "xsd" && <><option value="xml">Paste or edit XML</option><option value="xml-file">Load XML file</option></>}
      <option value="empty">No input</option>
    </select></label>
    {draft.method === "form" && <>
      <p>Untouched fields are omitted. Use Omit to remove a value you entered. Use JSON input for a field outside this list.</p>
      <div className="subtask-input-fields">{fields.map(field => {
        const kind = inputControl(field.type);
        const value = draft.values[field.key];
        return <div key={field.key} className="subtask-input-field"><label>
          <span>{field.label}<small>{field.type}{field.required ? " · required" : ""}</small></span>
          {kind === "boolean" ? <select disabled={disabled} value={value ?? ""} onChange={event => setValue(field, event.target.value || undefined)}>
            <option value="">Omit</option><option value="true">True</option><option value="false">False</option>
          </select> : kind === "json" ? <textarea disabled={disabled} rows={2} value={value ?? ""} spellCheck={false}
            onChange={event => setValue(field, event.target.value || undefined)}/>
          : <input disabled={disabled} inputMode={kind === "number" ? "decimal" : undefined} value={value ?? ""}
            onChange={event => setValue(field, kind === "number" ? event.target.value || undefined : event.target.value)}/>}
        </label>
        {value !== undefined && <button type="button" disabled={disabled} aria-label={`Omit ${field.label}`} onClick={() => setValue(field)}>Omit</button>}
        </div>;
      })}</div>
      <div className="execution-setup-actions">
        <button type="button" disabled={disabled} onClick={() => update(current => ({
          ...current, values:Object.fromEntries(fields.map(field => [field.key, exampleFieldValue(field)])),
        }))}>Fill example</button>
        <button type="button" disabled={disabled} onClick={() => update(current => ({...current, values:{}}))}>Clear fields</button>
        <button type="button" disabled={disabled} onClick={editAsJson}>Edit as JSON</button>
      </div>
    </>}
    {draft.method === "json" && <>
      <label>Subtask input JSON<textarea disabled={disabled} value={draft.json} onChange={event => {
        const json = event.target.value;
        update(current => ({...current, json}));
      }} spellCheck={false}/></label>
      <div className="execution-setup-actions">
        <button type="button" disabled={disabled} onClick={editAsJson}>Format JSON</button>
        {report.example !== undefined && report.format !== "none" && <button type="button" disabled={disabled}
          onClick={() => update(current => ({...current, json:JSON.stringify(report.example, null, 2)}))}>Insert example</button>}
        <button type="button" disabled={disabled} onClick={() => update(current => ({...current, json:"{}"}))}>Reset JSON</button>
      </div>
    </>}
    {draft.method === "xml" && <label>Subtask input XML<textarea value={draft.xml ?? ""} disabled={disabled} spellCheck={false}
      onChange={event => { const xml = event.target.value; update(current => ({...current, xml})); }}/></label>}
    {(draft.method === "xml" || isXmlFile) && report.root && <p>Expected XML root <code>{report.root}</code></p>}
    {(draft.method === "file" || isXmlFile) && <>
      <label>Choose {fileLabel} file<input type="file" accept={isXmlFile ? ".xml,application/xml,text/xml" : ".json,application/json"} disabled={disabled} onChange={event => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        if (file) loadFile(file, isXmlFile ? "xml-file" : "file");
      }}/></label>
      {loadingFile && <p role="status">Reading {file?.name}…</p>}
      {file?.error && <p role="alert">{file.error}</p>}
      {file?.text !== undefined && <>
        <label>{file.name}<textarea readOnly spellCheck={false} value={file.text} aria-label={`${fileLabel} file contents`}/></label>
        <button type="button" disabled={disabled} onClick={() => update(current => isXmlFile
          ? {...current, method:"xml", xml:file.text}
          : {...current, method:"json", json:file.text ?? "{}"})}>Edit as {fileLabel}</button>
      </>}
    </>}
    {draft.method === "empty" && <p>The Subtask starts with an empty object if its Start schema allows it.</p>}
    <div className="execution-setup-actions"><button type="button" disabled={validationDisabled} onClick={validate}>Validate input</button></div>
  </section>;
}
