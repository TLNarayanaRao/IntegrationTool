import { useState } from "react";
import { HTTP_METHODS } from "./ActivityEditor";
import ModalLayer from "./ModalLayer";
import type { SchemaDoc } from "./SchemaStudio";
import EndpointSchemaPicker, { schemaChoiceName, schemaText, type SchemaChoice } from "./EndpointSchemaPicker";
import { HttpContentTypeCheckboxes } from "./HttpContentTypePicker";
import SharedConnectionSelect, { matchesConnection, type CreateConnection, type SharedConnection } from "./SharedConnectionSelect";
import "./http-endpoint-setup.css";

type EndpointDraft = {
  resourceId: string;
  path: string;
  methods: string[];
  requestContentTypes: string[];
  responseContentTypes: string[];
  request: SchemaChoice;
  response: SchemaChoice;
};
type Options = { resources: SharedConnection[]; schemas: SchemaDoc[]; createConnection: CreateConnection };
export type EndpointConfig = {
  resourceId: string;
  path: string;
  methods: string;
  requestContentTypes?: string[];
  responseContentTypes?: string[];
  requestSchema?: string;
  responseSchema?: string;
  requestSchemaName?: string;
  responseSchemaName?: string;
  validateRequest?: boolean;
  validateResponse?: boolean;
};

export function isHttpEndpoint(type: string, operation?: string) {
  return type === "http_listener" || (type === "rest" && operation === "receiver");
}

export function newEndpointDraft(): EndpointDraft {
  return {
    resourceId: "", path: "/events", methods: ["POST"], requestContentTypes: [], responseContentTypes: [],
    request: { source: "", text: "" }, response: { source: "", text: "" },
  };
}

export function endpointConfig(draft: EndpointDraft, { resources, schemas }: Pick<Options, "resources" | "schemas">): EndpointConfig {
  if (!resources.some(resource => resource.id === draft.resourceId && matchesConnection(resource, "http_server"))) {
    throw new Error("Select or create an HTTP server connection.");
  }
  const path = draft.path.trim();
  const parameters = [...path.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map(match => match[1]);
  if (!path.startsWith("/") || path.startsWith("//") || /[?#{}\s]/.test(path.replace(/\{[A-Za-z_][A-Za-z0-9_]*\}/g, "")) ||
      new Set(parameters).size !== parameters.length) {
    throw new Error("Enter a URI path such as /orders/{id}, with unique parameter names and no query or fragment.");
  }
  const methods = HTTP_METHODS.filter(method => draft.methods.includes(method));
  if (!methods.length) throw new Error("Select at least one HTTP method.");
  const requestSchema = schemaText(draft.request, schemas, "Request");
  const responseSchema = schemaText(draft.response, schemas, "Response");
  return {
    resourceId: draft.resourceId, path, methods: methods.join(","),
    ...(draft.requestContentTypes.length && { requestContentTypes: [...draft.requestContentTypes] }),
    ...(draft.responseContentTypes.length && { responseContentTypes: [...draft.responseContentTypes] }),
    ...(requestSchema !== undefined && { requestSchema, requestSchemaName: schemaChoiceName(draft.request, schemas), validateRequest: true }),
    ...(responseSchema !== undefined && { responseSchema, responseSchemaName: schemaChoiceName(draft.response, schemas), validateResponse: true }),
  };
}

export function HttpEndpointFields({ draft, onChange, resources, schemas, createConnection }: Options & {
  draft: EndpointDraft; onChange: (draft: EndpointDraft) => void;
}) {
  return (
    <section className="endpoint-setup-fields" aria-label="Endpoint settings">
      <label>HTTP server connection
        <SharedConnectionSelect value={draft.resourceId} resources={resources} kinds={["http_server"]}
          onChange={resourceId => onChange({ ...draft, resourceId })} onCreate={createConnection}/>
      </label>
      <label>URI path
        <input value={draft.path} placeholder="/orders/{id}" onChange={event => onChange({ ...draft, path: event.target.value })}/>
      </label>
      <fieldset>
        <legend>Allowed HTTP methods</legend>
        <div className="endpoint-methods">
          {HTTP_METHODS.map(method => <label key={method}>
            <input type="checkbox" checked={draft.methods.includes(method)} onChange={event => onChange({
              ...draft,
              methods: event.target.checked ? [...draft.methods, method] : draft.methods.filter(value => value !== method),
            })}/>
            {method}
          </label>)}
        </div>
      </fieldset>
      <div className="endpoint-media-types">
        <HttpContentTypeCheckboxes label="Request content types" value={draft.requestContentTypes}
          onChange={requestContentTypes => onChange({ ...draft, requestContentTypes })}/>
        <HttpContentTypeCheckboxes label="Response content types" value={draft.responseContentTypes} response
          onChange={responseContentTypes => onChange({ ...draft, responseContentTypes })}/>
      </div>
      <EndpointSchemaPicker label="Request" value={draft.request} schemas={schemas} onChange={request => onChange({ ...draft, request })}/>
      <EndpointSchemaPicker label="Response" value={draft.response} schemas={schemas} onChange={response => onChange({ ...draft, response })}/>
      <p>Optional schemas describe and validate the incoming request body and the response your workflow returns. Selecting a project schema copies its current definition into this endpoint.</p>
      <p>When you select several formats, an XSD applies to XML and a JSON Schema applies to JSON. Use an OpenAPI contract to define a separate schema for each format.</p>
    </section>
  );
}

export default function HttpEndpointSetup({ label, onClose, onCreate, connectionOpen, ...options }: Options & {
  label: string; onClose: () => void; onCreate: (config: EndpointConfig) => void; connectionOpen: boolean;
}) {
  const [draft, setDraft] = useState(newEndpointDraft);
  const [error, setError] = useState("");
  const create = () => {
    let config;
    try { config = endpointConfig(draft, options); }
    catch (error) { setError((error as Error).message); return; }
    onCreate(config);
  };
  return (
    <ModalLayer>
      <div className="runtime-modal endpoint-setup-dialog" role="dialog" aria-modal="true" aria-labelledby="endpoint-setup-title" inert={connectionOpen}>
        <header><b id="endpoint-setup-title">Set up {label}</b><button aria-label="Close endpoint setup" onClick={onClose}>×</button></header>
        <main>
          <HttpEndpointFields {...options} draft={draft} onChange={value => { setDraft(value); setError(""); }}/>
          {error && <p className="endpoint-setup-error" role="alert">{error}</p>}
        </main>
        <footer><button onClick={onClose}>Cancel</button><button className="primary" onClick={create}>Create activity</button></footer>
      </div>
    </ModalLayer>
  );
}
