import { useMemo } from 'react';
import { selectXsdStructure, xsdSelection, xsdStructures } from './xsdSelection';

export default function XsdStructurePicker({text,onChange,label='Structure'}:{text:string;onChange:(text:string)=>void;label?:string}) {
  const {options,selected}=useMemo(()=>{const options=xsdStructures(text);return {options,selected:xsdSelection(text) || options.find(option=>option.kind==='Element')?.id || options[0]?.id || ''};},[text]);
  if (!options.length) return null;
  return <label className="xsd-structure-picker">{label}<select aria-label={label} value={selected} onChange={event=>onChange(selectXsdStructure(text,event.target.value))}>
    {!options.some(option=>option.id===selected) && <option value={selected}>Unavailable structure — choose another</option>}
    {options.map(option=><option key={option.id} value={option.id}>{option.kind} · {option.name}</option>)}
  </select></label>;
}
