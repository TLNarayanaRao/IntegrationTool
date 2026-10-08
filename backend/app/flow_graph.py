"""Find convergence barriers without depending on connector or project models."""
from collections import deque
import asyncio
import copy


def parallel_join(edges, targets, terminals=(), boundary=None, fork=None):
    """Return the nearest node every successful branch must pass through.

    Conditional alternatives are included; error handlers are separate flows.
    A branch that terminates before a candidate prevents that candidate joining.
    The enclosing barrier bounds nested forks.
    """
    outgoing = {}
    for source, target, kind in edges:
        if kind != 'error': outgoing.setdefault(source, []).append(target)
    terminals = set(terminals)
    if boundary is not None: terminals.add(boundary)
    distances = []
    for target in targets:
        found = {target: 0}
        pending = deque([target])
        while pending:
            node = pending.popleft()
            if node in terminals: continue
            for child in outgoing.get(node, ()):
                if child not in found:
                    found[child] = found[node] + 1
                    pending.append(child)
        distances.append(found)
    if not distances: return None
    candidates = set(distances[0]).intersection(*(set(item) for item in distances[1:]))
    candidates.discard(fork)
    for candidate in sorted(candidates, key=lambda node: (max(item[node] for item in distances), sum(item[node] for item in distances), node)):
        pending, seen, valid = list(targets), set(), True
        while pending:
            node = pending.pop()
            if node == candidate or node in seen: continue
            seen.add(node)
            children = outgoing.get(node, ())
            if node in terminals or not children:
                valid = False
                break
            pending.extend(children)
        if valid: return candidate
    return None


def parallel_plan(edges, targets, terminals=(), boundary=None, fork=None):
    """Group partial convergences as well as an enclosing all-branch join."""
    join = parallel_join(edges, targets, terminals, boundary, fork)
    outgoing = {}
    for source, target, kind in edges:
        if kind != 'error': outgoing.setdefault(source, []).append(target)
    stops = set(terminals)
    if join or boundary: stops.add(join or boundary)
    owners = {}
    for index, target in enumerate(targets):
        pending, seen = deque([(target, 0)]), set()
        while pending:
            node, distance = pending.popleft()
            if node in seen: continue
            seen.add(node)
            owners.setdefault(node, []).append((index, distance))
            if node not in stops:
                pending.extend((child, distance + 1) for child in outgoing.get(node, ()))
    candidates = sorted((node for node, items in owners.items() if 1 < len(items) < len(targets) and node not in (join, boundary, fork)),
                        key=lambda node: (max(distance for _, distance in owners[node]), node))
    remaining = list(enumerate(targets))
    branches = []
    while remaining:
        subset = None
        for candidate in candidates:
            indices = {index for index, _ in owners[candidate]}
            possible = [(index, target) for index, target in remaining if index in indices]
            if len(possible) < 2: continue
            subset = [(index, target) for index, target in possible
                      if parallel_join(edges, [target, candidate], terminals, join or boundary, fork) == candidate]
            if len(subset) > 1: break
        if subset and len(subset) > 1:
            indices = {index for index, _ in subset}
            part = parallel_plan(edges, [target for _, target in subset], terminals, candidate, fork)
            branches.append((max(indices), part))
            remaining = [item for item in remaining if item[0] not in indices]
        else:
            branches.extend(remaining)
            break
    return {'join': join, 'branches': [part for _, part in sorted(branches, key=lambda item: item[0])]}


async def execute_parallel(plan, run_branch, initial, boundary=None):
    """Run a convergence tree, settling siblings before raising failures."""
    stop = plan['join'] or boundary
    async def execute(part):
        if isinstance(part, str):
            return await run_branch(part, stop, copy.deepcopy(initial))
        values = await execute_parallel(part, run_branch, initial, stop)
        value = values[-1] if values else initial
        return await run_branch(part['join'], stop, value) if part['join'] is not None else value
    values = await asyncio.gather(*(execute(part) for part in plan['branches']), return_exceptions=True)
    for value in values:
        if isinstance(value, BaseException): raise value
    return values
