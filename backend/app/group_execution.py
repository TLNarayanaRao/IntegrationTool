"""Value helpers shared by studio group execution and standalone exports."""
import re
from collections.abc import Sequence

ROUTED_GROUPS = frozenset(('parallel_for_each', 'scatter_gather', 'first_successful', 'async'))
MULTI_ROUTE_GROUPS = frozenset(('scatter_gather', 'first_successful'))


def partition_routes(entries, members, transitions):
    outgoing = {member: [] for member in members}
    for edge in transitions:
        if edge.source in members and edge.target in members:
            outgoing[edge.source].append(edge.target)
    routes, used = [], set()
    for entry in entries:
        pending, route = [entry], set()
        while pending:
            activity = pending.pop()
            if activity in route:
                continue
            route.add(activity)
            pending.extend(outgoing[activity])
        if route & used:
            raise ValueError('Group routes must be disjoint and join outside the group')
        routes.append((entry, route))
        used.update(route)
    if used != members:
        raise ValueError('Every group activity must belong to a reachable route')
    return routes


class _Batches(Sequence):
    def __init__(self, source, size):
        self.source = source
        self.size = size

    def __len__(self):
        return (len(self.source) + self.size - 1) // self.size

    def __getitem__(self, index):
        if not 0 <= index < len(self):
            raise IndexError(index)
        start = index * self.size
        return list(self.source[start:start + self.size])


def iteration_items(source, batch_size=1):
    size = int(batch_size)
    if isinstance(batch_size, bool) or size < 1 or float(batch_size) != size:
        raise ValueError('Group batch size must be a positive integer')
    if isinstance(source, dict):
        source = list(source.values())
    elif source is None:
        source = []
    elif not isinstance(source, (list, tuple, range)):
        raise ValueError('Group iteration requires an array, an object, or a numeric range')
    if size == 1:
        return source
    return _Batches(source, size)


def scope_variables(config):
    variables = config.get('localVariables', [])
    if not isinstance(variables, list):
        raise ValueError('Group local variables must be a list')
    names = set()
    for variable in variables:
        name = variable.get('name') if isinstance(variable, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name in names:
            raise ValueError('Group local variables require unique identifier names')
        names.add(name)
    return variables


def scope_fault_action(config, fault):
    for handler in config.get('faultHandlers', []):
        types = {value.strip() for value in handler.get('types', []) if value.strip()}
        if not types or fault['type'] in types or fault['code'] and fault['code'] in types:
            return handler
    return None
