/** Recover a schema from upstream contract metadata without loading sample values. */
export function schemaFromActivityFields(fields:any[]) {
  const root:any = {type:"object",properties:{}};
  const valid = (Array.isArray(fields) ? fields : []).filter(field=>field && typeof field.key==="string" && field.key);
  const parents = new Set<string>();
  for (const field of valid) {
    const parts=field.key.split(".");
    for(let i=1;i<parts.length;i++) parents.add(parts.slice(0,i).join("."));
  }
  const sorted = [...valid].sort((a,b)=>a.key.split(".").length-b.key.split(".").length);
  for (const field of sorted) {
    if (typeof field.key !== "string" || !field.key) continue;
    const parts = field.key.split(".");
    if (parts.some((name:string)=>!name || ["__proto__","prototype","constructor"].includes(name) || /[\[\]]/.test(name))) continue;
    let node = root, insideArray = false;
    parts.forEach((name:string,index:number) => {
      if (node.type === "array") {node=node.items;insideArray=true;}
      node.properties ||= Object.create(null);
      if (index < parts.length-1) {node=node.properties[name] ||= {type:"object",properties:Object.create(null)};return;}
      const raw = String(field.type || "any").replace(/\[\]$/,"").toLowerCase();
      const children = parents.has(field.key);
      const type = children ? "object" : ["string","boolean","integer","number"].includes(raw) ? raw :
        ["int","long","short"].includes(raw) ? "integer" : ["float","double","decimal"].includes(raw) ? "number" : "any";
      const repeat = /\[\]$/.test(field.type || "") || field.maxOccurs === "unbounded" || Number(field.maxOccurs)>1 ||
        (field.repeating === true && field.maxOccurs === undefined && !insideArray);
      const previous = node.properties[name];
      const value:any = type === "object" ? {type,properties:previous?.properties || previous?.items?.properties || Object.create(null)} : {type};
      node.properties[name] = repeat ? {type:"array",items:value} : value;
    });
  }
  return root;
}
