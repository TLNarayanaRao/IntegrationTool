export function studioObjectName(value: string): string {
  return value.trim().replace(/\s+/g, "-");
}

export type NamedPackageObject = {id:string; name:string; package_path?:string};
type ObjectCategory = 'tasks' | 'resources' | 'schemas';
type NamedWorkspace = Record<ObjectCategory, readonly NamedPackageObject[]>;
const categories = {tasks:'task', resources:'connection', schemas:'schema'} as const;
export const studioNameKey = (value:string) => studioObjectName(value).normalize('NFKC').toLowerCase();

export function workspaceNameConflict(workspace:NamedWorkspace, name:string, folder:string, exclude?:{category:ObjectCategory; id:string}): string {
  const key = studioNameKey(name);
  if (!key) return 'Enter a name.';
  for (const category of Object.keys(categories) as ObjectCategory[]) {
    const existing = workspace[category].find(item => !(category === exclude?.category && item.id === exclude.id) &&
      studioNameKey(item.package_path || 'Default') === studioNameKey(folder || 'Default') && studioNameKey(item.name) === key);
    if (existing) return `A ${categories[category]} named “${existing.name}” already exists in package “${folder}”. Choose a different name or package.`;
  }
  return '';
}

export function schemaObjectName(value:string, previous = '') {
  const name = studioObjectName(value);
  const extension = previous.match(/\.[^./]+$/)?.[0] || '.xsd';
  return !name || name.toLowerCase().endsWith(extension.toLowerCase()) ? name : name + extension;
}

export function resolveWorkspaceSubtask<T extends NamedPackageObject & {kind:string}>(tasks: readonly T[], reference: string): T | undefined {
  const subtasks = tasks.filter(task => task.kind === 'subtask');
  const byId = subtasks.find(task => task.id === reference);
  if (byId) return byId;
  const key = (value:string) => value.split('/').map(studioNameKey).join('/');
  const matches = subtasks.filter(task => key(reference.includes('/') ? `${task.package_path || 'Default'}/${task.name}` : task.name) === key(reference));
  return matches.length === 1 ? matches[0] : undefined;
}
