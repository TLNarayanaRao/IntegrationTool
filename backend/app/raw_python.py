"""Export a deliberately independent, executable Python application.

This compiler does not serialize the Fabric project model into Python.  Each
task becomes an async state machine and uses only the small generated Python
support library.  Unsupported activity semantics are rejected at build time.
"""
from __future__ import annotations

import ast
import keyword
import re
from pathlib import Path
from pprint import pformat


SUPPORTED = {
    ('start', ''), ('end', ''), ('log', ''), ('mapper', ''), ('confirm', 'acknowledge'),
    ('call_task', ''), ('catch', ''), ('throw', ''), ('rethrow', ''),
    ('basic', 'empty'), ('basic', 'assign'), ('basic', 'sleep'), ('basic', 'checkpoint'),
    ('basic', 'get_shared_variable'), ('basic', 'set_shared_variable'), ('basic', 'external_command'),
    *((('file', operation) for operation in ('read', 'write', 'list', 'delete', 'rename', 'copy', 'poll'))),
    *((('ftp', operation) for operation in ('get', 'put', 'delete', 'dir', 'change_dir'))),
    *((('sftp', operation) for operation in ('get', 'put', 'delete', 'dir', 'change_dir'))),
    ('http_listener', 'listen'), ('http', 'request'), ('rest', 'receiver'), ('rest', 'invoke'),
    ('soap', 'service'), ('soap', 'request_reply'), ('http_response', 'response'),
    ('xml', 'parse'), ('xml', 'render'), ('json', 'parse'), ('json', 'render'),
    ('flat', 'parse'), ('flat', 'render'), ('excel', 'read'), ('dataweave', 'transform'),
    ('python', 'invoke'), ('java', 'invoke'),
    *((('snowflake', operation) for operation in ('insert', 'query', 'update', 'delete', 'bulk_load'))),
    *((('amqp', operation) for operation in ('send', 'get', 'receive', 'dead_letter'))),
    ('kafka', 'publish'), ('kafka', 'send'), ('kafka', 'receive'), ('kafka', 'get'),
    ('pubsub', 'publish'), ('pubsub', 'pull'), ('pubsub', 'subscribe'),
    ('ems', 'send'), ('ems', 'publish'), ('ems', 'queue_receiver'), ('ems', 'topic_subscriber'), ('ems', 'request_reply'), ('ems', 'reply'),
    ('jms', 'send_message'), ('jms', 'receive_message'), ('jms', 'get_queue_message'), ('jms', 'request_reply'), ('jms', 'reply_message'), ('jms', 'wait_request'),
    ('sap', 'dynamic_connection'), ('sap', 'idoc_acknowledgment'), ('sap', 'idoc_confirmation'),
    ('sap', 'idoc_converter'), ('sap', 'idoc_parser'), ('sap', 'idoc_reader'),
    ('sap', 'post_idoc'), ('sap', 'idoc_renderer'), ('sap', 'invoke_rfc_bapi'),
    ('sap', 'read_table'),
    ('sap', 'idoc_listener'), ('sap', 'rfc_bapi_listener'), ('sap', 'reply_rfc_bapi'),
    ('timer', 'schedule'),
    *((('jdbc', operation) for operation in ('insert', 'update', 'query', 'truncate', 'delete', 'call', 'dynamic'))),
}
STRUCTURAL = {'start', 'end', 'log', 'mapper', 'call_task', 'catch', 'throw', 'rethrow'}
STRUCTURAL_ONLY = {'start', 'end', 'catch'}
SUPPORTED_GROUP_TYPES = {'if', 'for_each', 'iterate', 'while', 'repeat', 'repeat_on_error',
                         'critical_section', 'transaction_jdbc'}
ACTIVITY_CAPABILITY_BY_KIND = {
    'timer': 'timer', 'confirm': 'confirm', 'throw': 'faults', 'rethrow': 'faults',
    'log': 'log', 'basic': 'basic', 'mapper': 'mapper', 'call_task': 'call_task',
    'file': 'file', 'excel': 'excel', 'ftp': 'transfer', 'sftp': 'transfer',
    'http_response': 'http_response', 'dataweave': 'dataweave', 'python': 'python',
    'java': 'java', 'kafka': 'kafka', 'pubsub': 'pubsub', 'sap': 'sap',
    'ems': 'jms', 'jms': 'jms', 'jdbc': 'jdbc', 'snowflake': 'snowflake', 'amqp': 'amqp',
}
EVENT_OPERATIONS = {('kafka', 'receive'), ('kafka', 'get'), ('pubsub', 'pull'), ('pubsub', 'subscribe'), ('ems', 'queue_receiver'),
                    ('ems', 'topic_subscriber'), ('jms', 'receive_message'), ('sap', 'idoc_listener'), ('sap', 'rfc_bapi_listener'), ('timer', 'schedule')}
EVENT_OPERATIONS.update({('http_listener', 'listen'), ('rest', 'receiver'), ('soap', 'service'), ('jms', 'wait_request')})


def _activity_capabilities(kind: str, operation: str) -> set[str] | None:
    """Resolve one persisted activity model to linker capabilities.

    ``None`` deliberately means that the compiler registry has no linker rule;
    an empty set is a valid rule for structural nodes that need no optional
    implementation.  This distinction prevents newly added Studio activities
    from being silently omitted by the exporter.
    """
    if kind in STRUCTURAL_ONLY:
        return set()
    if kind in {'xml', 'json', 'flat'}:
        return {'data_formats'}
    if kind == 'http_listener' or kind == 'rest' and operation == 'receiver' or kind == 'soap' and operation == 'service':
        return {'inbound_http'}
    if kind in {'http', 'rest', 'soap'}:
        return {'http_client'}
    capability = ACTIVITY_CAPABILITY_BY_KIND.get(kind)
    return {capability} if capability else None


def _validate_capability_registry() -> None:
    """Require linker metadata for every operation the exporter advertises."""
    missing = sorted(f'{kind}/{operation or "default"}' for kind, operation in SUPPORTED
                     if _activity_capabilities(kind, operation) is None)
    if missing:
        raise RuntimeError('Raw Python capability registry is incomplete: ' + ', '.join(missing))


def _edge_type(edge: dict) -> str:
    """Normalize transitions saved by older Studio builds.

    Older project files commonly persisted an ordinary transition as either a
    missing field, an empty string, or JSON null.  They all mean ``success``.
    """
    return str(edge.get('type') or 'success')


def _project_capabilities(project: dict) -> set[str]:
    """Compute the executable capability closure for the selected task graph."""
    capabilities = {'structural'}
    for task in project.get('tasks', []):
        for activity in task.get('activities', []):
            kind = str(activity.get('type') or '')
            operation = str(activity.get('config', {}).get('operation') or '')
            if kind not in {'start', 'end', 'catch'}:
                capabilities.add(f'activity:{kind}/{operation or "default"}')
            linked = _activity_capabilities(kind, operation)
            if linked is None:
                raise RuntimeError(f'Raw Python capability registry has no rule for {kind}/{operation or "default"}')
            capabilities.update(linked)
            if kind == 'sap' and operation == 'idoc_listener':
                source = str(activity.get('config', {}).get('messagingSource') or '').strip().lower().replace(' ', '')
                if source == 'kafka': capabilities.add('kafka')
                elif source in {'ems', 'jms'}: capabilities.add('jms')
                elif source not in {'', 'nomessaging', 'direct', 'sapjcorfc/idoc_inbound_asynchronous'}:
                    # A property/template-driven messaging source can select a
                    # different provider per environment, so retain both legal
                    # provider implementations rather than producing a package
                    # that fails when its profile changes.
                    capabilities.update({'kafka', 'jms'})
        for group in task.get('groups') or []:
            capabilities.add(f"group:{group.get('type') or 'unknown'}")
            if group.get('type') == 'transaction_jdbc': capabilities.add('jdbc')
    return capabilities


