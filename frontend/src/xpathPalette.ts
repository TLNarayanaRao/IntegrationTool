import {xpathCatalog,type XPathFunction} from './xpath-catalog';
export type {XPathFunction};
const blocked=new Set(['doc','doc-available','collection','unparsed-text','unparsed-text-available','json-doc','trace']);
export function bundledXPathFunctions(version:string) {
  return xpathCatalog[version] || [];
}
export function designerXPathFunctions(version:string,live?:XPathFunction[]):XPathFunction[] {
  const bundled=bundledXPathFunctions(version);
  if(!live?.length)return bundled;
  return live.filter(item=>!blocked.has(item.name)).map(item=>{
    const fallback=bundled.find(entry=>entry.name===item.name&&entry.args.length===item.args.length);
    return {...fallback,...item,description:item.description||fallback?.description||item.signature,
      args:item.args.every(label=>/^argument \d+$/.test(label))&&fallback ? fallback.args : item.args};
  });
}
export function xpathFunctionExpression(name:string,args:string[],version:string) {
  return `xpath${version==='2.0'?'2':'1'}(${JSON.stringify(`${name}(${args.join(', ')})`)})`;
}

export function xpathSuggestions(prefix:string) {
  const token=prefix.match(/[\w:-]+$/)?.[0] || '';
  const inside=prefix.match(/xpath([12]?)\(\s*(["'])([\s\S]*)$/);
  if(!token || /\$\{[^}]*$/.test(prefix) || !inside && /(?:'[^']*|"[^"]*)$/.test(prefix))return [];
  const version=inside?.[1]==='1'?'1.0':'2.0';
  const seen=new Set<string>();
  return bundledXPathFunctions(version).filter(entry=>entry.name.toLowerCase().startsWith(token.toLowerCase()))
    .filter(entry=>{if(seen.has(entry.name))return false;seen.add(entry.name);return true;})
    .map(entry=>({label:`XPath ${version} · ${entry.name}(${entry.args.join(', ')})`,needsArguments:entry.args.length>0,
      insert:inside ? `${entry.name}()` : xpathFunctionExpression(entry.name,[],version)}));
}
