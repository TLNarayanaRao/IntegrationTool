export type RequestParameter = {
  in: "path" | "query" | "header";
  name: string;
  type: "string" | "integer" | "number" | "boolean";
  required: boolean;
};

export function validateRequestParameters(parameters: RequestParameter[], path: string) {
  const pathNames = new Set([...path.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map(match => match[1]));
  const seen = new Set<string>();
  for (const parameter of parameters) {
    const name = parameter.name.trim();
    if (parameter.in === "path" ? !pathNames.has(name) : !/^[A-Za-z0-9_-]+$/.test(name)) {
      return parameter.in === "path"
        ? "Choose a URI parameter already present in the path, such as {id}."
        : "Enter a parameter name using letters, numbers, underscores or hyphens.";
    }
    const key = parameter.in + ":" + (parameter.in === "header" ? name.toLowerCase() : name);
    if (seen.has(key)) return `Declare ${name} only once per location.`;
    if (["header:accept", "header:content-type", "header:authorization"].includes(key)) {
      return `Configure ${name} through media types or authentication.`;
    }
    seen.add(key);
  }
  return "";
}

export default function HttpRequestParameters({ value, path, onChange }: {
  value: RequestParameter[];
  path: string;
  onChange: (value: RequestParameter[]) => void;
}) {
  const pathNames = [...new Set([...path.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map(match => match[1]))];
  const update = (index: number, patch: Partial<RequestParameter>) =>
    onChange(value.map((parameter, i) => i === index ? { ...parameter, ...patch } : parameter));
  const error = validateRequestParameters(value, path);
  return <fieldset className="http-request-parameters">
    <legend>Request parameters</legend>
    <p>Add URI parameters to the path as <code>{"{name}"}</code>. Declare them here to set their types, or add query parameters and custom headers.</p>
    {value.map((parameter, index) => <div className="http-request-parameter" key={index}>
      <select aria-label={`Parameter ${index + 1} location`} value={parameter.in} onChange={event => {
        const location = event.target.value as RequestParameter["in"];
        update(index, { in: location, name: location === "path" ? pathNames[0] || "" : "", required: location === "path" });
      }}>
        <option value="path">URI path</option>
        <option value="query">Query</option>
        <option value="header">Custom header</option>
      </select>
      {parameter.in === "path" ?
        <select aria-label={`Parameter ${index + 1} name`} value={parameter.name} onChange={event => update(index, {name: event.target.value})}>
          <option value="">Choose URI parameter</option>
          {pathNames.map(name => <option key={name}>{name}</option>)}
        </select> :
        <input aria-label={`Parameter ${index + 1} name`} placeholder={parameter.in === "header" ? "X-Request-ID" : "limit"}
          value={parameter.name} onChange={event => update(index, {name: event.target.value})}/>}
      <select aria-label={`Parameter ${index + 1} type`} value={parameter.type}
        onChange={event => update(index, {type: event.target.value as RequestParameter["type"]})}>
        {["string", "integer", "number", "boolean"].map(type => <option key={type}>{type}</option>)}
      </select>
      <label><input type="checkbox" checked={parameter.in === "path" || parameter.required} disabled={parameter.in === "path"}
        onChange={event => update(index, {required: event.target.checked})}/>Required</label>
      <button type="button" aria-label={`Remove parameter ${index + 1}`} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove</button>
    </div>)}
    <button type="button" onClick={() => onChange([...value, {in: "query", name: "", type: "string", required: false}])}>Add parameter</button>
    {error && <p role="alert">{error}</p>}
  </fieldset>;
}