def _project_artifact_closure(project: dict) -> tuple[list[dict], list[dict]]:
    """Return the transitive resource and schema closure for selected tasks.

    A task can reference a connection which itself delegates to another shared
    resource, and an XSD/JSON schema can include another schema. Packaging only
    the first object found in the task would create a small, but broken,
    archive. Follow those references while excluding unrelated project assets.
    """
    resources = project.get('resources') or []
    resource_by_id = {str(item.get('id') or ''): item for item in resources}
    referenced_ids: set[str] = set()
    dynamic_resource_types: set[str] = set()
    expected_type = {'ems': 'ems', 'jms': 'jms', 'kafka': 'kafka', 'pubsub': 'pubsub', 'sap': 'sap',
                     'jdbc': 'jdbc', 'snowflake': 'snowflake', 'amqp': 'amqp', 'ftp': 'ftp', 'sftp': 'sftp',
                     'http': 'http', 'http_listener': 'http', 'rest': 'http', 'soap': 'http'}
    def collect(value, activity_type=''):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and ('resourceid' in key.lower() or key.lower().endswith('connectionid')):
                    if child in resource_by_id: referenced_ids.add(child)
                    elif '${' in child and activity_type in expected_type: dynamic_resource_types.add(expected_type[activity_type])
                collect(child, activity_type)
        elif isinstance(value, list):
            for child in value: collect(child, activity_type)
    for task in project.get('tasks', []):
        for activity in task.get('activities', []): collect(activity.get('config') or {}, str(activity.get('type') or ''))
        for group in task.get('groups') or []: collect(group.get('config') or {}, 'jdbc' if group.get('type') == 'transaction_jdbc' else '')
    # Shared resources may be layered. Retain dependencies of selected
    # resources recursively instead of retaining every project connection.
    scanned_resources: set[str] = set()
    while True:
        for resource in resources:
            if str(resource.get('type') or '') in dynamic_resource_types:
                referenced_ids.add(str(resource.get('id') or ''))
        pending_resources = referenced_ids - scanned_resources
        if not pending_resources: break
        for resource_id in pending_resources:
            scanned_resources.add(resource_id)
            resource = resource_by_id.get(resource_id)
            if resource:
                collect(resource.get('config') or {}, str(resource.get('type') or ''))
    selected_resources = [resource for resource in resources if str(resource.get('id') or '') in referenced_ids]
    schema_references: set[str] = set()
    known_schemas = {str(schema.get('id') or ''): schema for schema in project.get('schemas') or []}
    known_schemas.update({str(schema.get('name') or ''): schema for schema in project.get('schemas') or []})
    dynamic_schema_reference = False
    def collect_schemas(value, key=''):
        nonlocal dynamic_schema_reference
        if isinstance(value, dict):
            for child_key, child in value.items(): collect_schemas(child, str(child_key))
        elif isinstance(value, list):
            for child in value: collect_schemas(child, key)
        elif isinstance(value, str) and 'schema' in key.lower():
            if value in known_schemas: schema_references.add(value)
            elif '${' in value: dynamic_schema_reference = True
    for task in project.get('tasks', []): collect_schemas(task)
    for resource in selected_resources: collect_schemas(resource)
    if dynamic_schema_reference:
        schema_references.update(known_schemas)
    selected_schema_ids = {id(known_schemas[name]) for name in schema_references}
    # Follow XSD include/import schemaLocation and JSON Schema $ref values.
    schema_aliases: dict[str, dict] = {}
    for schema in project.get('schemas') or []:
        for alias in (str(schema.get('id') or ''), str(schema.get('name') or '')):
            if alias:
                schema_aliases[alias] = schema
                schema_aliases[alias.replace('\\', '/').rsplit('/', 1)[-1]] = schema
    pending_schemas = [schema for schema in project.get('schemas') or [] if id(schema) in selected_schema_ids]
    while pending_schemas:
        schema = pending_schemas.pop()
        content = str(schema.get('content') or '')
        references = re.findall(r'''schemaLocation\s*=\s*["']([^"']+)["']''', content)
        references.extend(re.findall(r'''["']\$ref["']\s*:\s*["']([^"']+)["']''', content))
        for reference in references:
            path = reference.split('#', 1)[0].replace('\\', '/')
            if not path: continue
            dependency = schema_aliases.get(path) or schema_aliases.get(path.rsplit('/', 1)[-1])
            if dependency is not None and id(dependency) not in selected_schema_ids:
                selected_schema_ids.add(id(dependency))
                pending_schemas.append(dependency)
    selected_schemas = [schema for schema in project.get('schemas') or [] if id(schema) in selected_schema_ids]
    return selected_resources, selected_schemas


def _profile_closure(project: dict, profiles: dict[str, list[dict]]) -> dict[str, list[dict]]:
    searchable = repr({'tasks': project.get('tasks') or [], 'resources': project.get('resources') or [], 'schemas': project.get('schemas') or []})
    referenced = set(re.findall(r'\$\{properties\.([^}]+)\}', searchable))
    result = {}
    for environment, values in profiles.items():
        by_key = {str(item.get('key') or ''): item for item in values}
        required, pending = set(referenced), list(referenced)
        while pending:
            item = by_key.get(pending.pop())
            if not item: continue
            for alias in re.findall(r'\$\{properties\.([^}]+)\}', str(item.get('value') or '')):
                if alias not in required: required.add(alias); pending.append(alias)
        result[environment] = [item for item in values if str(item.get('key') or '') in required]
    return result


def _filter_capability_blocks(source: str, capabilities: set[str]) -> str:
    """Remove marked implementation blocks that are unreachable in this project."""
    output, keep_stack = [], []
    marker = re.compile(r'^(\s*)# CAPABILITY ([A-Za-z0-9_:-]+) (START|END)\s*$')
    for line in source.splitlines():
        match = marker.match(line)
        if match:
            if match.group(3) == 'START': keep_stack.append(match.group(2) in capabilities)
            elif keep_stack: keep_stack.pop()
            continue
        if all(keep_stack) if keep_stack else True: output.append(line)
    return '\n'.join(output) + '\n'


def _prune_module(source: str, roots: set[str]) -> bytes:
    """Retain selected top-level functions and their transitive Python dependencies."""
    tree = ast.parse(source)
    definitions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name): assignments[target.id] = node
    kept = set(roots)
    changed = True
    while changed:
        changed = False
        nodes = [definitions[name] for name in kept if name in definitions] + [assignments[name] for name in kept if name in assignments]
        referenced = {child.id for node in nodes for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}
        additions = referenced & (set(definitions) | set(assignments)) - kept
        if additions: kept.update(additions); changed = True
    kept_nodes = [definitions[name] for name in kept if name in definitions] + [assignments[name] for name in kept if name in assignments]
    used = {child.id for node in kept_nodes for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)} | kept
    body = []
    for index, node in enumerate(tree.body):
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str): body.append(node); continue
        if isinstance(node, ast.ImportFrom) and node.module == '__future__': body.append(node); continue
        if isinstance(node, ast.Import):
            aliases = [alias for alias in node.names if (alias.asname or alias.name.split('.')[0]) in used]
            if aliases: node.names = aliases; body.append(node)
            continue
        if isinstance(node, ast.ImportFrom):
            aliases = [alias for alias in node.names if (alias.asname or alias.name) in used]
            if aliases: node.names = aliases; body.append(node)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in kept: body.append(node)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in kept for target in targets): body.append(node)
    tree.body = body
    ast.fix_missing_locations(tree)
    return (ast.unparse(tree) + '\n').encode('utf-8')


def _specialize_module(source: str, limits: dict[str, dict[str, set[str]]]) -> str:
    """Narrow operation/kind branches to the statically reachable variants."""
    class Specializer(ast.NodeTransformer):
        active: dict[str, set[str]] = {}
        def _function(self, node):
            previous, self.active = self.active, limits.get(node.name, {})
            node = self.generic_visit(node)
            self.active = previous
            return node
        visit_FunctionDef = _function
        visit_AsyncFunctionDef = _function
        def visit_Compare(self, node):
            node = self.generic_visit(node)
            if len(node.ops) != 1 or len(node.comparators) != 1 or not isinstance(node.left, ast.Name): return node
            allowed = self.active.get(node.left.id)
            if not allowed: return node
            comparator = node.comparators[0]
            if isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                possible = comparator.value in allowed
                if isinstance(node.ops[0], ast.NotEq): possible = not possible
                if len(allowed) == 1 or not possible: return ast.copy_location(ast.Constant(possible), node)
            if isinstance(node.ops[0], (ast.In, ast.NotIn)) and isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
                values = {item.value for item in comparator.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                intersection = values & allowed
                result = bool(intersection)
                if isinstance(node.ops[0], ast.NotIn): result = bool(allowed - values)
                if not result or allowed <= values and isinstance(node.ops[0], ast.In) or allowed.isdisjoint(values) and isinstance(node.ops[0], ast.NotIn):
                    return ast.copy_location(ast.Constant(result), node)
                comparator.elts = [ast.Constant(value) for value in sorted(intersection if isinstance(node.ops[0], ast.In) else values & allowed)]
            return node
        def visit_If(self, node):
            node = self.generic_visit(node)
            if isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool): return node.body if node.test.value else node.orelse
            return node
    tree = Specializer().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + '\n'


def _starter_event(task: dict) -> dict | None:
    if task.get('kind') != 'starter': return None
    activities = {item['id']: item for item in task['activities']}
    incoming = {edge['target'] for edge in task.get('transitions', [])}
    entries = [item for item in task['activities'] if item['id'] not in incoming and item['type'] != 'catch']
    if len(entries) != 1: return None
    candidate = entries[0]
    if candidate['type'] == 'start':
        successors = [edge['target'] for edge in task.get('transitions', [])
                      if edge['source'] == candidate['id'] and _edge_type(edge) == 'success']
        if len(successors) == 1: candidate = activities.get(successors[0], candidate)
    operation = str(candidate.get('config', {}).get('operation') or '')
    return candidate if (candidate['type'], operation) in EVENT_OPERATIONS else None


def _identifier(value: str) -> str:
    result = re.sub(r'[^A-Za-z0-9_]', '_', value).strip('_') or 'task'
    return f'_{result}' if result[0].isdigit() else result


