"""Audit large nested Data files through complete Run/Debug/archive flows.

Measures sampled process RSS (not Python-only allocations) and checks every
JSON Lines record plus byte-exact rendered output. All files are synthetic.
"""
import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import psutil
from app.models import Project


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1048576),b''):result.update(block)
    return result.hexdigest()


async def verify(args):
    args.output_dir.mkdir(parents=True,exist_ok=True)
    source=args.output_dir/'source.csv';body='x'*args.payload_chars
    child=[{'sku':'A','qty':2}]
    with source.open('w',encoding='utf-8',newline='') as handle:
        writer=csv.writer(handle,lineterminator='\n');writer.writerow(['id','body','lines'])
        for index in range(args.records):writer.writerow([index,body,json.dumps(child,separators=(',',':'))])
    source_hash=digest(source)
    config={'nestedRecords':True,'streaming':True,'fields':'id,body,lines','fieldTypes':'integer,string,json',
            'fieldPaths':{'id':'/id','body':'/detail/body','lines':'/lines'},'strictColumns':True,
            'streamBatchSize':100,'streamMaxBatchBytes':1048576,'streamMaxRecordBytes':65536}
    nodes=[{'id':'s','name':'Start','type':'start'},
           {'id':'p','name':'Parse-Data','type':'flat','config':{**config,'operation':'parse','inputMappings':{'fileName':'${input.source}','streamOutputFile':'${input.jsonl}'}}},
           {'id':'r','name':'Render-Data','type':'flat','config':{**config,'operation':'render','inputMappings':{'streamInputFile':'${input.jsonl}','streamOutputFile':'${input.target}'}}},
           {'id':'e','name':'End','type':'end'}]
    project=Project.model_validate({'id':'large-data-qa','name':'Large-Data-QA','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
        'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
    spec=importlib.util.spec_from_file_location('data_stream_qa_flow',ROOT/'scripts/flow-throughput.py')
    flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
    results=[]
    for mode in args.modes:
        executor=flow.Executor(mode,project,str(args.output_dir/(mode+'.log')))
        records=args.output_dir/(mode+'.jsonl');target=args.output_dir/(mode+'.csv')
        try:
            await executor.start();process=psutil.Process(executor.interpreter_pid)
            baseline=process.memory_info().rss;peak=[baseline];stop=threading.Event()
            def sample():
                while not stop.wait(.01):
                    try:peak[0]=max(peak[0],process.memory_info().rss)
                    except psutil.Error:return
            monitor=threading.Thread(target=sample,daemon=True);monitor.start();started=time.perf_counter()
            try:output=await executor.execute('main',{'source':str(source),'jsonl':str(records),'target':str(target)})
            finally:stop.set();monitor.join()
            elapsed=time.perf_counter()-started
            assert output['streamed'] and output['recordCount']==args.records,(mode,output)
            assert digest(target)==source_hash,(mode,'rendered bytes differ')
            count=0
            with records.open(encoding='utf-8') as handle:
                for index,line in enumerate(handle):
                    assert json.loads(line)=={'id':index,'detail':{'body':body},'lines':child},(mode,index)
                    count+=1
            assert count==args.records
            row={'mode':mode,'passed':True,'recordsAudited':count,'sourceBytes':source.stat().st_size,
                 'elapsedSeconds':round(elapsed,4),'sampledBaselineRssBytes':baseline,'sampledPeakRssBytes':peak[0],
                 'sampledRssGrowthBytes':peak[0]-baseline,'renderedSha256':source_hash,'batchCount':output['batchCount']}
            results.append(row);print(json.dumps(row),flush=True)
        finally:await executor.close()
    report={'passed':True,'results':results,'scope':'Complete nested Parse file -> JSON Lines -> Render file flows; every value and rendered byte audited',
            'limitations':'Synthetic local files. Timings cover flow execution, excluding archive creation/startup/cleanup and output audits. 10 ms sampled RSS can miss short peaks; no constant-RSS guarantee or long-duration soak claim.'}
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--records',type=int,default=35000)
    parser.add_argument('--payload-chars',type=int,default=2048)
    parser.add_argument('--modes',nargs='+',choices=['run','debug','python-direct','python-engine'],default=['run','debug','python-direct','python-engine'])
    args=parser.parse_args()
    if not 1<=args.records<=100000 or not 1<=args.payload_chars<=32000:parser.error('Use 1–100000 records and 1–32000 payload characters')
    if (args.output_dir/'summary.json').exists():parser.error('Choose a fresh output directory')
    args.output_dir=args.output_dir.resolve()
    asyncio.run(verify(args))
