"""Measure actual activity processing against an explicit records/deadline target.

Broker profiles require dedicated test resources. Cloud/vendor results cannot
be inferred from a different provider. Publish completion includes confirmation;
an independent read verifies unique IDs and payloads outside the publish timer.
"""
import argparse,asyncio,importlib.util,json,sys,time,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
spec=importlib.util.spec_from_file_location('live_soak',Path(__file__).with_name('live-messaging-soak.py'))
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
import psutil
from app.models import Activity,SharedResource
from app.runtime import WorkflowRuntime
from app.mapper import execute as map_record


def payload(run,index,size):
    record={'run':run,'seq':index,'text':''}
    record['text']='x'*max(0,size-len(json.dumps(record,separators=(',',':')).encode()))
    return json.dumps(record,separators=(',',':'))


def mapper_case(index,size):
    source={'seq':index,'run':'mapper','customer':{'name':'  mina customer  ','country':'US'},
        'amounts':[1,2,3],'items':[{'sku':'item-1','qty':2}],'text':'x'*max(0,size-200)}
    mappings=[{'target':'id','source':'${seq}'},{'target':'name','source':'${customer.name}','functions':['trim','upperCase']},
        {'target':'summary.country','source':'${customer.country}'},{'target':'summary.total','source':'sum(${amounts})'},
        {'target':'first.sku','source':'${items[0].sku}'},{'target':'first.qty','source':'${items[0].qty}'},
        {'target':'text','source':'${text}'},{'target':'run','source':'${run}'}]
    return source,mappings


def context(resource,run):
    return {'resources':{resource.id:resource},'input':{},'last':{},'properties':{},'vars':{},
        'activities':{},'tasks':{},'logs':[],'context':{'jmsSenderScope':run}}


def check_records(values,run,seen,size):
    for value in values:
        record=json.loads(value) if isinstance(value,str) else value
        if record.get('run')!=run:raise AssertionError('Unexpected record on dedicated test destination')
        index=record['seq']
        if type(index) is not int or not 0<=index<len(seen):raise AssertionError('Invalid sequence number')
        if seen[index]:raise AssertionError('Duplicate sequence number')
        if record!=json.loads(payload(run,index,size)):raise AssertionError('Record payload differs from sent value')
        seen[index]=1


async def broker_test(args,profile):
    if profile.get('dedicatedTestResources') is not True:raise ValueError('Dedicated test resource configuration is required')
    family=args.family;run=profile.get('runId') or uuid.uuid4().hex
    resource=SharedResource(id='connection',name='Throughput-test',type=family,config=profile['connection'])
    destination=profile['destination'];runtime=WorkflowRuntime();seen=bytearray(args.records)
    scope='throughput-'+uuid.uuid4().hex
    base={'resourceId':resource.id,'destination':destination,'topic':destination,'queue':destination}
    send_op='publish' if family in ('kafka','pubsub') else 'send_message' if family=='jms' else 'send'
    receive_op='get' if family=='kafka' else 'pull' if family=='pubsub' else 'get_queue_message' if family=='jms' else 'queue_receiver'
    send=Activity(id='send',name='Send',type=family,config={**base,'operation':send_op,'message':'${input}',
        'waitForDelivery':family=='pubsub'})
    receive_cfg={**base,'operation':receive_op,'maxMessages':args.batch_size,'timeout':1,'receiveTimeout':1000,
        'enableAutoCommit':False,'groupId':scope,'assignCustomPartition':True,'partitionIds':'0',
        'seekPosition':'custom','customOffset':'${vars.offset}'}
    if family=='pubsub':receive_cfg['subscription']=profile['subscription'];receive_cfg['destination']=profile['subscription']
    receive=Activity(id='receive',name='Receive',type=family,config=receive_cfg)
    counters={'done':0};started=time.perf_counter();publish_seconds=None;receive_seconds=None

    async def publish():
        began=time.perf_counter()
        async def worker(number):
            ctx=context(resource,scope)
            for index in range(number,args.records,args.concurrency):
                ctx['input']=payload(run,index,args.payload_bytes);ctx['last']=ctx['input']
                await runtime.execute(send,ctx)
                counters['done']+=1
                if counters['done']%10000==0:print(json.dumps({'phase':'publish','records':counters['done']}),flush=True)
        await asyncio.gather(*(worker(n) for n in range(args.concurrency)))
        if family=='kafka':
            for key,client in list(runtime._publishers.items()):
                if key.startswith('kafka:') and await asyncio.to_thread(client.flush,max(1,args.deadline-(time.perf_counter()-began))):
                    raise AssertionError('Kafka delivery confirmation did not complete')
        return time.perf_counter()-began

    async def consume():
        began=time.perf_counter();offset=0;ctx=context(resource,scope)
        while offset<args.records:
            ctx['vars']['offset']=int(profile.get('startOffset',0))+offset
            receive.config['maxMessages']=min(args.batch_size,args.records-offset)
            result=await runtime.execute(receive,ctx)
            messages=result.get('messages') or []
            values=[item.get('data',item.get('body')) if isinstance(item,dict) else item for item in messages]
            if not values and result.get('received'):values=[result.get('body')]
            check_records(values,run,seen,args.payload_bytes);offset+=len(values)
            if time.perf_counter()-began>args.deadline:raise TimeoutError('Receive target deadline exceeded')
            if offset and offset%10000==0:print(json.dumps({'phase':'receive','records':offset}),flush=True)
        return time.perf_counter()-began

    try:
        # For receive measurements, seeding is explicitly outside the receive timer.
        publish_seconds=await asyncio.wait_for(publish(),timeout=args.deadline)
        receive_seconds=await consume()
        if sum(seen)!=args.records:raise AssertionError('Missing records')
        seconds=publish_seconds if args.operation=='publish' else receive_seconds
        return {'passed':seconds<=args.deadline,'measuredSeconds':seconds,'records':args.records,
            'recordsPerSecond':args.records/seconds,'publishSeconds':publish_seconds,'receiveSeconds':receive_seconds,
            'uniqueRecordsVerified':sum(seen),'runId':run,'measurement':'MINA WorkflowRuntime.execute activity path; excludes task graph/UI overhead',
            'publishConfirmation':'Kafka flush plus readback; other send operations await completion; Pub/Sub waits for delivery'}
    finally:runtime.close_publishers()