_CONDITION_ATOM = r'(?:\$\{[^}]+\}|true|false|-?\d+(?:\.\d+)?|"[^"\n]*"|\'[^\'\n]*\')'


def _condition_atom_source(value: str) -> str:
    item = value.strip()
    if item.lower() in {'true', 'false'}: return item.title()
    if re.fullmatch(r'-?\d+(?:\.\d+)?', item): return item
    if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"}: return repr(item[1:-1])
    if re.fullmatch(r'\$\{[^}]+\}', item): return f'resolve({_direct_literal(item)}, ctx)'
    raise ValueError(f'Unsupported direct-code condition: {value!r}')


def _condition_source(value: str) -> str:
    condition = str(value or '').strip()
    match = re.fullmatch(rf'\s*({_CONDITION_ATOM})\s*(==|!=|>=|<=|>|<)\s*({_CONDITION_ATOM})\s*', condition, re.I)
    if match:
        return f'({_condition_atom_source(match.group(1))} {match.group(2)} {_condition_atom_source(match.group(3))})'
    return f'bool({_condition_atom_source(condition)})'


def _simple_group_plans(task: dict) -> list[dict]:
    """Accept only structured groups that compile to inline Python control flow."""
    groups = task.get('groups') or []
    if not groups: return []
    if len(groups) > 1:
        by_id = {group['id']: group for group in groups}
        if len(by_id) != len(groups): raise ValueError(f"{task['name']}: duplicate group identifiers")
        def ancestors(group: dict) -> list[str]:
            result, seen = [], set()
            current = group.get('parent_group_id')
            while current:
                if current not in by_id or current in seen:
                    raise ValueError(f"{task['name']}: invalid nested group hierarchy")
                result.append(current); seen.add(current)
                current = by_id[current].get('parent_group_id')
            return result
        lineage = {group['id']: ancestors(group) for group in groups}
        descendants = {}
        for group in groups:
            children = [child for child in groups if group['id'] in lineage[child['id']]]
            descendants[group['id']] = set(group.get('member_activity_ids') or []) - set(by_id)
            for child in children:
                descendants[group['id']].update(set(child.get('member_activity_ids') or []) - set(by_id))
        for left in groups:
            for right in groups:
                if left['id'] >= right['id']: continue
                if descendants[left['id']] & descendants[right['id']] and left['id'] not in lineage[right['id']] and right['id'] not in lineage[left['id']]:
                    raise ValueError(f"{task['name']}: overlapping sibling groups are ambiguous")
        plans = []
        for group in sorted(groups, key=lambda item: (len(lineage[item['id']]), item['id'])):
            flattened = {**group, 'parent_group_id': None, 'member_activity_ids': sorted(descendants[group['id']])}
            compiled = _simple_group_plans({**task, 'groups': [flattened]})
            for plan in compiled:
                plan['parent_group_id'] = group.get('parent_group_id')
                plan['depth'] = len(lineage[group['id']])
            plans.extend(compiled)
        return plans
    if len(groups) != 1 or groups[0].get('type') not in SUPPORTED_GROUP_TYPES or groups[0].get('parent_group_id'):
        raise ValueError(f"{task['name']}: nested or unsupported groups are not yet supported by independent Python code")
    group = groups[0]
    members = set(group.get('member_activity_ids') or [])
    if not members: raise ValueError(f"{task['name']}: If group is empty")
    transitions = task.get('transitions') or []
    entries = {edge['target'] for edge in transitions if edge['source'] not in members and edge['target'] in members}
    exits = [edge for edge in transitions if edge['source'] in members and edge['target'] not in members]
    if len(entries) != 1 or len(exits) != 1 or _edge_type(exits[0]) != 'success':
        raise ValueError(f"{task['name']}: direct group needs one external entry and one unconditional exit")
    if any(edge['source'] in members and edge['target'] in members and _edge_type(edge) != 'success' for edge in transitions):
        raise ValueError(f"{task['name']}: direct group cannot contain conditional or error transitions")
    activity_types = {activity['id']: activity['type'] for activity in task['activities']}
    if any(activity_types.get(member) in (None, 'end') for member in members):
        raise ValueError(f"{task['name']}: direct group has a missing or terminal member")
    reachable = set()
    pending = list(entries)
    while pending:
        member = pending.pop()
        if member in reachable: continue
        reachable.add(member)
        pending.extend(edge['target'] for edge in transitions if edge['source'] == member and edge['target'] in members)
    if reachable != members:
        raise ValueError(f"{task['name']}: direct group has disconnected members")
    cfg = group.get('config') or {}
    expression = _condition_source(str(cfg.get('condition') or '')) if group['type'] in {'if', 'while'} or group['type'] == 'repeat' and cfg.get('condition') else ''
    if group['type'] == 'repeat' and not expression and cfg.get('count', cfg.get('iterations')) is None:
        raise ValueError(f"{task['name']}: Repeat group needs a condition or count")
    if group['type'] == 'repeat_on_error':
        expression = _condition_source(str(cfg.get('stopCondition') or ''))
    if group['type'] in {'for_each', 'iterate'}:
        if cfg.get('collection', cfg.get('source')) in (None, '') and not (group['type'] == 'for_each' and cfg.get('start') is not None and cfg.get('end') is not None):
            raise ValueError(f"{task['name']}: collection group needs a source or numeric range")
    if group['type'] == 'transaction_jdbc':
        jdbc_members = [activity for activity in task['activities'] if activity['id'] in members and activity['type'] == 'jdbc']
        if not jdbc_members:
            raise ValueError(f"{task['name']}: JDBC transaction group needs JDBC activities")
        configured = str(cfg.get('resourceId') or '')
        used = {str(item.get('config', {}).get('resourceId') or '') for item in jdbc_members}
        if not configured and len(used) == 1: configured = next(iter(used))
        if not configured or any(item not in ('', configured) for item in used):
            raise ValueError(f"{task['name']}: JDBC transaction group needs one static shared connection")
        cfg = {**cfg, 'resourceId': configured}
    return [{'entry': next(iter(entries)), 'exit_source': exits[0]['source'],
             'exit_target': exits[0]['target'], 'expression': expression,
             'type': group['type'], 'config': cfg, 'id': group['id'], 'members': members,
             'parent_group_id': group.get('parent_group_id'), 'depth': 0}]


