"""Concurrent disposable File/FTP/FTPS/SFTP/SQLite/MySQL qualification.

Test-only dependencies: psutil, pyftpdlib, pyOpenSSL, paramiko, cryptography,
and PyMySQL. MINA_TEST_MYSQLD optionally enables a NEW local MySQL datadir.
Never connects to a configured customer database or transfer endpoint.
"""
from __future__ import annotations
import argparse,base64,contextlib,gc,hashlib,json,logging,os,sqlite3,statistics,subprocess,sys,tempfile,threading,time,tracemalloc
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def serve(config_path):
    from tests.connector_fixtures import certificates
    from tests.test_transfer_network import ftp_server,sftp_server
    from tests.test_mysql_live import MySQLLiveTests
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix='connector-soak-server-',dir=ROOT/'tmp') as directory,contextlib.ExitStack() as stack:
        root=Path(directory);configs={}
        for kind in ('ftp','ftps','sftp'):
            folder=root/kind;folder.mkdir()
            cfg=stack.enter_context(sftp_server(folder) if kind=='sftp' else ftp_server(folder,certificates(folder) if kind=='ftps' else None))
            configs[kind]={**cfg,'timeout':10}
        if os.environ.get('MINA_TEST_MYSQLD'):
            MySQLLiveTests.setUpClass();stack.callback(MySQLLiveTests.tearDownClass)
            configs['mysql']=MySQLLiveTests.config
        Path(config_path).write_text(json.dumps({'pid':os.getpid(),'configs':configs}),encoding='utf-8')
        sys.stdin.readline()  # Parent requests graceful cleanup, including MySQL shutdown.


def measure(process):
    data={'rss':process.memory_info().rss,'threads':process.num_threads()}
    data['handles']=process.num_handles() if hasattr(process,'num_handles') else process.num_fds()
    try:data['private']=getattr(process.memory_info(),'private',process.memory_full_info().uss)
    except Exception:pass
    return data


def percent(values,p):
    ordered=sorted(values)
    return ordered[min(len(ordered)-1,int((len(ordered)-1)*p))] if ordered else 0


