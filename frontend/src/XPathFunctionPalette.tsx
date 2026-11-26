import {useEffect,useId,useMemo,useRef,useState} from 'react';
import ModalLayer from './ModalLayer';
import {bundledXPathFunctions,xpathFunctionExpression} from './xpathPalette';

type FunctionEntry = ReturnType<typeof bundledXPathFunctions>[number];

function XPathFunctionHelp({entry, version, onClose}: {entry:FunctionEntry; version:string; onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const titleId=useId();
  const {example}=entry;
  const close=()=>{
    dialog.current?.close();
    onClose();
  };
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return ()=>element?.close();
  },[]);

  return <ModalLayer className="xpath-help-layer">
    <dialog ref={dialog} className="xpath-help-dialog" aria-labelledby={titleId}
      onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}}}
      onCancel={event=>{event.preventDefault();event.stopPropagation();close();}}>
      <header className="xpath-help-header">
        <div><small>XPath {version} · {entry.category}</small><h2 id={titleId}>{entry.name}()</h2></div>
        <button type="button" onClick={close}>Close</button>
      </header>
      <div className="xpath-help-content" tabIndex={0} role="region" aria-label="Function reference">
        <p>{entry.description}</p>
        <h3>Signature</h3>
        <pre>{entry.signature || `${entry.name}(${entry.args.join(', ')})`}</pre>
        <h3>Sample inputs</h3>
        {entry.args.length ? <dl>{entry.args.map((arg,index)=><div key={index}>
          <dt>{arg}</dt><dd><code>{example.args[index]}</code></dd>
        </div>)}</dl> : <p>This overload takes no arguments.</p>}
        {example.xml && <><h3>Sample XML</h3><pre>{example.xml.replace(/></g,'>\n<')}</pre></>}
        {example.properties && <><h3>Sample project properties</h3><pre>{JSON.stringify(example.properties,null,2)}</pre></>}
        <h3>Example expression</h3>
        <pre>{example.expression}</pre>
        <h3>{example.error ? 'Expected error' : example.variable ? 'Example result' : 'Expected result'}</h3>
        <pre>{example.result}</pre>
        {example.note && <p>{example.note}</p>}
      </div>
    </dialog>
  </ModalLayer>;
}

export default function XPathFunctionPalette({search='',onSelect}:{search?:string;onSelect:(expression:string)=>void}) {
  const [version,setVersion]=useState('2.0'),[selected,setSelected]=useState(''),[values,setValues]=useState<string[]>([]);
  const [help,setHelp]=useState<FunctionEntry|null>(null);
  const argumentsPanel=useRef<HTMLElement>(null);
  const selectionTimer=useRef<number>(undefined);
  useEffect(()=>()=>window.clearTimeout(selectionTimer.current),[]);
  useEffect(()=>{if(selected)argumentsPanel.current?.scrollIntoView({block:'nearest'});},[selected]);
  const entries=useMemo(()=>bundledXPathFunctions(version),[version]);
  const query=search.trim().toLowerCase();
  const visible=entries.filter(entry=>`${entry.name} ${entry.category} ${entry.description}`.toLowerCase().includes(query));
  const current=entries.find(entry=>entry.name+'#'+entry.args.length===selected);
  const expression=current ? xpathFunctionExpression(current.name,values,version) : '';
  const ready=!!current && values.length===current.args.length&&values.every(value=>value.trim());
  const startDrag = (transfer: DataTransfer, value: string) => {
    transfer.effectAllowed = 'copy';
    transfer.setData('expression', value);
    transfer.setData('sourceType', 'function');
    transfer.setData('text/plain', value);
  };
  return <details className="function-category xpath-function-palette" open={!!query}>
    <summary><span className="tree-disclosure"/><b>XPath functions</b><code>{visible.length}</code></summary>
    <label>XPath version<select aria-label="Functions tab XPath version" value={version} onChange={event=>{window.clearTimeout(selectionTimer.current);setVersion(event.target.value);setSelected('');setValues([]);}}><option>1.0</option><option>2.0</option></select></label>
    {current && <section ref={argumentsPanel} className="xpath-function-arguments">
      <b>{current.name}</b><small>{current.description}</small>
      <button type="button" onClick={()=>setHelp(current)}>Function help</button>
      {current.args.map((label,index)=><label key={index}>{label}<input aria-label={`${current.name} ${label}`} placeholder="XPath, for example /orders/order or 'text'" value={values[index]||''}
        onChange={event=>setValues(previous=>previous.map((value,current)=>current===index?event.target.value:value))}/></label>)}
      <button type="button" disabled={!ready} draggable={ready} title="Drag the prepared expression onto a target field" onClick={()=>onSelect(expression)} onDragStart={event=>{
        if(!ready){event.preventDefault();return;}
        startDrag(event.dataTransfer, expression);
      }}>Drag XPath expression to target</button>
      {ready && <code className="xpath-prepared-expression">{expression}</code>}
    </section>}
    {[...new Set(visible.map(entry=>entry.category))].map(category=><details className="function-category" key={category} open={!!query}>
      <summary><b>{category}</b></summary>
      {visible.filter(entry=>entry.category===category).map(entry=>{
        const key = entry.name+'#'+entry.args.length;
        return <button type="button" className="source-tree-node mapper-function-source" key={key} draggable
          title={entry.description + ' Double-click for help. Drag onto a target field.'}
          onClick={event=>{
            window.clearTimeout(selectionTimer.current);
            if(selected===key || event.detail>1)return;
            const select=()=>{setSelected(key);setValues(entry.args.map(()=>''));};
            // Opening the arguments moves the row. Wait for a possible second mouse click.
            if(event.detail===1)selectionTimer.current=window.setTimeout(select,500);
            else select();
          }}
          onDoubleClick={()=>{window.clearTimeout(selectionTimer.current);setHelp(entry);}}
          onDragStart={event=>startDrag(event.dataTransfer,
            selected === key && ready ? expression : xpathFunctionExpression(entry.name, [], version))}>
          <span><b>{entry.name}</b><small>{entry.args.length} argument{entry.args.length===1?'':'s'}</small></span><code>XPath</code>
        </button>;
      })}
    </details>)}
    {help && <XPathFunctionHelp entry={help} version={version} onClose={()=>setHelp(null)}/>}
  </details>;
}
