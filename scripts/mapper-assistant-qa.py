"""Audit indexed planning and generated complete flows, without external services."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.mapper_assistant import plan
from app.models import Project


async def verify(count,folder):
    folder.mkdir(parents=True,exist_ok=True)
    source={f'field_{i}':i+1 for i in range(count)}
    target={f'field_{i}':0 for i in range(count)}
    start=time.perf_counter(); result=plan(source,target); planning=time.perf_counter()-start
    assert result['summary']['suggested']==count
    assert result['summary']['candidateComparisons']==count
    nodes=[{'id':'s','name':'Start','type':'start'}, {'id':'m','name':'Mapper','type':'mapper','config':{'mappings':result['rules']}}, {'id':'e','name':'End','type':'end'}]
    project=Project.model_validate({'id':'assistant-qa','name':'Assistant-QA','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
        'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
    spec=importlib.util.spec_from_file_location('assistant_flow',ROOT/'scripts/flow-throughput.py')
    flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
    runs=[]
    for mode in ('run','debug','python-direct','python-engine'):
        executor=flow.Executor(mode,project,str(folder/(mode+'.log')))
        start=time.perf_counter()
        try:
            await executor.start(); output=await executor.execute('main',source)
            assert output==source,(mode,len(output))
        finally: await executor.close()
        runs.append({'mode':mode,'passed':True,'fieldsAudited':count,'elapsedSeconds':round(time.perf_counter()-start,6)})
    report={'passed':True,'scope':'Indexed schema planning plus Start -> Mapper -> End; every mapped value audited',
            'fields':count,'planningSeconds':round(planning,6),'candidateComparisons':result['summary']['candidateComparisons'],
            'results':runs,'limitations':'Functional/bulk-field audit; not a UI interaction latency measurement or long-duration soak'}
    (folder/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fields',type=int,default=2000)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.fields<=5000: parser.error('--fields must be 1 to 5000')
    if (args.output_dir/'summary.json').exists(): parser.error('Choose a fresh output directory')
    asyncio.run(verify(args.fields,args.output_dir))
