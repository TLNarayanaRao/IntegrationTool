export const supportsOutboundRetry = (type = "", operation = "") =>
  ["http", "jdbc", "snowflake", "ftp", "sftp"].includes(type) ||
  (type === "amqp" && ["send", "get", "dead_letter"].includes(operation)) ||
  (type === "ems" && ["send", "publish", "request_reply", "reply"].includes(operation)) ||
  (type === "jms" && ["send_message", "get_queue_message", "request_reply", "reply_message"].includes(operation)) ||
  (type === "kafka" && ["send", "publish", "get"].includes(operation)) ||
  (type === "pubsub" && operation === "publish") ||
  (type === "rest" && operation === "invoke") ||
  (type === "soap" && operation === "request_reply") ||
  (type === "sap" && ["idoc_acknowledgment", "idoc_confirmation", "post_idoc", "invoke_rfc_bapi", "reply_rfc_bapi", "read_table"].includes(operation));

export const supportsActivityCircuit = (type = "", operation = "") =>
  supportsOutboundRetry(type, operation) && !["http", "rest", "soap"].includes(type) &&
  !["dead_letter", "idoc_acknowledgment", "idoc_confirmation", "reply_rfc_bapi", "reply", "reply_message"].includes(operation);

export const activityCircuitDefaults = {
  circuitEnabled: false,
  circuitFailureThreshold: 5,
  circuitCooldownSeconds: 30,
  circuitFaultTypes: "",
};

export const activityCircuitErrors = [
  {type: "CircuitOpen", description: "The activity skipped its connector call while the circuit was open or a recovery probe was running."},
  {type: "CircuitBreakerCapacity", description: "The runtime has reached the activity circuit state limit."},
];
