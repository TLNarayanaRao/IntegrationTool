"""Audit many HDT groups, EOF validation and atomic failure in complete flows."""
import argparse
import asyncio
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.models import Project
from tests.test_data_groups import LAYOUTS, XSD


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1048576),b''):value.update(block)
    return value.hexdigest()


async def verify(args):
    root=args.output_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    source=root/'source.csv'
    with source.open('w',encoding='utf-8',newline='') as handle:
        for i in range(args.groups):
            handle.write(f'H,G{i}\nD,S{i}-A,0.10,G{(i+1)%args.groups}\nD,S{i}-B,0.20,G{i}\nT,2,0.30\n')
    wanted=digest(source)
    rules={'minGroups':args.groups,'maxGroups':args.groups,'minRecords':args.groups*4,'maxRecords':args.groups*4,
           'minDetails':args.groups*2,'maxDetails':args.groups*2,'uniqueKeys':[['/header/orderId']],
           'totals':[{'name':'amount','path':'/amount','expected':format(Decimal('.30')*args.groups,'f')}]}
    config={'streaming':True,'groupRecords':True,'recordLayouts':LAYOUTS,'wholeFileValidation':True,
            'wholeFileRules':rules,'wholeFileXsd':True,'schemaText':XSD,'recordElement':'group','strictColumns':True}
    nodes=[{'id':'s','name':'Start','type':'start'},
           {'id':'p','name':'Parse','type':'flat','config':{**config,'operation':'parse','inputMappings':{'fileName':'${input.source}','streamOutputFile':'${input.groups}'}}},
           {'id':'r','name':'Render','type':'flat','config':{**config,'operation':'render','inputMappings':{'streamInputFile':'${input.groups}','streamOutputFile':'${input.target}'}}},
           {'id':'e','name':'End','type':'end'}]
    project=Project.model_validate({'id':'hdt-qa','name':'HDT-QA','tasks':[{'id':'main','name':'Main','kind':'subtask','activities':nodes,
        'transitions':[{'id':str(i),'source':a['id'],'target':b['id']} for i,(a,b) in enumerate(zip(nodes,nodes[1:]))]}]})
    spec=importlib.util.spec_from_file_location('hdt_qa_flows',ROOT/'scripts/flow-throughput.py')
    flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
    results=[]
    for mode in ('run','debug','python-direct','python-engine'):
        executor=flow.Executor(mode,project,str(root/(mode+'.log')))
        groups=root/(mode+'.jsonl');target=root/(mode+'.csv')
        try:
            await executor.start();started=time.perf_counter()
            result=await executor.execute('main',{'source':str(source),'groups':str(groups),'target':str(target)})
            elapsed=time.perf_counter()-started
            assert result['groupCount']==args.groups and result['detailCount']==2*args.groups
            assert result['validation']['xsdValidated'] and result['validation']['uniqueKeyRules']==1
            assert digest(target)==wanted
            count=0
            with groups.open(encoding='utf-8') as handle:
                for i,line in enumerate(handle):
                    group=json.loads(line)
                    assert group=={'header':{'kind':'H','orderId':f'G{i}'},'details':[
                        {'kind':'D','sku':f'S{i}-A','amount':'0.10','orderRef':f'G{(i+1)%args.groups}'},
                        {'kind':'D','sku':f'S{i}-B','amount':'0.20','orderRef':f'G{i}'}],
                        'trailer':{'kind':'T','count':2,'total':'0.30'}}
                    count+=1
            assert count==args.groups
            bad=root/(mode+'.bad.csv')
            # Preserve all controls/counts; only the last forward reference is
            # invalid, forcing failure in the complete-file XSD pass at EOF.
            text=source.read_text();needle=f'D,S{args.groups-1}-B,0.20,G{args.groups-1}'
            bad.write_text(text.replace(needle,f'D,S{args.groups-1}-B,0.20,UNKNOWN'),newline='')
            groups_hash=digest(groups)
            try:await executor.execute('main',{'source':str(bad),'groups':str(groups),'target':str(target)})
            except RuntimeError:pass
            else:raise AssertionError('Invalid EOF key reference was accepted')
            assert digest(groups)==groups_hash and digest(target)==wanted
            row={'mode':mode,'passed':True,'groupsAudited':count,'detailsAudited':count*2,'physicalRecords':count*4,
                 'sourceBytes':source.stat().st_size,'executionSeconds':round(elapsed,4),'sha256':wanted,
                 'eofKeyrefFailurePreservedOutputs':True,'validation':result['validation']}
            results.append(row);print(json.dumps(row),flush=True)
        finally:await executor.close()
    report={'passed':True,'scope':'HDT -> grouped JSON Lines -> HDT, full rule/XSD validation on both stages and every record/byte audited',
            'results':results,'limitations':'Synthetic local functional/bulk audit. Execution timing excludes archive startup/cleanup and audit passes; not a memory/soak benchmark.'}
    (root/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--groups',type=int,default=5000)
    args=parser.parse_args()
    if not 1<=args.groups<=100000:parser.error('Use 1–100000 groups')
    if (args.output_dir/'summary.json').exists():parser.error('Choose a fresh output directory')
    asyncio.run(verify(args))
