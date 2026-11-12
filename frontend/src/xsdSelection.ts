export const XSD_SELECTION_NS = 'urn:mina:schema-selection';
const XS = 'http://www.w3.org/2001/XMLSchema';
const XMLNS = 'http://www.w3.org/2000/xmlns/';
type Structure = {id:string;name:string;kind:string};
const metadataCache=new Map<string,{options:Structure[];selection:string}>();
const resolvedCache:{source:string;selection:string;text:string}[]=[];
function documentFor(text: string) {
  if (!text?.trimStart().startsWith('<')) return;
  const doc=new DOMParser().parseFromString(text,'application/xml');
  if (doc.querySelector('parsererror') || doc.documentElement.namespaceURI!==XS || doc.documentElement.localName!=='schema') return;
  return doc;
}
function metadata(text: string) {
  const cached=metadataCache.get(text);if(cached)return cached;
  const doc=documentFor(text);if (!doc) return {options:[],selection:''};
  const root=doc.documentElement, ns=root.getAttribute('targetNamespace') || '';
  const options=Array.from(root.children || []).filter(node=>node.namespaceURI===XS && ['element','complexType'].includes(node.localName)
    && node.getAttribute('name') && !node.hasAttributeNS(XSD_SELECTION_NS,'generated')).map(node=>({
    id:`${node.localName==='element'?'element':'type'}|{${ns}}${node.getAttribute('name')}`,
    name:node.getAttribute('name')!,kind:node.localName==='element'?'Element':'Complex type',
  }));
  const value={options,selection:root.getAttributeNS(XSD_SELECTION_NS,'structure') || ''};
  metadataCache.set(text,value);if(metadataCache.size>4)metadataCache.delete(metadataCache.keys().next().value!);
  return value;
}
export function xsdStructures(text: string) {return metadata(text).options;}
export function xsdSelection(text: string) {
  return metadata(text).selection;
}
function explicitSchemaNamespace(doc:Document,root:Element) {
  let prefix=Array.from(root.attributes).find(attribute=>attribute.namespaceURI===XMLNS&&attribute.localName!=='xmlns'&&attribute.value===XS)?.localName || 'minaXsd';
  while(root.lookupNamespaceURI(prefix) && root.lookupNamespaceURI(prefix)!==XS)prefix+='X';
  const replacement=doc.createElementNS(XS,prefix+':schema');
  for(const attribute of Array.from(root.attributes))if(attribute.name!=='xmlns')replacement.setAttributeNS(attribute.namespaceURI,attribute.name,attribute.value);
  replacement.setAttributeNS(XMLNS,'xmlns:'+prefix,XS);
  for(const node of [root,...Array.from(root.getElementsByTagNameNS(XS,'*'))]){
    if(node.lookupNamespaceURI(null)!==XS)continue;
    for(const attribute of ['type','base','ref','itemType','memberTypes','substitutionGroup','refer']){
      const value=node.getAttribute(attribute);
      if(value)node.setAttribute(attribute,value.split(/\s+/).map(value=>value.includes(':')?value:prefix+':'+value).join(' '));
    }
  }
  while(root.firstChild)replacement.appendChild(root.firstChild);
  doc.replaceChild(replacement,root);
  return replacement;
}
export function selectXsdStructure(text: string, selection?: string) {
  const doc=documentFor(text);if (!doc) return text;
  let root:Element=doc.documentElement;
  const options=xsdStructures(text), id=selection || xsdSelection(text) || options.find(option=>option.kind==='Element')?.id || options[0]?.id;
  if (!id) return text;
  const chosen=options.find(option=>option.id===id);
  if (!chosen) throw new Error('The selected XSD structure is no longer available. Choose another structure.');
  for (const node of Array.from(root.children || [])) if (node.hasAttributeNS(XSD_SELECTION_NS,'generated')) node.remove();
  const ns=root.getAttribute('targetNamespace') || '';
  let element=Array.from(root.children || []).find(node=>node.namespaceURI===XS && node.localName==='element' && node.getAttribute('name')===chosen.name);
  if (chosen.kind==='Complex type') {
    if(!ns && root.lookupNamespaceURI(null)===XS)root=explicitSchemaNamespace(doc,root);
    // Keep all global declarations for refs; synthesize a distinct typed entry.
    let name=chosen.name;
    const names=new Set(Array.from(root.children || []).filter(node=>node.localName==='element').map(node=>node.getAttribute('name')));
    while(names.has(name)) name+='Root';
    element=doc.createElementNS(XS,`${root.prefix || 'xs'}:element`);
    element.setAttribute('name',name);
    let type=chosen.name;
    if (ns) {let prefix=root.lookupPrefix(ns);if (!prefix) {prefix='minaType';let i=1;while(root.lookupNamespaceURI(prefix))prefix=`minaType${i++}`;root.setAttributeNS(XMLNS,`xmlns:${prefix}`,ns);}type=prefix+':'+type;}
    else if (root.lookupNamespaceURI(null)) element.setAttributeNS(XMLNS,'xmlns','');
    element.setAttribute('type',type);
    element.setAttributeNS(XSD_SELECTION_NS,'minaSelection:generated','true');
  }
  if (!element) throw new Error('The selected XSD element is unavailable.');
  // XSD imports/includes must precede declarations. Reorder only among declarations.
  const first=Array.from(root.children || []).find(node=>['element','complexType','simpleType','group','attributeGroup','attribute'].includes(node.localName));
  root.insertBefore(element,first || null);
  root.setAttributeNS(XSD_SELECTION_NS,'minaSelection:structure',id);
  root.setAttributeNS(XSD_SELECTION_NS,'minaSelection:element',`{${ns}}${element.getAttribute('name')}`);
  return new XMLSerializer().serializeToString(doc);
}
export function selectedSchemaText(source: string, snapshot?: string) {
  const selection=snapshot && xsdSelection(snapshot);
  if (!selection) return source;
  const cached=resolvedCache.find(item=>item.source===source&&item.selection===selection);
  if(cached)return cached.text;
  const remember=(text:string)=>{resolvedCache.unshift({source,selection,text});if(resolvedCache.length>4)resolvedCache.pop();return text;};
  if (xsdStructures(source).some(option=>option.id===selection)) return remember(selectXsdStructure(source,selection));
  // Keep an unavailable choice visible and repairable after an asset edit.
  // Do not crash the editor or silently switch to another document root.
  const doc=documentFor(source);
  if (!doc) return source;
  doc.documentElement.setAttributeNS(XSD_SELECTION_NS,'minaSelection:structure',selection);
  doc.documentElement.setAttributeNS(XSD_SELECTION_NS,'minaSelection:element','#unavailable');
  return remember(new XMLSerializer().serializeToString(doc));
}
