"""Local, reviewable schema mapping plans. Never sends payloads to an AI service."""
import copy
import json
import math
import re
from collections import defaultdict

from .mapper import local_schema_target

PROFILES = {
    'general': [('identifier', 'id'), ('telephone', 'phone'), ('zip', 'postal'), ('surname', 'lastname'), ('givenname', 'firstname')],
    'commerce': [('client', 'customer'), ('buyer', 'customer'), ('purchase', 'order'), ('product', 'item'), ('sku', 'productcode'), ('qty', 'quantity')],
    'finance': [('currencycode', 'currency'), ('transaction', 'payment'), ('acct', 'account'), ('amt', 'amount')],
}
LOOPS = {'for-each', 'for-each-group', 'copy-of', 'choose', 'if', 'when-otherwise'}


def _normal(text):
    return re.sub(r'[^\w]', '', str(text).casefold()).replace('_', '')


def _schema(schema):
    if isinstance(schema, str):
        if schema.lstrip().startswith('<'):
            from .data_formats import xsd_shape
            shape = xsd_shape(schema)
            return {'type': 'object', 'properties': {shape['xml']['name']: shape}}
        try: schema = json.loads(schema)
        except ValueError as error: raise ValueError('Select a valid source/target schema or JSON sample') from error
    return schema


def _merge_samples(a,b):
    if a.get('unobserved') or a.get('type')=='null': return b
    if b.get('unobserved') or b.get('type')=='null': return a
    if a.get('type')==b.get('type')=='object':
        props=dict(a['properties'])
        for k,v in b['properties'].items(): props[k]=_merge_samples(props[k],v) if k in props else v
        return {'type':'object','properties':props}
    if a.get('type')==b.get('type')=='array': return {'type':'array','items':_merge_samples(a['items'],b['items'])}
    if {a.get('type'),b.get('type')} <= {'integer','number'}: return {'type':'number' if 'number' in (a['type'],b['type']) else 'integer'}
    return a if a==b else {'type':'any'}


def _sample(value, depth=0, budget=None):
    if budget is None: budget=[0]
    budget[0]+=1
    if depth > 64 or budget[0]>20000: raise ValueError('Sample exceeds 64 levels or 20000 analyzed values')
    if isinstance(value, dict): return {'type': 'object', 'properties': {k: _sample(v, depth+1,budget) for k,v in value.items()}}
    if isinstance(value, list):
        # Inspect several records so optional members missing in the first record
        # remain addressable. Heterogeneous scalar types are treated as unknown.
        definitions = [_sample(v, depth+1,budget) for v in value[:32] if v is not None]
        items = {'type':'any','unobserved':True}
        for definition in definitions: items = _merge_samples(items,definition)
        return {'type':'array','items':items}
    return {'type': 'null' if value is None else 'boolean' if isinstance(value,bool) else 'integer' if isinstance(value,int) else 'number' if isinstance(value,float) else 'string'}


def fields(schema):
    schema = _schema(schema)
    if not isinstance(schema, dict) or not ('properties' in schema or schema.get('type') in ('object','array') or '$ref' in schema):
        schema = _sample(schema)
    root = schema; result = []; visited = 0
    def walk(node, path='', repeats=(), required=False, refs=(), depth=0):
        nonlocal visited
        visited += 1
        if depth > 64 or visited > 20000: raise ValueError('Narrow the selected schema: mapping analysis exceeds 64 levels or 20000 nodes')
        if not isinstance(node, dict): return
        if '$ref' in node:
            ref = node['$ref']
            if ref in refs: return
            try:
                resolved = local_schema_target(root, ref)
            except (KeyError, IndexError, TypeError, ValueError): return
            if not isinstance(resolved, dict): return
            walk({**resolved, **{k:v for k,v in node.items() if k != '$ref'}},path,repeats,required,(*refs,ref),depth+1); return
        kind = node.get('type', 'object' if 'properties' in node else 'any')
        if isinstance(kind,list): kind = next((k for k in kind if k != 'null'),'any') if len([k for k in kind if k != 'null']) == 1 else 'any'
        if kind == 'array':
            if not path: raise ValueError('Wrap a root array in a named schema field before automatic mapping')
            walk(node.get('items',{}),path,(*repeats,path),required,refs,depth+1); return
        if kind == 'object' or 'properties' in node:
            for name, child in node.get('properties',{}).items():
                # Runtime dot paths cannot distinguish literal dots/brackets in names.
                if not isinstance(name,str) or not name: continue
                if any(c in name for c in '.[]'):
                    result.append({'path':(path+'.'+name).strip('.'),'name':name,'type':'any','repeats':list(repeats),'required':name in node.get('required',[])})
                    continue
                walk(child, (path+'.'+name).strip('.'),repeats,name in node.get('required',[]),refs,depth+1)
        elif path:
            result.append({'path':path,'name':path.rsplit('.',1)[-1], 'type':kind,
                           'repeats':list(repeats), 'required':required})
    walk(schema)
    return result


