export type SharedConnection = {
  id: string;
  type: "jdbc" | "snowflake" | "amqp" | "ftp" | "sftp" | "http" | "ems" | "jms" | "kafka" | "pubsub" | "sap" | "sap_tid";
  name: string;
  package_path?: string;
  config: Record<string, any>;
};

export type ConnectionKind = SharedConnection["type"] | "http_client" | "http_server";
export type CreateConnection = (kind: ConnectionKind, select: (resource: SharedConnection) => void) => void;
const createPrefix = "create-connection:";

type Props = {
  value: string;
  resources: SharedConnection[];
  kinds: ConnectionKind[];
  onChange: (id: string, resource?: SharedConnection) => void;
  onCreate?: CreateConnection;
};

export function matchesConnection(resource: SharedConnection, kind: ConnectionKind) {
  if (kind === "http_server") return resource.type === "http" && resource.config?.connectorMode !== "client";
  if (kind === "http_client") return resource.type === "http" && resource.config?.connectorMode !== "server";
  return resource.type === kind;
}

export default function SharedConnectionSelect({ value, resources, kinds, onChange, onCreate }: Props) {
  const options = resources.filter(resource => resource.id === value || kinds.some(kind => matchesConnection(resource, kind)));
  return (
    <select value={value} onChange={event => {
      const selected = event.target.value;
      const kind = kinds.find(kind => selected === createPrefix + kind);
      if (kind && onCreate) {
        // The create command must never become the selected connection.
        event.target.value = value;
        onCreate(kind, resource => onChange(resource.id, resource));
      } else {
        onChange(selected);
      }
    }}>
      <option value="">Select shared connection…</option>
      {value && !options.some(resource => resource.id === value) && <option value={value}>Missing connection ({value})</option>}
      {options.map(resource => <option key={resource.id} value={resource.id}>{resource.name}</option>)}
      {onCreate && kinds.map(kind => (
        <option key={kind} value={createPrefix + kind}>
          {kinds.length === 1 ? "+ Create new connection…" : `+ Create ${kind.toUpperCase()} connection…`}
        </option>
      ))}
    </select>
  );
}
