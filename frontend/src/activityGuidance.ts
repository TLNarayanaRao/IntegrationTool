// Activity explanations displayed only in Documentation.
export const activityGuidance: Record<string, string[]> = {
  "MappingContextMenu": [
    "For Each wraps a target element and its child mappings in an expandable statement. For Each Group adds a Grouping row; enter a child path relative to each source item, such as ProductName. Edit the collection on the loop row and map fields on the target rows beneath it.",
    "Duplicate a repeating transformer loop to create another complete, independently editable target tree. Both occurrences contribute to the same repeating output target. In shared activity Input mappings, ${vars.current} is the current item and ${vars.currentGroup} contains the current group's items.",
    "Mapping statement",
    "Branches appear under the target field, followed by Otherwise. The first matching When wins.",
    "Iterate a repeating source value",
    "Group repeated values before mapping",
    "Create conditional branches on this field",
    "Select or drag an actual source sequence; the mapper no longer substitutes the ambiguous ${last} expression.",
    "Remove the target expression",
    "Required schema fields cannot be conditional",
    "Emit this target only when true",
    "Create another target occurrence with its complete child mapping tree",
    "Create an independently editable statement"
  ],
  "ActivityEditor": [
    "Operation settings and shared resources"
  ],
  "CallTaskRoutingEditor": [
    "Resolved at runtime for every call; the selected Sub Task supplies the fallback contract.",
    "Accepts a literal Sub Task ID/name, an environment property, task input, process variable, or previous activity output.",
    "The expression is resolved using the active design-time or runtime environment."
  ],
  "CatchAIEditor": [
    "Declared exceptions from every activity in the current Task are available below.",
    "Generate Catch → Throw handler block"
  ],
  "SchedulerEditor": [
    "Choose one deterministic schedule mode for this Starter Task.",
    "Uses the selected time zone.",
    "Five fields: minute, hour, day-of-month, month, day-of-week. Supports *, values, ranges, lists, and */step.",
    "Executes immediately during local testing without waiting for the scheduled instant. Production packaging still honors the configured schedule."
  ],
  "DataWeaveScriptEditor": [
    "Executable DataWeave 2.0-compatible integration language",
    "Embedded engine: Nested & wildcard selectors; Objects & arrays; default / if-else; Custom functions; as type coercion; map / flatMap / filter; mapObject / pluck; groupBy / orderBy / distinctBy; read / write; JSON / XML / CSV / text.",
    "Common integration transformations execute locally in Run, Debug, and Test. Namespaces, type declarations, pattern matching, annotations, and Mule runtime-only modules are rejected explicitly."
  ],
  "DataWeaveTestEditor": [
    "Execute representative payload data before running the Task."
  ],
  "TransformSchemaEditor": [
    "Select an XSD from Project Schemas or define the target structure inline.",
    "Inline JSON Schema, sample JSON, or XSD",
    "Project XSD with an editable working copy"
  ],
  "TransformPoliciesEditor": [
    "Executable output, compatibility, validation, and failure behavior",
    "0 means unlimited; execution fails before publishing an oversized result.",
    "Reject output that violates the configured JSON schema.",
    "Remove surrounding whitespace after functions are applied.",
    "Prune null, empty objects, arrays, and strings from the final result.",
    "Preserve explicit source null values when the null policy allows them.",
    "Suggestions never overwrite manually approved rules.",
    "Keep recommended mappings pending until reviewed.",
    "Recommend For-Each for compatible source and target cardinality."
  ],
  "TaskBoundarySchemaEditor": [
    "Select a project schema or define an inline JSON Schema/XSD contract.",
    "Defines the data accepted by this task and published by Start.",
    "Defines the response mapped into End and returned to Call Sub Task."
  ],
  "DataContractSchemaEditor": [
    "Choose a project XSD/JSON schema or provide an inline definition.",
    "Define the tree to map before serialization.",
    "Define the tree published after parsing."
  ],
  "JdbcDesigner": [
    "Prepared SQL editor · parameters become typed Input fields automatically.",
    "Use :parameterName for safe dynamic values.",
    "Map values in Input → parameters; choose the database datatype here."
  ],
  "MappingBinding": [
    "Value for this field"
  ],
  "ExpandedInputMappingDialog": [
    "Map execution data, functions, properties, and typed constants to the desired target fields."
  ],
  "InputEditor": [
    "Map simple schema elements and attributes. Complex structures are controlled exclusively through their child fields.",
    "Open expanded editor",
    "Schema-typed hierarchical input · constants are validated against each simple field type"
  ],
  "TransformInputEditor": [
    "Drop a repeating complex source to create its For-Each statement and matching child mappings. Use Duplicate occurrence for additional target copies.",
    "Open expanded editor"
  ],
  "TransformOutputEditor": [
    "Published target schema available to downstream activities"
  ],
  "TransformMapTestEditor": [
    "Execute the exact mappings, constants, conditions, grouping rules, and formulas configured in the Input tab.",
    "JSON matching the upstream/source structure",
    "Saved design-time rules executed in order",
    "Target structure produced by the mapper"
  ],
  "OutputEditor": [
    "Published values available to downstream activity mappings"
  ],
  "AdvancedEditor": [
    "Inherited automatically by every activity type",
    "Activity policy tree",
    "Logs activity input and output without placing a Log activity on the canvas.",
    "Configure Log Payload from the active environment",
    "Defaults to advanced.logPayload; browse to select another environment property.",
    "Applied when this activity calls its target system.",
    "Boolean or global property expression",
    "Default: 3 retry attempts",
    "Default: 60 seconds",
    "The active environment is resolved once for the complete project, including every Task, Sub Task, activity, and shared connection.",
    "property group"
  ],
  "ErrorEditor": [
    "Operation-declared faults plus runtime handling",
    "Outbound retry is configured consistently for all connectors on the Advanced tab."
  ],

};