def plan(source_schema, target_schema, mappings=None, *, threshold=70, profile='general', aliases=None,
         choices=None, learned=None, source_scope='', target_scope='', source_level=4, target_level=4,
         exact_names=False, auto_repeating=True, strategy='balanced'):
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not 0 <= threshold <= 100 or not math.isfinite(threshold):
        raise ValueError('Confidence must be between 0 and 100')
    if not isinstance(profile,str) or profile not in PROFILES: raise ValueError('Unknown business vocabulary')
    if strategy not in ('balanced','strict','semantic','exact'): raise ValueError('Unknown matching strategy')
    aliases = [] if aliases is None else aliases
    choices = {} if choices is None else choices
    mappings = [] if mappings is None else mappings
    if not isinstance(aliases,list) or len(aliases)>100 or not isinstance(choices,dict) or len(choices)>5000:
        raise ValueError('Use at most 100 vocabulary pairs and 5000 reviewed choices')
    if not isinstance(mappings,list) or len(mappings)>5000 or any(not isinstance(r,dict) or not isinstance(r.get('target'),str) for r in mappings):
        raise ValueError('Expected at most 5000 mapping objects')
    parent = {}
    def representative(term):
        parent.setdefault(term,term)
        while parent[term]!=term:
            parent[term]=parent[parent[term]]; term=parent[term]
        return term
    for pair in [*PROFILES['general'], *(PROFILES[profile] if profile != 'general' else []), *aliases]:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2 or any(not isinstance(v,str) or not 1<=len(v)<=80 for v in pair):
            raise ValueError('Each vocabulary pair needs two terms of at most 80 characters')
        a,b = map(_normal,pair)
        if not a or not b: raise ValueError('Vocabulary terms must contain letters or numbers')
        parent[representative(a)] = representative(b)
    canonical = {term:representative(term) for term in parent}
    exact_names = exact_names or strategy=='exact'
    def words(text):
        parts = re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',text).casefold()
        tokens = re.findall(r'\w+',parts.replace('_',' '))
        tokens = [t[:-1] if t in {'orders','items','customers','payments','transactions','accounts','products','clients','purchases','buyers'} else t for t in tokens]
        return {canonical.get(_normal(v),_normal(v)) for v in tokens}
    def scope(rows, path, level):
        if not isinstance(path,str) or type(level) is not int or not 1<=level<=10: raise ValueError('Matching levels must be 1 to 10')
        return [r for r in rows if not path or r['path']==path or (r['path'].startswith(path+'.') and r['path'][len(path)+1:].count('.')<level)]
    source = scope(fields(source_schema),source_scope,source_level)
    target = scope(fields(target_schema),target_scope,target_level)
    if any(not isinstance(k,str) or not isinstance(v,str) for k,v in choices.items()) or set(choices)-{r['path'] for r in target}:
        raise ValueError('Reviewed choices must refer to fields in the selected target branch')
    if max(len(source),len(target))>5000: raise ValueError('Select a smaller source or target branch (maximum 5000 fields)')
    existing = copy.deepcopy([r for r in mappings if not r.get('pending')])
    primary_counts=defaultdict(int)
    for rule in existing:
        if not rule.get('occurrenceId'): primary_counts[rule['target']]+=1
    reusable = {}
    for rule in existing:
        value=rule.get('select') or rule.get('source')
        if isinstance(value,str) and value.startswith('${') and value.endswith('}'): value=value[2:-1]
        if (primary_counts[rule['target']]==1 and rule.get('operator')=='for-each' and rule.get('enabled') is not False and not rule.get('occurrenceId')
                and not rule.get('duplicateOf') and not rule.get('functions') and not rule.get('condition')
                and isinstance(value,str) and re.fullmatch(r'last\.[\w.@-]+',value)):
            reusable[rule['target']]=value[5:]
    protected = {r['target'] for r in existing if any(r.get(k) is not None and r.get(k)!='' for k in ('source','select'))
                 or 'constant' in r or r.get('operator') or r.get('functions') or r.get('occurrenceId') or r.get('condition') or r.get('whens')}
    structures = [r['target'] for r in existing if (r.get('operator') in LOOPS or r.get('duplicateOf')) and r['target'] not in reusable]
    by_name = defaultdict(list); by_alias = defaultdict(list); by_word = defaultdict(set); by_path = {r['path']:r for r in source}
    for i,row in enumerate(source):
        by_name[_normal(row['name'])].append(i)
        by_alias[canonical.get(_normal(row['name']),_normal(row['name']))].append(i)
        row['_words'] = words(row['name'])
        for word in row['_words']: by_word[word].add(i)
    proposals = []; recommendations = []; loop_pairs = dict(reusable); used_reusable=set(); evaluations = 0
    def blocked(path): return path in protected or any(path.startswith(p+'.') for p in {*structures,*(protected-set(reusable))})
    # Resolve distinctive leaves first so their loop context can disambiguate
    # generic id/name fields in the same repeating branch.
    ordered = sorted(target,key=lambda r:len(by_name.get(_normal(r['name']),[])) or 10000)
    for dest in ordered:
        path = dest['path']
        if blocked(path):
            active = any((r['target']==path or path.startswith(r['target']+'.')) and r.get('enabled') is not False and not r.get('pending') for r in existing)
            recommendations.append({'target':path,'status':'protected','required':dest['required'],'active':active,'alternatives':[]}); continue
        tokens = words(dest['name']); normalized = _normal(dest['name'])
        indices = set(by_name.get(normalized,[]))
        if not exact_names and not indices:
            indices.update(by_alias.get(canonical.get(normalized,normalized),[]))
        if not exact_names and not indices:
            for word in tokens: indices.update(by_word.get(word,()))
        explicit = choices.get(path)
        remembered = (learned or {}).get(path)
        for chosen in (explicit,remembered):
            if chosen in by_path: indices.add(source.index(by_path[chosen]))
        if len(indices)>1000: raise ValueError('More than 1000 candidate sources for one field; select a narrower matching branch')
        candidates = []
        for index in sorted(indices):
            evaluations += 1
            if evaluations>1000000: raise ValueError('Select a source/target branch to narrow mapping analysis')
            src = source[index]; reasons = []
            same = _normal(src['name'])==normalized
            if exact_names and not same: continue
            compatible = src['type']==dest['type'] or src['type']=='integer' and dest['type']=='number'
            if strategy == 'strict': compatible = src['type']==dest['type']
            if not compatible or src['type'] in ('any','null') or dest['type'] in ('any','null'): continue
            if len(src['repeats']) != len(dest['repeats']): continue
            if src['repeats'] and ((src['repeats'][-1]==src['path']) != (dest['repeats'][-1]==path)): continue
            if dest['repeats'] and not auto_repeating: continue
            pairs = list(zip(dest['repeats'],src['repeats']))
            if any(path.startswith(t+'.') and (t not in dest['repeats'] or not src['path'].startswith(s+'.')) for t,s in reusable.items()): continue
            if any(t not in reusable and any(p.startswith(t+'.') for p in protected) for t,_ in pairs): continue
            if any(p in loop_pairs and loop_pairs[p]!=s for p,s in pairs): continue
            overlap = len(src['_words'] & tokens)/max(1,len(src['_words'] | tokens))
            alias_match = canonical.get(_normal(src['name']),_normal(src['name'])) == canonical.get(normalized,normalized)
            linguistic = 1 if same or alias_match else overlap
            if not linguistic and src['path'] not in (explicit,remembered): continue
            # Ancestor tokens disambiguate e.g. billing.id vs shipping.id.
            sp = src['path'].split('.')[:-1]; tp = path.split('.')[:-1]
            sw = words(' '.join(sp)); tw = words(' '.join(tp))
            ancestor = len(sw & tw)/max(1,len(sw | tw)) if sw or tw else 1
            score = round((85 if strategy=='semantic' else 75)*linguistic+(5 if strategy=='semantic' else 15)*ancestor+10,1)
            reasons.append('Same field name (case/separator insensitive)' if same else 'Business vocabulary/token match')
            if ancestor: reasons.append('Matching parent context')
            reasons.append('Compatible data types')
            if pairs: reasons.append(f'{len(pairs)} repeating level(s) aligned')
            if src['path']==remembered: score=max(score,95); reasons.append('Previously reviewed shared mapping')
            if src['path']==explicit: score=100; reasons.append('Source explicitly chosen in this review')
            candidates.append({'source':src['path'],'score':score,'reasons':reasons,'repeatPairs':pairs})
        candidates.sort(key=lambda c:(c['source']==explicit,c['score'],c['source']==remembered),reverse=True)
        top = candidates[:3]; best = top[0] if top else None
        ambiguous = bool(best and len(top)>1 and top[0]['score']-top[1]['score']<8 and not explicit and top[0]['source']!=remembered)
        selected = best if best and best['score']>=threshold and not ambiguous else None
        if explicit and (not best or best['source']!=explicit): raise ValueError(f'{path}: chosen source is incompatible with the target structure/type')
        status = 'suggested' if selected else 'ambiguous' if ambiguous else 'unmatched'
        recommendations.append({'target':path,'targetType':dest['type'],'required':dest['required'],'status':status,
                                'confidence':best['score'] if best else 0,'alternatives':top,'selected':selected['source'] if selected else None})
        if selected:
            primitive_array = bool(dest['repeats'] and dest['repeats'][-1]==path)
            for t,s in selected['repeatPairs']:
                if t in reusable: used_reusable.add(t)
                if t!=path: loop_pairs[t]=s
            proposals.append({'target':path,'source':'${last.'+selected['source']+'}','targetType':'array' if primitive_array else dest['type'],
                              **({'operator':'copy-of'} if primitive_array else {}),'enabled':True,
                              'functions':[],'confidence':selected['score'],'autoGenerated':True,'mappingReasons':selected['reasons']})
    loops = [{'target':t,'source':'${last.'+s+'}','select':'${last.'+s+'}','operator':'for-each','enabled':True,'functions':[],
              'autoGenerated':True,'mappingReasons':['Repeating source and target structures aligned']} for t,s in sorted(loop_pairs.items(),key=lambda p:p[0].count('.')) if t not in reusable]
    new_targets = {r['target'] for r in proposals}
    retained = [r for r in existing if r['target'] not in new_targets]
    if len(retained)+len(loops)+len(proposals)>5000: raise ValueError('Plan exceeds 5000 rules; select a smaller branch')
    counts = {status:sum(r['status']==status for r in recommendations) for status in ('suggested','protected','ambiguous','unmatched')}
    target_order = {r['path']:i for i,r in enumerate(target)}
    recommendations.sort(key=lambda r:target_order[r['target']])
    return {'rules':retained+loops+proposals,'recommendations':recommendations,
            'summary':{**counts,'targetFields':len(target),'requiredUnmapped':sum(r['required'] and (r['status'] in ('ambiguous','unmatched') or r['status']=='protected' and not r.get('active')) for r in recommendations),
                       'loops':len(loops),'reusedLoops':len(used_reusable),'copies':sum(r.get('operator')=='copy-of' for r in proposals),'sourceFields':len(source),'candidateComparisons':evaluations},
            'engine':'Local schema/vocabulary matching and reviewed learning; no external AI service or payload upload'}
