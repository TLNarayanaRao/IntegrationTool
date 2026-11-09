type EntryActivity = {
  type: string;
  operation?: string;
  config?: { operation?: string };
};

export const isEventActivity = (item: EntryActivity) => {
  const operation = item.operation || item.config?.operation || "";
  return item.type === "start" || item.type === "timer" || item.type === "http_listener" ||
    (item.type === "rest" && operation === "receiver") || (item.type === "soap" && operation === "service") ||
    (item.type === "file" && operation === "poll") ||
    (item.type === "ems" && ["queue_receiver", "topic_subscriber"].includes(operation)) ||
    (item.type === "jms" && operation === "receive_message") ||
    (item.type === "kafka" && ["receive", "get"].includes(operation)) ||
    (item.type === "pubsub" && operation === "subscribe") ||
    (item.type === "amqp" && operation === "receive") ||
    (item.type === "sap" && ["idoc_listener", "rfc_bapi_listener"].includes(operation));
};

export const taskEntryLabels = {
  starter: "Starter",
  subtask: "Subtask",
  unconfigured: "No start",
} as const;

export function taskEntryMode(task: {
  kind: string;
  activities: (EntryActivity & { id: string })[];
  transitions?: { target: string }[];
}): keyof typeof taskEntryLabels {
  if (task.kind === "subtask") return "subtask";
  // Match the runtime's entry selection: receivers with incoming edges are ordinary activities.
  const incoming = new Set(task.transitions?.map(transition => transition.target));
  const entries = task.activities.filter(activity => !incoming.has(activity.id));
  if (entries.some(activity => activity.type !== "start" && isEventActivity(activity))) return "starter";
  return entries.some(activity => activity.type === "start") ? "subtask" : "unconfigured";
}
