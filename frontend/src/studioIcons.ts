import { activityIconUrl } from "./activityIconUrl";

type ActivityIconDefinition = { type: string; operation?: string; asset: string };
type IconActivity = { type: string; operation?: string; config?: { operation?: string } };

// Imported legacy mapper types have the same meaning and artwork as Mapper.
export function activityIconAsset(activity: IconActivity, catalog: ReadonlyMap<string, readonly ActivityIconDefinition[]>): string {
  const type = ["transform", "ai_transform"].includes(activity.type) ? "mapper" : activity.type;
  const definitions = catalog.get(type);
  const operation = activity.operation || activity.config?.operation;
  return (definitions?.find(item => item.operation === operation) || definitions?.[0])?.asset || "activity.svg";
}

const connectionIcons: Record<string, string> = {
  http: "http.png", ftp: "ftp.png", sftp: "sftp.png", ems: "ems.png",
  jms: "jms-connection.svg", jdbc: "JDBC-Query.png", snowflake: "snowflake.svg",
};
const vendorIcons: Record<string, string> = {
  kafka: "apache-kafka.svg", pubsub: "gcp-pubsub.png", amqp: "rabbitmq.svg",
  sap: "sap.svg", sap_tid: "sap.svg",
};

// Shared by the connection creation menu and Project Explorer. Bundled SVGs
// use content-based URLs, so an older public copy cannot mask a new drawing.
export function connectionIconUrl(type: string): string | undefined {
  const key = ["http_client", "http_server"].includes(type) ? "http" : type;
  if (vendorIcons[key]) return `/vendor-logos/${vendorIcons[key]}`;
  return connectionIcons[key] ? activityIconUrl(connectionIcons[key]) : undefined;
}
