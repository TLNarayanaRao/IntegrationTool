/* No network calls, project reads, external scripts, HTML injection or credentials. */
(() => {
 'use strict';
 const model=window.MINA_DOCUMENTATION;
 const main=document.getElementById('content'), tree=document.getElementById('tree');
 if(!model?.pages?.length){main.textContent='Documentation data is missing. Rebuild the documentation or use the installed PDF.';return;}
 const pages=new Map(model.pages.map(p=>[p.id,p]));
 const searchable=model.pages.map(page=>({page,text:JSON.stringify(page).toLocaleLowerCase()}));
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const safeText=text=>String(text??'').replace(/\*\*(.*?)\*\*/g,'$1');
 function inline(parent,text){
  // Keep source Markdown links useful only when they resolve to bundled topics or HTTPS.
  const pattern=/\[([^\]]+)\]\(([^)]+)\)/g;let end=0;
  for(const match of String(text).matchAll(pattern)){
   parent.append(document.createTextNode(safeText(text.slice(end,match.index))));
   const target=model.pages.find(p=>p.source===`docs/${match[2]}`);
   if(target||/^https:\/\//i.test(match[2])){const a=node('a',match[1]);a.href=target?`#${target.id}`:match[2];if(!target){a.target='_blank';a.rel='noopener noreferrer';}parent.append(a);}else parent.append(document.createTextNode(`${match[1]} (${match[2]})`));
   end=match.index+match[0].length;
  }
  parent.append(document.createTextNode(safeText(String(text).slice(end))));
 }
 function block(b){
  if(b.kind==='table'){
   const wrap=node('div',undefined,'table-wrap');
   if(!b.rows.length){wrap.append(node('p','No additional fields declared for this section.'));return wrap;}
   const table=node('table'),thead=node('thead'),tr=node('tr');
   for(const c of b.columns){const th=node('th',c);th.scope='col';tr.append(th);}thead.append(tr);table.append(thead);
   const tbody=node('tbody');for(const row of b.rows){const r=node('tr');for(let i=0;i<b.columns.length;i++){const td=node('td');inline(td,String(row[i]??''));r.append(td);}tbody.append(r);}table.append(tbody);wrap.append(table);return wrap;
  }
  const el=node(b.kind==='code'?'pre':b.kind==='heading'?'h3':b.kind==='list'?'ul':'p');
  if(b.kind==='code')el.textContent=b.text;
  else if(b.kind==='list'){const li=node('li');inline(li,b.text);el.append(li);}else inline(el,b.text);
  return el;
 }
 function route(){let id;try{id=decodeURIComponent(location.hash.slice(1)).split('/')[0]||'overview';}catch{id='overview';}return id;}
 function renderTree(query=''){
  const terms=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches=searchable.filter(x=>terms.every(t=>x.text.includes(t))).map(x=>x.page);
  const hierarchy={};for(const page of matches){let group=hierarchy;for(const part of page.category.split(' / ')){group[part]??={};group=group[part];}(group._pages??=[]).push(page);}
  tree.replaceChildren();
  function walk(data,parent,level=0){for(const [name,children] of Object.entries(data)){if(name==='_pages')continue;const details=node('details');details.open=!!terms.length||level===0;details.append(node('summary',name));const branch=node('div',undefined,'branch');walk(children,branch,level+1);details.append(branch);parent.append(details);}for(const page of data._pages||[]){const a=node('a',page.title);a.href=`#${page.id}`;a.dataset.topic=page.id;if(page.id===route())a.setAttribute('aria-current','page');parent.append(a);}}
  walk(hierarchy,tree);document.getElementById('result-count').textContent=`${matches.length} of ${model.pages.length} topics`;
  if(!matches.length)tree.append(node('p','No matching topics. Try an activity name, field key or error code.'));
  markCurrent();
 }
 function markCurrent(){for(const a of tree.querySelectorAll('a[data-topic]')){if(a.dataset.topic===route()){a.setAttribute('aria-current','page');let parent=a.parentElement;while(parent&&parent!==tree){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}}else a.removeAttribute('aria-current');}}
 function render(){
  const page=pages.get(route());main.replaceChildren();
  if(!page){main.append(node('h1','Topic not found'),node('p','Choose a topic from the index.'));return;}
  document.title=`${page.title} | MINA Documentation`;
  const article=node('article');article.append(node('p',page.category,'breadcrumb'),node('h1',page.title));
  if(page.id==='overview')article.append(node('p',`${model.counts.activities} activities · ${model.counts.groups} groups · ${model.counts.functions} functions · ${model.counts.connections} connection types`,'counts'));
  const tabs=node('div',undefined,'tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',`${page.title} sections`);
  let tabName='';try{tabName=decodeURIComponent(location.hash.slice(1)).split('/')[1]||'';}catch{}
  const selected=Math.max(0,page.sections.findIndex(s=>s.title===tabName));
  page.sections.forEach((section,index)=>{
   const button=node('button',section.title);button.id=`tab-${index}`;button.setAttribute('role','tab');button.setAttribute('aria-selected',String(index===selected));button.setAttribute('aria-controls',`panel-${index}`);button.tabIndex=index===selected?0:-1;
   button.onclick=()=>{location.hash=`${page.id}/${encodeURIComponent(section.title)}`;};
   button.onkeydown=event=>{let next;if(event.key==='ArrowRight')next=(index+1)%page.sections.length;else if(event.key==='ArrowLeft')next=(index+page.sections.length-1)%page.sections.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=page.sections.length-1;else return;event.preventDefault();location.hash=`${page.id}/${encodeURIComponent(page.sections[next].title)}`;setTimeout(()=>document.getElementById(`tab-${next}`)?.focus(),0);};
   tabs.append(button);
  });article.append(tabs);
  page.sections.forEach((s,index)=>{const panel=node('section');panel.id=`panel-${index}`;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',`tab-${index}`);panel.tabIndex=0;panel.hidden=index!==selected;panel.append(node('h2',s.title));for(const b of s.blocks)panel.append(block(b));article.append(panel);});
  article.append(node('p',`MINA ${model.version} · ${page.source?`Reference source: ${page.source} · `:''}Build ${model.fingerprint.slice(0,12)}. Provider-specific setup and qualification remain required.`,'source'));
  main.append(article);main.scrollTop=0;markCurrent();
 }
 let timer;document.getElementById('search').oninput=e=>{clearTimeout(timer);timer=setTimeout(()=>renderTree(e.target.value),120);};
 document.getElementById('expand').onclick=()=>tree.querySelectorAll('details').forEach(d=>d.open=true);
 document.getElementById('collapse').onclick=()=>tree.querySelectorAll('details').forEach(d=>d.open=false);
 document.getElementById('menu').onclick=e=>{const hidden=document.body.classList.toggle('index-hidden');e.currentTarget.setAttribute('aria-expanded',String(!hidden));};
 try{document.body.classList.toggle('dark',localStorage.getItem('mina-docs-theme')==='dark');}catch{}
 document.getElementById('theme').onclick=()=>{const dark=document.body.classList.toggle('dark');try{localStorage.setItem('mina-docs-theme',dark?'dark':'light');}catch{}};
 document.getElementById('print').onclick=()=>window.print();
 document.querySelector('.skip').onclick=event=>{event.preventDefault();main.focus();};
 document.getElementById('version').textContent=`v${model.version} · installed reference`;
 window.addEventListener('hashchange',render);renderTree();render();
})();
