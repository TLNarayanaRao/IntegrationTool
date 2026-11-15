import {useEffect,useMemo,useRef,useState} from 'react';
import {bundledXPathFunctions,xpathFunctionExpression} from './xpathPalette';

export default function XPathFunctionPalette({search='',onSelect}:{search?:string;onSelect:(expression:string)=>void}) {
  const [version,setVersion]=useState('2.0'),[selected,setSelected]=useState(''),[values,setValues]=useState<string[]>([]);
  const argumentsPanel=useRef<HTMLElement>(null);
  useEffect(()=>{if(selected)argumentsPanel.current?.scrollIntoView({block:'nearest'});},[selected]);
  const entries=useMemo(()=>bundledXPathFunctions(version),[version]);
  const query=search.trim().toLowerCase();
  const visible=entries.filter(entry=>`${entry.name} ${entry.category} ${entry.description}`.toLowerCase().includes(query));
  const current=entries.find(entry=>entry.name+'#'+entry.args.length===selected);
  const expression=current ? xpathFunctionExpression(current.name,values,version) : '';
  const ready=!!current && values.length===current.args.length&&values.every(value=>value.trim());
  return <details className="function-category xpath-function-palette" open={!!query}>
    <summary><span className="tree-disclosure"/><b>XPath functions</b><code>{visible.length}</code></summary>
    <label>XPath version<select aria-label="Functions tab XPath version" value={version} onChange={event=>{setVersion(event.target.value);setSelected('');setValues([]);}}><option>1.0</option><option>2.0</option></select></label>
    {current && <section ref={argumentsPanel} className="xpath-function-arguments">
      <b>{current.name}</b><small>{current.description}</small>
      {current.args.map((label,index)=><label key={index}>{label}<input aria-label={`${current.name} ${label}`} placeholder="XPath, for example /orders/order or 'text'" value={values[index]||''}
        onChange={event=>setValues(previous=>previous.map((value,current)=>current===index?event.target.value:value))}/></label>)}
      <button type="button" disabled={!ready} draggable={ready} title="Drag the prepared expression onto a Mapper target" onClick={()=>onSelect(expression)} onDragStart={event=>{
        if(!ready){event.preventDefault();return;}event.dataTransfer.setData('expression',expression);event.dataTransfer.setData('sourceType','function');event.dataTransfer.effectAllowed='copy';
      }}>Drag XPath expression to target</button>
      {ready && <code className="xpath-prepared-expression">{expression}</code>}
    </section>}
    {[...new Set(visible.map(entry=>entry.category))].map(category=><details className="function-category" key={category} open={!!query}>
      <summary><b>{category}</b></summary>
      {visible.filter(entry=>entry.category===category).map(entry=><button type="button" className="source-tree-node mapper-function-source" key={entry.name+'#'+entry.args.length}
        title={entry.description} onClick={()=>{setSelected(entry.name+'#'+entry.args.length);setValues(entry.args.map(()=>''));}}>
        <span><b>{entry.name}</b><small>{entry.args.length} argument{entry.args.length===1?'':'s'}</small></span><code>XPath</code>
      </button>)}
    </details>)}
  </details>;
}
