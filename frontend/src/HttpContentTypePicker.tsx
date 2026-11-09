import { useState } from "react";
import "./http-endpoint-setup.css";

const mediaTypes = [
  "application/json",
  "application/xml",
  "text/xml",
  "text/plain",
  "text/html",
  "text/csv",
  "application/x-www-form-urlencoded",
  "multipart/form-data",
  "application/octet-stream",
  "application/pdf",
];
const customOption = "@custom";
const mappedOption = "@mapped";

export function savedContentTypes(value: unknown, legacy?: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && !!item.trim())
    : typeof legacy === "string" && legacy.trim() ? [legacy.trim()] : [];
}

export function HttpContentTypeCheckboxes({ label, value, onChange, response = false }: {
  label: string; value: string[]; onChange: (value: string[]) => void; response?: boolean;
}) {
  const [custom, setCustom] = useState("");
  const [error, setError] = useState("");
  const add = () => {
    const type = custom.trim().toLowerCase();
    if (!/^[a-z0-9!#$%&'+.^_`|~-]+\/[a-z0-9!#$%&'+.^_`|~-]+$/.test(type)) {
      setError("Enter a media type such as application/vnd.example+json."); return;
    }
    if (!value.some(item => item.toLowerCase() === type)) onChange([...value, type]);
    setCustom(""); setError("");
  };
  return <fieldset className="endpoint-media-checkboxes">
    <legend>{label}</legend>
    <div className="endpoint-media-options">
      {[...mediaTypes, ...value.filter(type => !mediaTypes.includes(type))].map(type => <label key={type}>
        <input type="checkbox" checked={value.includes(type)} onChange={event => onChange(
          event.target.checked ? [...value, type] : value.filter(item => item !== type))}/>
        <span>{type}</span>
      </label>)}
    </div>
    <label>Custom type
      <input value={custom} onChange={event => { setCustom(event.target.value); setError(""); }}
        onKeyDown={event => { if (event.key === "Enter" && custom.trim()) { event.preventDefault(); add(); } }}
        placeholder="application/vnd.example+json" spellCheck={false}/>
    </label>
    <button type="button" onClick={add} disabled={!custom.trim()}>Add custom type</button>
    {error && <p role="alert" className="endpoint-setup-error">{error}</p>}
    <small>{!value.length ? "Automatic when none are selected." : response && value.length > 1
      ? `Default: ${value[0]}. Clients can request another selected type with Accept.` : ""}</small>
  </fieldset>;
}

export default function HttpContentTypePicker({ label, value, onChange, mapped = false }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mapped?: boolean;
}) {
  const [editingCustom, setEditingCustom] = useState(false);
  const isCustom = editingCustom || (value !== "" && !mediaTypes.includes(value));

  return (
    <div className="endpoint-media-type-picker">
      <label>{label}
        <select value={isCustom ? customOption : mapped ? mappedOption : value} onChange={event => {
          const selected = event.target.value;
          setEditingCustom(selected === customOption);
          if (selected !== customOption) onChange(selected);
        }}>
          <option value="">Automatic</option>
          {mapped && <option value={mappedOption} disabled>Mapped value</option>}
          {mediaTypes.map(type => <option key={type} value={type}>{type}</option>)}
          <option value={customOption}>Custom…</option>
        </select>
      </label>
      {isCustom && <label>Custom {label.toLowerCase()}
        <input value={value} onChange={event => onChange(event.target.value)}
          placeholder="application/vnd.example+json" spellCheck={false}/>
      </label>}
    </div>
  );
}