async def broker_soak(args, profile):
    began=time.perf_counter(); cycles=[]; offset=int(profile.get('startOffset',0))
    while time.perf_counter()-began<args.soak_seconds:
        started=time.perf_counter()
        result=await broker_test(args,{**profile,'startOffset':offset})
        if not result['passed']:raise AssertionError('Soak cycle missed its deadline')
        cycles.append(result);offset+=args.records
        await asyncio.sleep(max(0,args.cycle_interval-(time.perf_counter()-started)))
    return {'passed':True,'soakSeconds':time.perf_counter()-began,'cycles':len(cycles),
        'records':sum(item['records'] for item in cycles),
        'uniqueRecordsVerified':sum(item['uniqueRecordsVerified'] for item in cycles),
        'publishSeconds':sum(item['publishSeconds'] for item in cycles),
        'receiveSeconds':sum(item['receiveSeconds'] for item in cycles),
        'cycleResults':cycles,'measurement':'Repeated verified send/receive cycles, including client cleanup; paced between cycles'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family',choices=('kafka','pubsub','ems','jms','mapper'),required=True)
    parser.add_argument('--operation',choices=('publish','receive','map'),required=True)
    parser.add_argument('--config');parser.add_argument('--records',type=int,default=100000)
    parser.add_argument('--deadline',type=float,default=600);parser.add_argument('--payload-bytes',type=int,default=1024)
    parser.add_argument('--batch-size',type=int,default=1000);parser.add_argument('--concurrency',type=int,default=8)
    parser.add_argument('--soak-seconds',type=float,default=0);parser.add_argument('--output',required=True)
    parser.add_argument('--cycle-interval',type=float,default=5)
    args=parser.parse_args()
    if args.records<1 or args.deadline<=0 or args.payload_bytes<128 or args.soak_seconds<0 or args.cycle_interval<0 or not 1<=args.batch_size<=10000 or not 1<=args.concurrency<=32:parser.error('Invalid record, payload, duration, batch or concurrency limits')
    if (args.family=='mapper') != (args.operation=='map'):parser.error('Mapper requires map; brokers require publish or receive')
    if args.family!='mapper' and not args.config:parser.error('Protected broker config required')
    release=host.keep_host_awake();process=psutil.Process();before=process.memory_info().rss
    try:
        if args.family=='mapper':
            source,mappings=mapper_case(0,args.payload_bytes);began=time.perf_counter();index=0;goal_seconds=None
            while index<args.records or time.perf_counter()-began<args.soak_seconds:
                source['seq']=index;result=map_record(source,mappings)
                if result['id']!=index or result['name']!='MINA CUSTOMER' or result['summary']['total']!=6:raise AssertionError('Mapper output mismatch')
                index+=1
                if index==args.records:goal_seconds=time.perf_counter()-began
            report={'passed':goal_seconds<=args.deadline,'records':args.records,'measuredSeconds':goal_seconds,
                'recordsPerSecond':args.records/goal_seconds,'soakSeconds':time.perf_counter()-began,'soakRecords':index,
                'measurement':'Mapper engine, eight mappings including functions and nested targets; no target XSD validation'}
        else:
            profile=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            report=asyncio.run(broker_soak(args,profile) if args.soak_seconds else broker_test(args,profile))
        report.update(family=args.family,operation=args.operation,targetRecords=args.records,deadlineSeconds=args.deadline,
            batchSize=args.batch_size,concurrency=args.concurrency,payloadBytes=args.payload_bytes,rssGrowthMiB=(process.memory_info().rss-before)/1048576)
    except Exception as error:
        report={'passed':False,'family':args.family,'operation':args.operation,'exceptionType':type(error).__name__}
        raise
    finally:
        release()
        if 'report' in locals():
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