def _direct_literal(value, indent: int = 0) -> str:
    """Compile expressions into Python reference objects, never Fabric syntax."""
    if isinstance(value, str):
        matches = list(re.finditer(r'\$\{([^}]+)\}', value))
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return f'Reference({matches[0].group(1)!r})'
        if matches:
            parts = []
            cursor = 0
            for match in matches:
                if match.start() > cursor: parts.append(repr(value[cursor:match.start()]))
                parts.append(f'Reference({match.group(1)!r})')
                cursor = match.end()
            if cursor < len(value): parts.append(repr(value[cursor:]))
            return 'Template((' + ', '.join(parts) + (',' if len(parts) == 1 else '') + '))'
    if isinstance(value, dict):
        if not value: return 'dict()'
        if all(isinstance(key, str) and key.isidentifier() and not keyword.iskeyword(key) for key in value):
            pad = ' ' * indent
            fields = [f'{pad}    {key}={_direct_literal(item, indent + 4)},' for key, item in value.items()]
            return 'dict(\n' + '\n'.join(fields) + f'\n{pad})'
        return '{' + ', '.join(f'{key!r}: {_direct_literal(item, indent)}' for key, item in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(_direct_literal(item, indent) for item in value) + ']'
    return repr(value)


def validate_raw_python(project: dict) -> None:
    _validate_capability_registry()
    failures: list[str] = []
    task_ids = {task['id'] for task in project['tasks']}
    for task in project['tasks']:
        incoming_ids = {edge['target'] for edge in task.get('transitions', [])}
        entry_ids = {activity['id'] for activity in task['activities'] if activity['type'] == 'start'} or {
            activity['id'] for activity in task['activities'] if activity['id'] not in incoming_ids and activity['type'] != 'catch'
        }
        try: _simple_group_plans(task)
        except ValueError as error: failures.append(str(error))
        starter_event = _starter_event(task)
        for activity in task.get('activities', []):
            kind = str(activity['type'])
            operation = str(activity.get('config', {}).get('operation') or ('empty' if kind == 'basic' else ''))
            if kind not in STRUCTURAL and (kind, operation) not in SUPPORTED:
                failures.append(f"{task['name']} / {activity['name']}: {kind}/{operation or 'default'}")
            if kind in {'ems', 'jms'} and operation in {'queue_receiver', 'topic_subscriber', 'receive_message', 'get_queue_message', 'wait_request'}:
                client_ack = str(activity.get('config', {}).get('acknowledgeMode') or 'Auto').strip().lower() not in {'auto', 'automatic'}
                if client_ack and not (starter_event and activity['id'] == starter_event['id']):
                    failures.append(f"{task['name']} / {activity['name']}: client acknowledgement requires a Starter Task receiver")
            if kind == 'call_task' and str(activity.get('config', {}).get('taskId') or '') not in task_ids:
                failures.append(f"{task['name']} / {activity['name']}: Call Sub Task needs a static taskId")
        outgoing: dict[str, int] = {}
        for edge in task.get('transitions', []):
            if _edge_type(edge) == 'success':
                outgoing[edge['source']] = outgoing.get(edge['source'], 0) + 1
            if edge.get('type') == 'success_condition' and str(edge.get('condition') or '').strip() not in ('true', 'false') and not re.fullmatch(r'\$\{[^}]+\}', str(edge.get('condition') or '')):
                failures.append(f"{task['name']}: conditional transition {edge.get('id', '')} needs a simple boolean field expression")
        if task.get('groups') and any(count > 1 for count in outgoing.values()):
            failures.append(f"{task['name']}: parallel branches inside groups are not yet supported by direct code")
        for source_id, count in outgoing.items():
            if count <= 1: continue
            pending = [edge['target'] for edge in task.get('transitions', []) if edge['source'] == source_id and _edge_type(edge) == 'success']
            visited = set()
            while pending:
                candidate = pending.pop()
                if candidate == source_id:
                    failures.append(f"{task['name']}: parallel branches cannot cycle back to their fork")
                    break
                if candidate in visited: continue
                visited.add(candidate)
                pending.extend(edge['target'] for edge in task.get('transitions', []) if edge['source'] == candidate and _edge_type(edge) == 'success')
        for activity in task['activities']:
            edges = [edge for edge in task.get('transitions', []) if edge['source'] == activity['id']]
            conditions = [edge for edge in edges if edge.get('type') == 'success_condition']
            if len(conditions) > 1 or conditions and any(_edge_type(edge) == 'success' for edge in edges):
                failures.append(f"{task['name']} / {activity['name']}: parallel conditional branches are not yet supported by direct code")
    if failures:
        raise ValueError('Raw Python export cannot preserve these behaviors yet: ' + '; '.join(failures))


def raw_python_requirements(project: dict) -> tuple[list[dict], list[str]]:
    """Return optional runtime requirements actually used by the task closure."""
    activity_pairs = {(str(activity.get('type') or ''), str(activity.get('config', {}).get('operation') or ''))
                      for task in project.get('tasks', []) for activity in task.get('activities', [])}
    resources: dict[str, list[dict]] = {}
    for item in project.get('resources', []): resources.setdefault(str(item.get('type') or ''), []).append(item.get('config') or {})
    def needs_external(kind: str) -> bool:
        configured = resources.get(kind) or []
        return not configured or any(str(item.get('mode') or '').lower() not in {'memory', 'mock'} for item in configured)
    checks: list[dict] = []
    def add(name: str, modules: list[str], install: str, *, any_module: bool = False, java: bool = False):
        if not any(item['name'] == name for item in checks):
            checks.append({'name': name, 'modules': modules, 'install': install, 'any': any_module, 'java': java})
    if any(kind == 'kafka' for kind, _ in activity_pairs) and needs_external('kafka'): add('Kafka client', ['aiokafka'], 'python -m pip install aiokafka')
    if any(kind == 'pubsub' for kind, _ in activity_pairs): add('Google Pub/Sub client', ['google.cloud.pubsub_v1', 'google.oauth2'], 'python -m pip install google-cloud-pubsub google-auth')
    if any(kind == 'sftp' for kind, _ in activity_pairs): add('SFTP client', ['paramiko'], 'python -m pip install paramiko')
    if any(kind == 'excel' for kind, _ in activity_pairs): add('Excel reader', ['openpyxl'], 'python -m pip install openpyxl')
    if any(kind == 'snowflake' for kind, _ in activity_pairs): add('Snowflake client', ['snowflake.connector'], 'python -m pip install snowflake-connector-python')
    if any(kind == 'amqp' for kind, _ in activity_pairs):
        amqp_config = (resources.get('amqp') or [{}])[0]
        mode = str(amqp_config.get('brokerType') or amqp_config.get('provider') or '').lower()
        if 'azure' in mode: add('Azure Service Bus AMQP client', ['azure.servicebus'], 'python -m pip install azure-servicebus')
        elif needs_external('amqp'): add('AMQP client', ['pika', 'azure.servicebus'], 'python -m pip install pika  # or azure-servicebus', any_module=True)
    sap_sources = {str(activity.get('config', {}).get('messagingSource') or '').strip().lower().replace(' ', '')
                   for task in project.get('tasks', []) for activity in task.get('activities', [])
                   if activity.get('type') == 'sap' and activity.get('config', {}).get('operation') == 'idoc_listener'}
    if 'kafka' in sap_sources and needs_external('kafka'): add('Kafka client', ['aiokafka'], 'python -m pip install aiokafka')
    bridge_kinds = {kind for kind, _ in activity_pairs if kind in {'ems', 'jms', 'sap'} and needs_external(kind)}
    if any(source in sap_sources and needs_external(source) for source in ('ems', 'jms')):
        bridge_kinds.add('sap-messaging-bridge')
    if bridge_kinds or any(kind == 'java' for kind, _ in activity_pairs):
        add('Java vendor bridge', [], 'Provision Java plus the licensed vendor JARs in the configured driver directory.', java=True)
    external: list[str] = []
    for task in project.get('tasks', []):
        for activity in task.get('activities', []):
            cfg = activity.get('config') or {}
            if activity.get('type') in {'java', 'python'} and cfg.get('artifactPath'):
                external.append(str(cfg['artifactPath']))
    return checks, sorted(set(external))


def raw_python_files(project: dict, profiles: dict[str, list[dict]]) -> dict[str, bytes]:
    validate_raw_python(project)
    linked_resources, linked_schemas = _project_artifact_closure(project)
    linked_project = {**project, 'resources': linked_resources, 'schemas': linked_schemas}
    profiles = _profile_closure(linked_project, profiles)
    root = Path(__file__).with_name('raw_python_support')
    capabilities = _project_capabilities(project)
    operations_by_kind: dict[str, set[str]] = {}
    for task in project['tasks']:
        for activity in task['activities']:
            operations_by_kind.setdefault(str(activity.get('type') or ''), set()).add(str(activity.get('config', {}).get('operation') or ''))
    files = {f'application/{name}': (root / name).read_bytes()
             for name in ('__init__.py', 'diagnostics.py', 'qualification.py')}
    core_source = _filter_capability_blocks((root / 'core.py').read_text(encoding='utf-8'), capabilities)
    retry_expressions = []
    if 'kafka' in capabilities: retry_expressions.append("(kind == 'kafka' and raw.get('operation') in {'publish', 'send'})")
    if 'pubsub' in capabilities: retry_expressions.append("(kind == 'pubsub' and raw.get('operation') == 'publish')")
    if 'jms' in capabilities: retry_expressions.append("(kind in {'ems', 'jms'} and raw.get('operation') in {'send', 'publish', 'send_message', 'request_reply', 'reply', 'reply_message'})")
    if 'sap' in capabilities: retry_expressions.append("(kind == 'sap' and raw.get('operation') in {'post_idoc', 'invoke_rfc_bapi', 'reply_rfc_bapi'})")
    core_source = core_source.replace('False  # OUTBOUND_RETRY_EXPRESSION', ' or '.join(retry_expressions) or 'False')
    core_roots = {'Context', 'Reference', 'Template', 'resolve', 'execute_with_policy'}
    if 'group:critical_section' in capabilities:
        core_roots.add('group_lock')
    files['application/core.py'] = _prune_module(core_source, core_roots)
    activity_roots: set[str] = set()
    if 'file' in capabilities: activity_roots.add('file_activity')
    if 'data_formats' in capabilities: activity_roots.add('data_activity')
    if 'excel' in capabilities: activity_roots.add('excel_read')
    if 'transfer' in capabilities: activity_roots.add('transfer')
    if 'http_client' in capabilities: activity_roots.add('http_request')
    if 'python' in capabilities: activity_roots.add('python_invoke')
    if 'java' in capabilities: activity_roots.add('java_invoke')
    basic_operations = {str(activity.get('config', {}).get('operation') or '') for task in project['tasks'] for activity in task['activities'] if activity['type'] == 'basic'}
    if 'external_command' in basic_operations: activity_roots.add('external_command')
    if basic_operations & {'get_shared_variable', 'set_shared_variable'}: activity_roots.add('shared_variable')
    if activity_roots:
        activity_source = _specialize_module((root / 'activities.py').read_text(encoding='utf-8'), {
            'file_activity': {'operation': operations_by_kind.get('file', set())},
            'data_activity': {'operation': set().union(*(operations_by_kind.get(kind, set()) for kind in ('xml', 'json', 'flat'))),
                              'kind': {kind for kind in ('xml', 'json', 'flat') if kind in operations_by_kind}},
            'transfer': {'operation': set().union(*(operations_by_kind.get(kind, set()) for kind in ('ftp', 'sftp'))),
                         'kind': {kind for kind in ('ftp', 'sftp') if kind in operations_by_kind}},
        })
        files['application/activities.py'] = _prune_module(activity_source, activity_roots)
    connector_roots: set[str] = set()
    if 'jms' in capabilities: connector_roots.update({'jms', 'acknowledge_jms', 'close_jms'})
    if 'sap' in capabilities: connector_roots.update({'sap', 'acknowledge_sap', 'close_sap'})
    for capability in ('jdbc', 'snowflake', 'amqp', 'kafka', 'pubsub'):
        if capability in capabilities: connector_roots.add(capability)
    if 'kafka' in capabilities: connector_roots.add('close_kafka')
    if 'pubsub' in capabilities: connector_roots.add('close_pubsub')
    if connector_roots:
        jms_operations = set().union(*(operations_by_kind.get(kind, set()) for kind in ('ems', 'jms')))
        kafka_operations = set(operations_by_kind.get('kafka', set()))
        for task in project['tasks']:
            for activity in task['activities']:
                if activity.get('type') != 'sap' or activity.get('config', {}).get('operation') != 'idoc_listener': continue
                source = str(activity.get('config', {}).get('messagingSource') or '').strip().lower().replace(' ', '')
                if source == 'kafka': kafka_operations.add('receive')
                elif source == 'ems': jms_operations.add('queue_receiver')
                elif source == 'jms': jms_operations.add('receive_message')
        connector_source = _specialize_module((root / 'connectors.py').read_text(encoding='utf-8'), {
            'jms': {'operation': jms_operations, 'kind': {kind for kind in ('ems', 'jms') if kind in operations_by_kind} or {'ems', 'jms'}},
            'sap': {'operation': operations_by_kind.get('sap', set())},
            'kafka': {'operation': kafka_operations},
            'pubsub': {'operation': operations_by_kind.get('pubsub', set())},
            'snowflake': {'operation': operations_by_kind.get('snowflake', set())},
            'amqp': {'operation': operations_by_kind.get('amqp', set())},
        })
        files['application/connectors.py'] = _prune_module(connector_source, connector_roots)
    files['application/capabilities.py'] = ('"""Capability closure linked into this generated application."""\n'
        f'CAPABILITIES = {tuple(sorted(capabilities))!r}\n').encode('utf-8')
    main_source = (root / 'main.py').read_text(encoding='utf-8')
    delivery_capabilities = capabilities & {'sap', 'jms'}
    connector_lifecycle_capabilities = capabilities & {'sap', 'jms', 'kafka', 'pubsub'}
    main_source = main_source.replace('# CONNECTOR_IMPORT', 'from . import connectors' if connector_lifecycle_capabilities else '')
    ack_start = main_source.index('    # ACKNOWLEDGEMENT_CAPABILITY_START')
    ack_end = main_source.index('    # ACKNOWLEDGEMENT_CAPABILITY_END', ack_start) + len('    # ACKNOWLEDGEMENT_CAPABILITY_END')
    acknowledgement = ''
    if delivery_capabilities:
        acknowledgement = '    async def acknowledge_delivery(technology: str, listener_key: str, delivery_id: str, success: bool):\n'
        if delivery_capabilities == {'sap'}: acknowledgement += '        await asyncio.to_thread(connectors.acknowledge_sap, listener_key, delivery_id, success)\n'
        elif delivery_capabilities == {'jms'}: acknowledgement += '        connectors.acknowledge_jms(listener_key, delivery_id, success)\n'
        else: acknowledgement += "        if technology == 'sap': await asyncio.to_thread(connectors.acknowledge_sap, listener_key, delivery_id, success)\n        else: connectors.acknowledge_jms(listener_key, delivery_id, success)\n"
    main_source = main_source[:ack_start] + acknowledgement + main_source[ack_end:]
    close_start = main_source.index('        # CONNECTOR_CLOSE_START')
    close_end = main_source.index('        # CONNECTOR_CLOSE_END', close_start) + len('        # CONNECTOR_CLOSE_END')
    close_source = ''.join(f'        connectors.close_{name}()\n' for name in ('sap', 'jms') if name in delivery_capabilities) or '        pass\n'
    main_source = main_source[:close_start] + close_source + main_source[close_end:]
    async_close_start = main_source.index('        # ASYNC_CONNECTOR_CLOSE_START')
    async_close_end = main_source.index('        # ASYNC_CONNECTOR_CLOSE_END', async_close_start) + len('        # ASYNC_CONNECTOR_CLOSE_END')
    async_close_source = ''.join(f'        await connectors.close_{name}()\n' for name in ('kafka', 'pubsub') if name in capabilities) or '        pass\n'
    main_source = main_source[:async_close_start] + async_close_source + main_source[async_close_end:]
    files['application/main.py'] = main_source.encode('utf-8')
    has_inbound_http = 'inbound_http' in capabilities
    if has_inbound_http:
        files['application/inbound_http.py'] = (root / 'inbound_http.py').read_bytes()
    else:
        main_source = files['application/main.py'].decode('utf-8')
        start = main_source.index('    # HTTP_CAPABILITY_START')
        end = main_source.index('    # HTTP_CAPABILITY_END', start) + len('    # HTTP_CAPABILITY_END')
        files['application/main.py'] = (main_source[:start]
            + "    jobs = [receive_forever(task_id) if task_id in EVENT_STARTERS else run_task(task_id, environment_name=environment_name) for task_id in ids]\n"
            + main_source[end:]).encode('utf-8')
    # A Python script task can run run.py from an extracted archive.  The
    # __main__ module also makes the .pympkg (and legacy .pyifpkg) directly executable by CPython
    # as a zip application, without generating or editing a launcher.
    launcher = b'"""Run this exported application with any standard Python interpreter."""\nfrom application.main import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
    files['run.py'] = launcher
    files['__main__.py'] = launcher
    native_modules = set()
    if 'sap' in capabilities: native_modules.update({'sap.py', 'java_bridge.py'})
    if 'jms' in capabilities or 'java' in capabilities: native_modules.add('java_bridge.py')
    if 'jdbc' in capabilities: native_modules.update({'jdbc.py', 'java_bridge.py'})
    if 'snowflake' in capabilities: native_modules.add('snowflake.py')
    if 'amqp' in capabilities: native_modules.add('amqp.py')
    if 'dataweave' in capabilities: native_modules.add('dataweave.py')
    if 'mapper' in capabilities: native_modules.add('mapper.py')
    if native_modules:
        files['application/native/__init__.py'] = b'"""Capability-selected native adapters; vendor binaries remain external."""\n'
        for name in sorted(native_modules): files[f'application/native/{name}'] = Path(__file__).with_name(name).read_bytes()
    files['application/tasks/__init__.py'] = b'"""Generated async tasks."""\n'
    checks, external_files = raw_python_requirements(linked_project)
    files['application/requirements.py'] = (
        '"""Generated deployment requirements for this application."""\n'
        f'CHECKS = {pformat(checks, width=100, sort_dicts=False)}\n'
        f'EXTERNAL_FILES = {pformat(external_files, width=100, sort_dicts=False)}\n'
    ).encode('utf-8')
    task_modules: dict[str, str] = {}
    for index, task in enumerate(project['tasks']):
        module = f'task_{index}_{_identifier(str(task["id"]))}'
        task_modules[task['id']] = module
    profile_source = ',\n    '.join(
        f'{name!r}: [{", ".join(_python_call("Property", item, ("key", "value", "data_type"), 8) for item in values)}]'
        for name, values in profiles.items())
    resource_source = ',\n    '.join(
        f'{resource["id"]!r}: Resource(id={resource["id"]!r}, type={resource["type"]!r}, name={resource["name"]!r}, config={_direct_literal(resource["config"], 8)})'
        for resource in linked_resources)
    schema_source = ',\n    '.join(
        f'{schema["name"]!r}: {_python_call("Schema", schema, ("name", "content"), 4)}'
        for schema in linked_schemas)
    files['application/config.py'] = (
        '"""Typed, sanitized deployment configuration. Secrets come from environment variables."""\n'
        'from dataclasses import dataclass, field\nfrom typing import Any\nimport json\nimport os\nfrom .core import Reference, Template\n\n'
        '@dataclass(frozen=True)\nclass Property:\n    key: str\n    value: Any\n    data_type: str = "string"\n\n'
        '@dataclass(frozen=True)\nclass Resource:\n    id: str\n    type: str\n    name: str\n    config: dict[str, Any] = field(default_factory=dict)\n\n'
        '@dataclass(frozen=True)\nclass Schema:\n    name: str\n    content: str\n\n'
        f'PROFILES = {{\n    {profile_source}\n}}\n'
        'DEFAULT_ENVIRONMENT = next(iter(PROFILES), "local")\n'
        f'RESOURCES = {{\n    {resource_source}\n}}\n'
        f'SCHEMAS = {{\n    {schema_source}\n}}\n\n'
        'def environment(name: str) -> tuple[dict[str, Any], dict[str, Resource]]:\n'
        '    if name not in PROFILES:\n        raise ValueError(f"Unknown environment: {name}")\n'
        '    properties = {}\n'
        '    for prop in PROFILES[name]:\n'
        '        value = os.environ.get(prop.key, prop.value)\n'
        '        if prop.data_type in ("integer", "long") and value not in (None, ""): value = int(value)\n'
        '        elif prop.data_type == "number" and value not in (None, ""): value = float(value)\n'
        '        elif prop.data_type == "boolean" and isinstance(value, str): value = value.lower() in ("true", "1", "yes", "on")\n'
        '        elif prop.data_type == "json" and isinstance(value, str) and value: value = json.loads(value)\n'
        '        properties[prop.key] = value\n'
        '    resources = {}\n'
        '    for key, resource in RESOURCES.items():\n'
        '        config = dict(resource.config)\n'
        '        for field in config:\n'
        '            secret_key = f"resources.{key}.config.{field}"\n'
        '            if secret_key in os.environ: config[field] = os.environ[secret_key]\n'
        '        resources[key] = Resource(resource.id, resource.type, resource.name, config)\n'
        '    return properties, resources\n'
    ).encode('utf-8')
    task_imports = '\n'.join(f'from .tasks import {module}' for module in task_modules.values())
    registry = ', '.join(f'{task_id!r}: {module}.run' for task_id, module in task_modules.items())
    event_starters = {task['id']: activity for task in project['tasks']
                      if (activity := _starter_event(task)) is not None}
    event_source = ',\n    '.join(
        f'{task_id!r}: ({activity["id"]!r}, {activity["type"]!r}, {_direct_literal(activity.get("config") or {}, 8)}, {activity["name"]!r})'
        for task_id, activity in event_starters.items())
    files['application/registry.py'] = (
        '"""Generated task registry; callable from notebooks or another Python host."""\n'
        'from .core import Reference, Template\n'
        f'{task_imports}\nTASKS = {{{registry}}}\n'
        f'STARTERS = {repr([task["id"] for task in project["tasks"] if task["kind"] == "starter"])}\n'
        f'EVENT_STARTERS = {{\n    {event_source}\n}}\n'
    ).encode('utf-8')
    for task in project['tasks']:
        group_plans = _simple_group_plans(task)
        activities = {activity['id']: activity for activity in task['activities']}
        incoming = {edge['target'] for edge in task['transitions']}
        starts = [activity['id'] for activity in task['activities'] if activity['type'] == 'start'] or [activity['id'] for activity in task['activities'] if activity['id'] not in incoming and activity['type'] != 'catch']
        if len(starts) != 1:
            raise ValueError(f"Raw Python task {task['name']} needs exactly one entry activity")
        for edge in task['transitions']:
            if edge['source'] not in activities or edge['target'] not in activities:
                raise ValueError(f"Raw Python task {task['name']} contains a dangling transition")
        core_imports = ['Context', 'execute_with_policy', 'resolve', 'Reference', 'Template']
        if any(plan['type'] == 'critical_section' for plan in group_plans):
            core_imports.append('group_lock')
        lines = [
            '"""Direct async implementation of this MINA task."""',
            'import asyncio',
            f'from application.core import {", ".join(core_imports)}',
            *(['from application.native.jdbc import jdbc_adapter'] if any(plan['type'] == 'transaction_jdbc' for plan in group_plans) else []),
            '',
            f'TASK_ID = {task["id"]!r}',
            f'TASK_NAME = {task["name"]!r}',
            '',
            'async def run(ctx: Context, *, start_after: str | None = None, event_output=None, start_at: str | None = None):',
            '    injected_event_activity = start_after if start_at is None else None',
            f'    current = start_at if start_at is not None else ({starts[0]!r} if start_after is None else start_after)',
            '    steps = 0',
            '    handled_catches = set()',
            '    while current is not None:',
            '        steps += 1',
            '        if steps > 100000:',
            '            raise RuntimeError(f"Task {TASK_NAME} exceeded its execution step limit")',
        ]
        if group_plans:
            insertion = lines.index('    while current is not None:')
            lines[insertion:insertion] = [
                '    group_items = {}', '    group_indices = {}',
                '    transaction_connections = {}', '    transaction_resources = {}',
                '    critical_locks = {}', '    retry_remaining = {}', '    retry_iterations = {}',
            ]
        for plan in group_plans:
            if plan['type'] == 'if':
                lines.extend([
                    f'        if current == {plan["entry"]!r} and not ({plan["expression"]}):',
                    f'            current = {plan["exit_target"]!r}',
                    '            continue',
                ])
            elif plan['type'] in {'while', 'repeat'}:
                cfg = plan['config']
                group_id = plan['id']
                index_name = str(cfg.get('indexVariable') or 'index')
                lines.append(f'        if current == {plan["entry"]!r}:')
                if plan['type'] == 'while':
                    lines.append(f'            if not ({plan["expression"]}):')
                elif plan['expression']:
                    lines.append(f'            if group_indices.get({group_id!r}, 0) > 0 and ({plan["expression"]}):')
                else:
                    lines.append(f'            if group_indices.get({group_id!r}, 0) >= int(resolve({_direct_literal(cfg.get("count", cfg.get("iterations")))}, ctx)):')
                lines.extend([
                    f'                group_indices.pop({group_id!r}, None)',
                    f'                current = {plan["exit_target"]!r}',
                    '                continue',
                    f'            if group_indices.get({group_id!r}, 0) >= int(resolve({_direct_literal(cfg.get("maxIterations", 10000))}, ctx)):',
                    f'                raise RuntimeError({plan["id"]!r} + " exceeded maxIterations")',
                    f'            group_indices[{group_id!r}] = group_indices.get({group_id!r}, 0) + 1',
                    f'            ctx.variables[{index_name!r}] = group_indices[{group_id!r}]',
                    f"            ctx.variables['currentIndex'] = group_indices[{group_id!r}]",
                ])
            elif plan['type'] == 'transaction_jdbc':
                group_id = plan['id']
                lines.extend([
                    f'        if current == {plan["entry"]!r} and {group_id!r} not in transaction_connections:',
                    f'            transaction_resource_id = str(resolve({_direct_literal(plan["config"]["resourceId"])}, ctx))',
                    '            transaction_resource = ctx.resources.get(transaction_resource_id)',
                    '            if transaction_resource is None or transaction_resource.type != "jdbc":',
                    '                raise RuntimeError("JDBC transaction requires the configured shared connection")',
                    '            transaction_conn = await asyncio.to_thread(jdbc_adapter.connect, resolve(transaction_resource.config, ctx))',
                    f'            transaction_connections[{group_id!r}] = transaction_conn',
                    f'            transaction_resources[{group_id!r}] = transaction_resource_id',
                    '            ctx.transactions[transaction_resource_id] = transaction_conn',
                ])
            elif plan['type'] == 'critical_section':
                group_id = plan['id']
                lock_name = plan['config'].get('lockName') or f'{task["id"]}:{plan["id"]}'
                lines.extend([
                    f'        if current == {plan["entry"]!r} and {group_id!r} not in critical_locks:',
                    f'            critical_lock = group_lock(str(resolve({_direct_literal(lock_name)}, ctx)))',
                    '            await critical_lock.acquire()',
                    f'            critical_locks[{group_id!r}] = critical_lock',
                ])
            elif plan['type'] == 'repeat_on_error':
                cfg = plan['config']
                group_id = plan['id']
                index_name = str(cfg.get('indexVariable') or 'index')
                lines.extend([
                    f'        if current == {plan["entry"]!r} and {group_id!r} not in retry_remaining:',
                    f'            retry_remaining[{group_id!r}] = max(0, int(resolve({_direct_literal(cfg.get("retryCount", cfg.get("retries", 3)))}, ctx)))',
                    f'            retry_iterations[{group_id!r}] = 1',
                    f'            ctx.variables[{index_name!r}] = retry_iterations[{group_id!r}]',
                    f"            ctx.variables['currentIndex'] = retry_iterations[{group_id!r}]",
                ])
            else:
                cfg = plan['config']
                group_id = plan['id']
                source = cfg.get('collection', cfg.get('source'))
                if source in (None, ''):
                    start = _direct_literal(cfg.get('start', 1)); end = _direct_literal(cfg.get('end', 1)); increment = _direct_literal(cfg.get('increment', 1))
                    source_expr = f'range(int(resolve({start}, ctx)), int(resolve({end}, ctx)) + (1 if int(resolve({increment}, ctx)) > 0 else -1), int(resolve({increment}, ctx)))'
                else:
                    source_expr = f'resolve({_direct_literal(source)}, ctx)'
                item_name = str(cfg.get('currentElementName') or cfg.get('itemVariable') or 'currentElement')
                index_name = str(cfg.get('indexVariable') or 'index')
                accumulator = str(cfg.get('accumulatorVariable') or f'{plan["id"]}Results')
                lines.extend([
                    f'        if current == {plan["entry"]!r}:',
                    f'            if {group_id!r} not in group_items:',
                    f'                group_source = {source_expr}',
                    f'                group_items[{group_id!r}] = list(group_source.values()) if isinstance(group_source, dict) else list(group_source or [])',
                    f'                group_indices[{group_id!r}] = 0',
                ])
                if cfg.get('accumulateOutput'):
                    lines.append(f'                ctx.variables[{accumulator!r}] = []')
                lines.extend([
                    f'            if group_indices[{group_id!r}] >= len(group_items[{group_id!r}]):',
                    f'                group_items.pop({group_id!r}, None)',
                    f'                group_indices.pop({group_id!r}, None)',
                    f'                current = {plan["exit_target"]!r}',
                    '                continue',
                    f'            if group_indices[{group_id!r}] >= int(resolve({_direct_literal(cfg.get("maxIterations", 10000))}, ctx)):',
                    f'                raise RuntimeError({plan["id"]!r} + " exceeded maxIterations")',
                    f'            current_element = group_items[{group_id!r}][group_indices[{group_id!r}]]',
                    f'            ctx.variables[{item_name!r}] = current_element',
                    "            ctx.variables['currentElement'] = current_element",
                    f'            ctx.variables[{index_name!r}] = group_indices[{group_id!r}] + 1',
                    f"            ctx.variables['currentIndex'] = group_indices[{group_id!r}] + 1",
                    f'            group_indices[{group_id!r}] += 1',
                ])
        for index, activity in enumerate(task['activities']):
            prefix = 'if' if index == 0 else 'elif'
            config = activity.get('config') or {}
            outgoing = [edge for edge in task['transitions'] if edge['source'] == activity['id']]
            error_target = next((edge['target'] for edge in outgoing if edge.get('type') == 'error'), None)
            conditional = [edge for edge in outgoing if edge.get('type') == 'success_condition']
            ordinary = next((edge['target'] for edge in outgoing if _edge_type(edge) == 'success'), None)
            ordinary_targets = [edge['target'] for edge in outgoing if _edge_type(edge) == 'success']
            no_match = next((edge['target'] for edge in outgoing if edge.get('type') == 'success_no_match'), None)
            lines.extend([
                f'        {prefix} current == {activity["id"]!r}:',
                '            try:',
                '                if injected_event_activity == current:',
                '                    result = event_output',
                '                    injected_event_activity = None',
                '                else:',
                f'                    result = await execute_with_policy({activity["type"]!r}, {_direct_literal(config, 20)}, ctx, {activity["id"]!r}, {activity["name"]!r})',
                '            except Exception as error:',
                '                ctx.error = error',
            ])
            for plan in sorted(group_plans, key=lambda item: item.get('depth', 0), reverse=True):
                if activity['id'] not in set(plan.get('members') or []): continue
                if plan['type'] == 'transaction_jdbc':
                    group_id = plan['id']
                    lines.extend([
                        f'                if {group_id!r} in transaction_connections:',
                        f'                    transaction_conn = transaction_connections.pop({group_id!r})',
                        f'                    transaction_resource_id = transaction_resources.pop({group_id!r})',
                        '                    await asyncio.to_thread(transaction_conn.rollback)',
                        '                    await asyncio.to_thread(transaction_conn.close)',
                        '                    ctx.transactions.pop(transaction_resource_id, None)',
                    ])
                elif plan['type'] == 'critical_section':
                    group_id = plan['id']
                    lines.extend([
                        f'                if {group_id!r} in critical_locks:',
                        f'                    critical_lock = critical_locks.pop({group_id!r})',
                        '                    critical_lock.release()',
                    ])
                elif plan['type'] == 'repeat_on_error':
                    cfg = plan['config']
                    group_id = plan['id']
                    index_name = str(cfg.get('indexVariable') or 'index')
                    delay = _direct_literal(cfg.get('retryIntervalSeconds', cfg.get('retryDelaySeconds', 0)))
                    lines.extend([
                        f'                if retry_remaining.get({group_id!r}, 0) > 0:',
                        f'                    retry_remaining[{group_id!r}] -= 1',
                        f'                    retry_iterations[{group_id!r}] += 1',
                        f'                    ctx.variables[{index_name!r}] = retry_iterations[{group_id!r}]',
                        f"                    ctx.variables['currentIndex'] = retry_iterations[{group_id!r}]",
                        f'                    if not ({plan["expression"]}):',
                    ])
                    for member in sorted(plan['members']):
                        lines.append(f'                        ctx.outputs.pop({member!r}, None)')
                    lines.extend([
                        f'                        await asyncio.sleep(max(0.0, float(resolve({delay}, ctx))))',
                        f'                        current = {plan["entry"]!r}',
                        '                        continue',
                    ])
            lines.extend([
                f'                current = {error_target!r}',
                '                if current is None:',
                '                    fault_type = str(getattr(error, "fault_type", type(error).__name__))',
                '                    fault_code = str(getattr(error, "code", "") or "")',
            ])
            global_catches = [item for item in task['activities'] if item['type'] == 'catch' and
                              not any(edge.get('target') == item['id'] and edge.get('type') == 'error' for edge in task['transitions'])]
            for catch in global_catches:
                catch_cfg = catch.get('config') or {}
                catch_all = bool(catch_cfg.get('catchAll', True))
                catch_type = str(catch_cfg.get('errorType') or '')
                catch_code = str(catch_cfg.get('errorCode') or '')
                match = 'True' if catch_all else f'(fault_type == {catch_type!r} or (bool({catch_code!r}) and fault_code == {catch_code!r}))'
                lines.extend([
                    f'                    if current is None and {catch["id"]!r} not in handled_catches and {match}:',
                    f'                        handled_catches.add({catch["id"]!r})',
                    f'                        current = {catch["id"]!r}',
                ])
            lines.extend(['                if current is None: raise', '            else:', f'                ctx.record({activity["id"]!r}, result)'])
            if activity['type'] == 'end':
                lines.append('                return result')
            elif conditional:
                for condition_index, edge in enumerate(conditional):
                    condition = str(edge.get('condition') or '').strip()
                    expression = 'True' if condition.lower() == 'true' else 'False' if condition.lower() == 'false' else f'bool(resolve({_direct_literal(condition, 16)}, ctx))'
                    lines.append(f'                {"if" if condition_index == 0 else "elif"} {expression}: current = {edge["target"]!r}')
                lines.append(f'                else: current = {no_match!r}')
            elif len(ordinary_targets) > 1:
                calls = ', '.join(f'run(ctx.fork(), start_at={target!r})' for target in ordinary_targets)
                lines.extend([
                    f'                branch_results = await asyncio.gather({calls})',
                    '                return branch_results[-1] if branch_results else ctx.last',
                ])
            else:
                exits = [plan for plan in group_plans if plan['exit_source'] == activity['id']]
                boundary_exit = max(exits, key=lambda item: item.get('depth', 0), default=None)
                collection_exit = boundary_exit if boundary_exit and boundary_exit['type'] in {'for_each', 'iterate', 'while', 'repeat'} else None
                transaction_exit = boundary_exit if boundary_exit and boundary_exit['type'] == 'transaction_jdbc' else None
                critical_exit = boundary_exit if boundary_exit and boundary_exit['type'] == 'critical_section' else None
                retry_exit = boundary_exit if boundary_exit and boundary_exit['type'] == 'repeat_on_error' else None
                if collection_exit:
                    if collection_exit['config'].get('accumulateOutput'):
                        accumulator = str(collection_exit['config'].get('accumulatorVariable') or f'{collection_exit["id"]}Results')
                        lines.append(f'                ctx.variables[{accumulator!r}].append(ctx.last)')
                    lines.append(f'                current = {collection_exit["entry"]!r}')
                elif transaction_exit:
                    group_id = transaction_exit['id']
                    lines.extend([
                        f'                transaction_conn = transaction_connections.pop({group_id!r})',
                        f'                transaction_resource_id = transaction_resources.pop({group_id!r})',
                        '                await asyncio.to_thread(transaction_conn.commit)',
                        '                await asyncio.to_thread(transaction_conn.close)',
                        '                ctx.transactions.pop(transaction_resource_id, None)',
                        f'                current = {ordinary!r}',
                    ])
                elif critical_exit:
                    group_id = critical_exit['id']
                    lines.extend([
                        f'                critical_lock = critical_locks.pop({group_id!r})',
                        '                critical_lock.release()',
                        f'                current = {ordinary!r}',
                    ])
                elif retry_exit:
                    group_id = retry_exit['id']
                    lines.extend([f'                retry_remaining.pop({group_id!r}, None)',
                                  f'                retry_iterations.pop({group_id!r}, None)', f'                current = {ordinary!r}'])
                else:
                    lines.append(f'                current = {ordinary!r}')
        lines.extend([
            '        else:',
            '            raise RuntimeError(f"Unknown activity {current!r} in {TASK_NAME}")',
            '    return ctx.last',
            '',
        ])
        if any(plan['type'] in {'transaction_jdbc', 'critical_section'} for plan in group_plans):
            start = lines.index('    while current is not None:')
            body = lines[start:-1]
            lines[start:-1] = ['    try:', *(f'    {line}' for line in body), '    finally:']
            lines.extend([
                '        for group_id, transaction_conn in list(transaction_connections.items()):',
                '            transaction_resource_id = transaction_resources.get(group_id)',
                '            try: await asyncio.to_thread(transaction_conn.rollback)',
                '            finally:',
                '                await asyncio.to_thread(transaction_conn.close)',
                '                if transaction_resource_id: ctx.transactions.pop(transaction_resource_id, None)',
                '        for critical_lock in list(critical_locks.values()):',
                '            if critical_lock.locked(): critical_lock.release()',
            ])
        files[f'application/tasks/{task_modules[task["id"]]}.py'] = ('\n'.join(lines)).encode('utf-8')
    for name, body in files.items():
        if name.endswith('.py'):
            try:
                compile(body, name, 'exec')
            except SyntaxError as error:
                raise ValueError(f'Generated Python is invalid in {name}: {error}') from error
    return files


ENGINE_CAPABILITY_MODULES = {
    'dataweave': 'dataweave', 'sap': 'sap', 'snowflake': 'snowflake',
    'jdbc': 'jdbc', 'amqp': 'amqp', 'ems': 'java_bridge',
    'jms': 'java_bridge', 'pubsub': 'google_pubsub',
}


def _engine_lazy_imports(source: str, modules: set[str], package: str) -> str:
    """Defer optional connector imports until the corresponding code executes.

    Shared engine methods also serve notebooks and event listeners. Keeping
    their imports lazy allows the selected engine to load without shipping
    unrelated connectors, while preserving the original implementation.
    """
    tree = ast.parse(source)
    symbols = {}
    for node in list(tree.body):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in modules:
            for alias in node.names:
                symbols[alias.asname or alias.name] = (node.module, alias.name)
            tree.body.remove(node)

    class LazyImports(ast.NodeTransformer):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id in symbols:
                module, name = symbols[node.id]
                return ast.copy_location(ast.Attribute(
                    value=ast.Call(func=ast.Name(id='_load_engine_module', ctx=ast.Load()),
                                   args=[ast.Constant(f'{package}.{module}')], keywords=[]),
                    attr=name, ctx=ast.Load()), node)
            return node

    tree = LazyImports().visit(tree)
    if symbols:
        # Insert after the module docstring and future imports.
        index = 0
        while index < len(tree.body) and (isinstance(tree.body[index], ast.Expr) or
                isinstance(tree.body[index], ast.ImportFrom) and tree.body[index].module == '__future__'):
            index += 1
        tree.body.insert(index, ast.ImportFrom(module='importlib', names=[ast.alias(name='import_module', asname='_load_engine_module')], level=0))
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def _engine_module_files(project: dict, source_root: Path) -> dict[str, bytes]:
    """Link the connector and transitive module closure for packaged tasks."""
    kinds = {activity['type'] for task in project.get('tasks', []) for activity in task.get('activities', [])}
    groups = {group['type'] for task in project.get('tasks', []) for group in task.get('groups', [])}
    if 'transaction_jdbc' in groups:
        kinds.add('jdbc')
    optional = set(ENGINE_CAPABILITY_MODULES.values())
    pending = {'runtime', 'models', 'mapper', 'time_utils'}
    pending.update(module for kind, module in ENGINE_CAPABILITY_MODULES.items() if kind in kinds)
    files = {}
    while pending:
        module = pending.pop()
        filename = f'application/engine/{module}.py'
        if filename in files:
            continue
        source = (source_root / f'{module}.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.level != 1 or not node.module or '.' in node.module:
                    raise ValueError(f'Engine dependency needs a linker rule: {module}: {ast.unparse(node)}')
                # Only runtime dispatch imports are capability-dependent.
                # Adapter dependencies (e.g. SAP/JDBC -> Java bridge) are mandatory.
                if module != 'runtime' or node.module not in optional:
                    pending.add(node.module)
        if module == 'runtime':
            source = _engine_lazy_imports(source, optional, 'application.engine')
        files[filename] = source.encode('utf-8')
    return files


def _python_literal(value, indent: int) -> str:
    if isinstance(value, dict) and all(isinstance(key, str) and key.isidentifier() and not keyword.iskeyword(key) for key in value):
        if not value:
            return 'dict()'
        pad = ' ' * indent
        parts = [f'{pad}    {key}={_python_literal(item, indent + 4)},' for key, item in value.items()]
        return 'dict(\n' + '\n'.join(parts) + f'\n{pad})'
    rendered = pformat(value, width=88, sort_dicts=False)
    return rendered.replace('\n', '\n' + ' ' * indent)


def _python_call(name: str, values: dict, fields: tuple[str, ...], indent: int = 8) -> str:
    """Emit readable Python constructor arguments instead of a model-dump blob."""
    pad = ' ' * indent
    arguments = []
    for field in fields:
        if field not in values:
            continue
        rendered = _python_literal(values[field], indent + 4)
        arguments.append(f'{pad}    {field}={rendered},')
    return f'{name}(\n' + '\n'.join(arguments) + f'\n{pad})'


def engine_python_files(project: dict, profiles: dict[str, list[dict]]) -> dict[str, bytes]:
    """Compile every persisted activity/group to Python model constructors.

    The bundled engine is the exact Python execution implementation used by
    Studio, including its SAP JCo and EMS/JMS bridges. Vendor runtimes/JARs
    remain external licensed dependencies of the target data plane.
    """
    source_root = Path(__file__).parent
    support = source_root / 'raw_python_support'
    files: dict[str, bytes] = {
        'application/__init__.py': (support / '__init__.py').read_bytes(),
        'application/main.py': _engine_lazy_imports(
            (support / 'engine_main.py').read_text(encoding='utf-8'),
            {'engine.sap'}, 'application').encode('utf-8'),
        'application/tasks/__init__.py': b'"""Generated task modules."""\n',
        'application/engine/__init__.py': b'"""Bundled Python execution engine."""\n',
    }
    files.update(_engine_module_files(project, source_root))
    task_imports: list[str] = []
    task_calls: list[str] = []
    for index, task in enumerate(project['tasks']):
        module = f'task_{index}_{_identifier(str(task["id"]))}'
        task_imports.append(f'from .tasks.{module} import build_task as build_task_{index}')
        task_calls.append(f'build_task_{index}()')
        attributes = {key: value for key, value in task.items() if key not in {'activities', 'transitions', 'groups'}}
        activities = ',\n        '.join(
            _python_call('Activity', activity, ('id', 'type', 'name', 'config'))
            for activity in task['activities'])
        transitions = ',\n        '.join(
            _python_call('Transition', edge, ('id', 'source', 'target', 'label', 'type', 'condition'))
            for edge in task['transitions'])
        groups = ',\n        '.join(
            _python_call('GroupDefinition', group, ('id', 'type', 'name', 'member_activity_ids', 'config', 'parent_group_id'))
            for group in task.get('groups', []))
        task_header = _python_call('TaskDefinition', attributes, ('id', 'name', 'kind', 'description', 'input_schema', 'output_schema'), 4)
        task_header = task_header.rsplit('\n', 1)[0] + '\n'
        files[f'application/tasks/{module}.py'] = (
            '"""Executable Python task definition and async entry point."""\n'
            'from application.engine.models import Activity, GroupDefinition, TaskDefinition, Transition\n'
            'from application.engine.runtime import WorkflowRuntime\n\n'
            'def build_task() -> TaskDefinition:\n'
            f'    return {task_header}'
            f'        activities=[{activities}],\n'
            f'        transitions=[{transitions}],\n'
            f'        groups=[{groups}],\n'
            '    )\n\n'
            'async def run(initial=None, *, resources=None, properties=None, project=None):\n'
            '    """Run this task directly from a notebook or Python caller."""\n'
            '    return await WorkflowRuntime().run(build_task(), initial or {}, resources or {}, properties or {}, project=project)\n'
        ).encode('utf-8')
    project_fields = {key: value for key, value in project.items()
                      if key not in {'tasks', 'resources', 'schemas', 'properties', 'custom_functions', 'process'}}
    resources = ',\n        '.join(_python_call('SharedResource', value, ('id', 'type', 'name', 'config')) for value in project['resources'])
    schemas = ',\n        '.join(_python_call('SchemaAsset', value, ('id', 'name', 'content')) for value in project.get('schemas', []))
    functions = ',\n        '.join(_python_call('CustomFunction', value, ('id', 'name', 'parameters', 'expression', 'description')) for value in project.get('custom_functions', []))
    profile_lines = ',\n        '.join(
        f'{name!r}: [{", ".join(_python_call("EnvironmentProperty", value, ("key", "value", "data_type")) for value in values)}]'
        for name, values in profiles.items())
    project_header = _python_call('Project', project_fields, ('id', 'name', 'description', 'active_environment', 'active_task_id'), 4).rsplit('\n', 1)[0] + '\n'
    files['application/project.py'] = (
        '"""Typed Python application assembly; no Fabric descriptor is loaded."""\n'
        'from .engine.models import CustomFunction, EnvironmentProperty, Project, SchemaAsset, SharedResource\n'
        + '\n'.join(task_imports) + '\n\n'
        'def build_project() -> Project:\n'
        f'    return {project_header}'
        f'        resources=[{resources}],\n'
        f'        schemas=[{schemas}],\n'
        f'        custom_functions=[{functions}],\n'
        f'        properties={{ {profile_lines} }},\n'
        f'        tasks=[{", ".join(task_calls)}])\n'
    ).encode('utf-8')
    for name, body in files.items():
        if name.endswith('.py'):
            try: compile(body, name, 'exec')
            except SyntaxError as error:
                raise ValueError(f'Generated Python is invalid in {name}: {error}') from error
    return files