def run(args):
    import psutil
    from app.file_operations import file_activity
    from app.transfer import transfer
    from app.jdbc import execute
    logging.disable(logging.CRITICAL)
    (ROOT/'tmp').mkdir(parents=True,exist_ok=True)
    report=Path(args.report).resolve();report.parent.mkdir(parents=True,exist_ok=True)
    total_workers={'file':4,'ftp':4,'ftps':2,'sftp':4,'sqlite':4,'mysql':4}
    stop=threading.Event();lock=threading.Lock();stats={};samples=[];pool=None;server=None
    started=time.monotonic();result={'startedAt':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'durationSeconds':args.duration_seconds,'warmupSeconds':args.warmup_seconds,'payloadBytes':args.payload_bytes,'status':'starting','samples':samples}
    report.write_text(json.dumps(result,indent=2))
    with tempfile.TemporaryDirectory(prefix='connector-soak-client-',dir=ROOT/'tmp') as directory:
        root=Path(directory);config_path=root/'servers.json';server_log=(report.parent/(report.stem+'-servers.log')).open('w',encoding='utf-8')
        try:
            server=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--serve',str(config_path)],cwd=ROOT,stdin=subprocess.PIPE,stdout=server_log,stderr=server_log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+120
            while not config_path.exists():
                if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Disposable servers failed to start; inspect server log')
                time.sleep(.1)
            published=json.loads(config_path.read_text());configs=published['configs']
            result['serverPid']=published['pid']
            if 'mysql' not in configs:total_workers.pop('mysql')
            sqlite_cfg={'driver':'sqlite','url':str(root/'soak.sqlite'),'timeoutSeconds':10}
            conn=sqlite3.connect(sqlite_cfg['url']);conn.execute('PRAGMA journal_mode=WAL');conn.execute('CREATE TABLE soak_rows(id TEXT PRIMARY KEY,value TEXT)');conn.commit();conn.close()
            if 'mysql' in configs:execute(configs['mysql'],{'operation':'dynamic','sql':'CREATE TABLE soak_rows(id VARCHAR(64) PRIMARY KEY,value VARCHAR(128))'})
            result['workers']=total_workers;result['infrastructure']='Disposable loopback FTP/FTPS/SFTP, SQLite WAL, optional fresh TLS MySQL; servers isolated in a child process.'
            payload='MINA-SOAK-'+'x'*max(0,args.payload_bytes-10);digest=hashlib.sha256(payload.encode()).hexdigest();encoded=base64.b64encode(payload.encode()).decode()
            for lane in total_workers:stats[lane]={'cycles':0,'operations':0,'errors':0,'latencies':deque(maxlen=4096),'errorExamples':[]}
            def cycle(lane,worker,index):
                key=f'{lane}-{worker}'
                if lane=='file':
                    folder=root/key;folder.mkdir(exist_ok=True);source=folder/'source';target=folder/'target'
                    file_activity('write',{'path':str(source),'textContent':payload,'overwrite':True},None)
                    file_activity('copy',{'path':str(source),'destination':str(target),'overwrite':True},None)
                    value=file_activity('read',{'path':str(target),'maxReadBytes':args.payload_bytes+100},None)['textContent']
                    if hashlib.sha256(value.encode()).hexdigest()!=digest:raise AssertionError('File checksum mismatch')
                    listing=file_activity('list',{'path':str(folder),'maxEntries':3},None)
                    if listing['count']!=2:raise AssertionError('Unexpected file/temp entry count')
                    return 4
                if lane in ('ftp','ftps','sftp'):
                    kind='ftp' if lane=='ftps' else lane;cfg=configs[lane];remote=key+'.bin';local=root/(key+'.upload');download=root/(key+'.download')
                    if not local.exists():local.write_bytes(payload.encode())
                    transfer(kind,'put',{**cfg,'remotePath':remote,'localPath':str(local),'atomicUpload':True,'overwrite':True})
                    transfer(kind,'get',{**cfg,'remotePath':remote,'localPath':str(download),'overwrite':True,'maxDownloadBytes':args.payload_bytes+100})
                    if hashlib.sha256(download.read_bytes()).hexdigest()!=digest:raise AssertionError('Transfer checksum mismatch')
                    transfer(kind,'delete',{**cfg,'remotePath':remote})
                    return 3
                cfg=sqlite_cfg if lane=='sqlite' else configs['mysql'];key+=f'-{index}'
                execute(cfg,{'operation':'insert','sql':'INSERT INTO soak_rows VALUES (:id,:value)','parameters':{'id':key,'value':digest}})
                rows=execute(cfg,{'sql':'SELECT value FROM soak_rows WHERE id=:id','parameters':{'id':key},'maxRows':1})['rows']
                if rows!=[{'value':digest}]:raise AssertionError('Database result mismatch')
                execute(cfg,{'operation':'delete','sql':'DELETE FROM soak_rows WHERE id=:id','parameters':{'id':key}})
                return 3
            def worker(lane,number):
                index=0
                while not stop.is_set():
                    tick=time.monotonic()
                    try:
                        operations=cycle(lane,number,index)
                        with lock:stats[lane]['cycles']+=1;stats[lane]['operations']+=operations;stats[lane]['latencies'].append(time.monotonic()-tick)
                    except Exception as error:
                        with lock:
                            stats[lane]['errors']+=1
                            if len(stats[lane]['errorExamples'])<10:stats[lane]['errorExamples'].append(type(error).__name__+': '+str(error))
                    index+=1;stop.wait(args.pacing_seconds)
            def summary():
                with lock:return {lane:{key:value for key,value in state.items() if key!='latencies'}|{'recentP50Seconds':percent(state['latencies'],.5),'recentP95Seconds':percent(state['latencies'],.95)} for lane,state in stats.items()}
            process=psutil.Process();server_process=psutil.Process(published['pid'])
            gc.collect();idle=measure(process);tracemalloc.start(4)
            pool=ThreadPoolExecutor(max_workers=sum(total_workers.values()),thread_name_prefix='mina-soak')
            futures=[pool.submit(worker,lane,index) for lane,count in total_workers.items() for index in range(count)]
            # Warm, then quiesce before measuring: native crypto/cache initialization is
            # not a leaked per-operation handle. Compare idle-to-idle on the same warmed process.
            stop.wait(args.warmup_seconds);stop.set();pool.shutdown(wait=True);pool=None
            for future in futures:future.result()
            del future;futures=[]
            time.sleep(5);gc.collect();idle=measure(process)
            baseline_counts=summary();result['warmIdle']=idle
            stop=threading.Event();pool=ThreadPoolExecutor(max_workers=sum(total_workers.values()),thread_name_prefix='mina-soak')
            futures=[pool.submit(worker,lane,index) for lane,count in total_workers.items() for index in range(count)]
            measured_start=time.monotonic();finish=measured_start+args.duration_seconds;baseline=None;snapshot=None
            result['status']='running'
            while time.monotonic()<finish:
                tick=time.monotonic();before_gc=tracemalloc.get_traced_memory()[0];gc_start=time.monotonic();collected=gc.collect();gc_seconds=time.monotonic()-gc_start
                point={'elapsedSeconds':tick-started,'measuredSeconds':max(0,tick-measured_start),**measure(process),'pythonCurrent':tracemalloc.get_traced_memory()[0],'gcCounts':gc.get_count(),'gcCollections':[v['collections'] for v in gc.get_stats()]}
                point.update(pythonBeforeGc=before_gc,gcCollected=collected,gcSeconds=gc_seconds,gcUncollectable=[v['uncollectable'] for v in gc.get_stats()],lanes=summary())
                with contextlib.suppress(Exception):point['server']=measure(server_process)
                if baseline is None:baseline=point.copy();snapshot=tracemalloc.take_snapshot()
                samples.append(point);result['lanes']=summary();result['elapsedSeconds']=tick-started
                report.write_text(json.dumps(result,indent=2))
                print(json.dumps({'elapsed':round(tick-started),'measured':round(point['measuredSeconds']),'rssMiB':round(point['rss']/1024**2,1),'handles':point['handles'],'threads':point['threads'],'cycles':{k:v['cycles'] for k,v in result['lanes'].items()},'errors':sum(v['errors'] for v in result['lanes'].values())}),flush=True)
                stop.wait(min(args.sample_seconds,max(0,finish-time.monotonic())))
            stop.set();pool.shutdown(wait=True);pool=None
            for future in futures:future.result()
            del future;futures=[]
            time.sleep(5);gc.collect();final=measure(process);final['pythonCurrent']=tracemalloc.get_traced_memory()[0]
            result['lanes']=summary();result['idleBefore']=idle;result['quiescentAfter']=final;result['warmBaseline']=baseline;result['warmLaneCounts']=baseline_counts
            measured=[v for v in samples if v['measuredSeconds']>0]
            late=measured[len(measured)//2:]
            slope=0.0
            if len(late)>1:
                xs=[v['elapsedSeconds']/60 for v in late];ys=[v['rss']/1024**2 for v in late];mean=statistics.mean(xs)
                slope=sum((x-mean)*(y-statistics.mean(ys)) for x,y in zip(xs,ys))/sum((x-mean)**2 for x in xs)
            result['rssSlopeMiBPerMinute']=slope
            result['growth']={'rssMiB':(final['rss']-baseline['rss'])/1024**2 if baseline else None,'pythonMiB':(final['pythonCurrent']-baseline['pythonCurrent'])/1024**2 if baseline else None,'idleHandles':final['handles']-idle['handles'],'idleThreads':final['threads']-idle['threads']}
            if snapshot:result['topPythonGrowth']=[str(v) for v in tracemalloc.take_snapshot().compare_to(snapshot,'lineno')[:12]]
            tracemalloc.stop()
            problems=[]
            if sum(v['errors'] for v in result['lanes'].values()):problems.append('Operation errors occurred')
            if result['growth']['rssMiB'] is not None and result['growth']['rssMiB']>64:problems.append('Post-warm-up RSS growth exceeds 64 MiB')
            if result['growth']['pythonMiB'] is not None and result['growth']['pythonMiB']>8:problems.append('Retained Python growth exceeds 8 MiB')
            if args.duration_seconds>=300 and slope>.5:problems.append('Late RSS slope exceeds 0.5 MiB/minute')
            if result['growth']['idleHandles']>20:problems.append('Quiescent handles increased by more than 20')
            if result['growth']['idleThreads']>4:problems.append('Quiescent threads increased by more than 4')
            result['problems']=problems;result['status']='failed' if problems else 'passed'
        except BaseException as error:
            result['status']='interrupted' if isinstance(error,KeyboardInterrupt) else 'error';result['error']=type(error).__name__+': '+str(error)
            raise
        finally:
            stop.set()
            if pool:pool.shutdown(wait=True)
            if server:
                with contextlib.suppress(Exception):server.stdin.write('stop\n');server.stdin.flush()
                try:server.wait(35)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(Exception):
                        for child in psutil.Process(server.pid).children(recursive=True):child.kill()
                    server.kill();server.wait(5)
            server_log.close();result['finishedAt']=datetime.now(timezone.utc).isoformat();result['elapsedSeconds']=time.monotonic()-started
            report.write_text(json.dumps(result,indent=2))
    print('SOAK '+result['status'].upper()+' '+str(report),flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve');parser.add_argument('--duration-seconds',type=int,default=1800);parser.add_argument('--warmup-seconds',type=int,default=60);parser.add_argument('--sample-seconds',type=int,default=30);parser.add_argument('--pacing-seconds',type=float,default=.15);parser.add_argument('--payload-bytes',type=int,default=65536);parser.add_argument('--report',default=str(ROOT/'tmp/connector-soak-report.json'))
    args=parser.parse_args()
    if args.serve:serve(args.serve)
    else:
        if min(args.duration_seconds,args.sample_seconds,args.payload_bytes)<=0 or args.warmup_seconds<0 or args.pacing_seconds<0:parser.error('Durations, sample and payload must be positive; warmup/pacing nonnegative')
        sys.exit(run(args))
