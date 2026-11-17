/** Normalize JSON samples/compact field definitions for the shared schema tree. */
export function mappingSchemaDefinition(value:any):any {
  let visited=0;
  const types=new Set(['object','array','string','integer','number','boolean','null','any']);
  const definition=(v:any)=>v && typeof v==='object' && !Array.isArray(v) &&
    (v.properties || v.$ref || v.$defs || v.definitions || v.$schema || v.oneOf || v.anyOf || v.allOf ||
      typeof v.type==='string' && types.has(v.type) || Array.isArray(v.type));
  const merge=(a:any,b:any):any=>{
    if(a.unobserved)return b;if(b.unobserved)return a;
    if(a.type===b.type && a.type==='object') {
      const properties=Object.assign(Object.create(null),a.properties);
      for(const [k,v] of Object.entries(b.properties))properties[k]=Object.prototype.hasOwnProperty.call(properties,k)?merge(properties[k],v):v;
      return {type:'object',properties};
    }
    if(a.type===b.type && a.type==='array')return {type:'array',items:merge(a.items,b.items)};
    if(a.type===b.type)return a;
    if(['integer','number'].includes(a.type) && ['integer','number'].includes(b.type))return {type:'number'};
    if(a.type==='null')return {...b,type:[b.type,'null'].flat()};
    if(b.type==='null')return {...a,type:[a.type,'null'].flat()};
    return {type:'any'};
  };
  const infer=(v:any,depth=0):any=>{
    if(++visited>20000 || depth>64)throw Error('Schema sample exceeds 20000 values or 64 levels');
    if(definition(v))return v;
    if(Array.isArray(v)) {
      let items:any={type:'any',unobserved:true};
      for(const item of v.slice(0,32))items=merge(items,infer(item,depth+1));
      return {type:'array',items};
    }
    if(v && typeof v==='object') {
      const properties=Object.create(null);
      for(const [k,child] of Object.entries(v))properties[k]=infer(child,depth+1);
      return {type:'object',properties};
    }
    return {type:v===null?'null':typeof v==='number' && Number.isInteger(v)?'integer':typeof v};
  };
  return infer(value);
}
