/** Preserve transition order while computing branch lanes in linear time. */
export function transitionLanes<T extends { source: string }>(edges: readonly T[]): number[] {
  const counts = new Map<string, number>();
  for (const edge of edges) counts.set(edge.source, (counts.get(edge.source) || 0) + 1);
  const offsets = new Map<string, number>();
  return edges.map(edge => {
    const offset = offsets.get(edge.source) || 0;
    offsets.set(edge.source, offset + 1);
    return offset - ((counts.get(edge.source) || 1) - 1) / 2;
  });
}
