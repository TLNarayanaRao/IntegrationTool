const XSD = 'http://www.w3.org/2001/XMLSchema';
const xsdTypes: Record<string, string> = {string:'string', integer:'integer', number:'decimal', boolean:'boolean', null:'string'};

export function editMapperXsd(text: string, path: string[], type: string, required: boolean, repeating: boolean, remove: boolean, nillable?: boolean) {
  const document = new DOMParser().parseFromString(text, 'application/xml');
  const schema = document.documentElement;
  if (schema.namespaceURI !== XSD || schema.localName !== 'schema') throw new Error('Enter a valid XML Schema document');
  const children = (node: Element, kind: string) => Array.from(node.children).filter(child => child.namespaceURI === XSD && child.localName === kind);
  const create = (kind: string) => document.createElementNS(XSD, schema.prefix ? `${schema.prefix}:${kind}` : kind);
  const target = path[path.length - 1];
  let container: Element = schema;
  for (const part of path.slice(0, -1)) {
    const element = children(container, 'element').find(child => child.getAttribute('name') === part);
    if (!element) throw new Error(`Create the parent field ${part} first`);
    let complex = children(element, 'complexType')[0];
    const reference = element.getAttribute('type');
    if (!complex && reference) {
      const [prefix, name] = reference.includes(':') ? reference.split(':') : [null, reference];
      if ((element.lookupNamespaceURI(prefix) || '') === (schema.getAttribute('targetNamespace') || '')) {
        complex = children(schema, 'complexType').find(child => child.getAttribute('name') === name)!;
      }
    }
    const group = complex && Array.from(complex.children).find(child => child.namespaceURI === XSD && ['sequence','choice','all'].includes(child.localName));
    if (!group) throw new Error(`${part} must contain a local complex type with an element group`);
    container = group;
  }
  if (!remove && repeating && (container === schema || container.localName === 'all')) throw new Error('This XSD group does not permit repeating elements');
  const existing = children(container, 'element').find(child => child.getAttribute('name') === target);
  if (remove) existing?.remove();
  else {
    const element = existing || create('element');
    element.setAttribute('name', target);
    if (container !== schema) {
      element.setAttribute('minOccurs', required ? '1' : '0');
      element.setAttribute('maxOccurs', repeating ? 'unbounded' : '1');
    }
    if (type === 'object') {
      if (children(element, 'simpleType').length) throw new Error('Edit the XSD to replace the existing inline type');
      if (!children(element, 'complexType').length && !element.hasAttribute('type')) {
        const complex = create('complexType');
        complex.append(create('sequence'));
        element.append(complex);
      } else if (element.hasAttribute('type')) {
        const ref = element.getAttribute('type')!;
        const [prefix, name] = ref.includes(':') ? ref.split(':') : [null, ref];
        if ((element.lookupNamespaceURI(prefix) || '') !== (schema.getAttribute('targetNamespace') || '') ||
          !children(schema, 'complexType').some(child => child.getAttribute('name') === name)) throw new Error('This field uses a scalar or external type. Edit its XSD to replace the type.');
      }
    } else {
      const builtIn = xsdTypes[type];
      if (!builtIn) throw new Error('Unsupported XSD field type');
      if (children(element, 'complexType').length || children(element, 'simpleType').length) throw new Error('Edit the XSD to replace an existing inline type');
      let prefix = schema.lookupPrefix(XSD);
      if (!prefix) {
        prefix = 'xs';
        while (schema.lookupNamespaceURI(prefix)) prefix += '_';
        schema.setAttributeNS('http://www.w3.org/2000/xmlns/', `xmlns:${prefix}`, XSD);
      }
      element.setAttribute('type', `${prefix}:${builtIn}`);
    }
    if (type === 'null' || nillable === true) element.setAttribute('nillable', 'true');
    else if (nillable === false) element.removeAttribute('nillable');
    if (!existing) container.append(element);
  }
  return new XMLSerializer().serializeToString(document);
}
