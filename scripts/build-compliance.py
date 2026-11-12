"""Build auditable license/notice bundles and CycloneDX manifests.

No application packages are imported. Metadata and installed license files are
read as data. Source downloads use PyPI's recorded SHA-256 and an explicit cache.
"""
from __future__ import annotations
import argparse,base64,hashlib,importlib.metadata as metadata,json,os,re,shutil,sys,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.distribution_compliance import sbom

BUILD_ONLY={'pip','setuptools','wheel','pyinstaller','pyinstaller-hooks-contrib','altgraph','pefile','pywin32-ctypes'}
SOURCE_REQUIRED={'paramiko','ldap3','psycopg','psycopg-binary','certifi'}
SAFE_NAME=re.compile(r'[^a-zA-Z0-9._-]+')


def normalized(name):return re.sub(r'[-_.]+','-',name).lower()


def read_url(url):
    if not url.startswith('https://'):raise ValueError('Compliance downloads require HTTPS')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'MINA-compliance/1'}),timeout=45) as response:
        if not response.url.startswith('https://'):raise ValueError('Insecure download redirect')
        return response.read()


def save(output,name,data):
    path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return {'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def source_archive(name,version,cache,fetch):
    if name=='psycopg-binary':name='psycopg'
    record=cache/(name+'-'+version+'.json')
    if not record.exists():
        if not fetch:raise ValueError('Missing source cache for '+name+' '+version+'; rerun with --fetch-sources')
        info=json.loads(read_url(f'https://pypi.org/pypi/{name}/{version}/json'))
        source=next((item for item in info['urls'] if item['packagetype']=='sdist'),None)
        if source is None:raise ValueError('No source distribution published for '+name+' '+version)
        data=read_url(source['url']);digest=hashlib.sha256(data).hexdigest()
        if digest!=source['digests']['sha256']:raise ValueError('Source checksum mismatch for '+name)
        cache.mkdir(parents=True,exist_ok=True)
        (cache/source['filename']).write_bytes(data)
        record.write_text(json.dumps({'file':source['filename'],'url':source['url'],'sha256':digest}),encoding='utf-8')
    result=json.loads(record.read_text(encoding='utf-8'))
    if Path(result['file']).name!=result['file'] or not re.fullmatch(r'[0-9a-f]{64}',result['sha256']):
        raise ValueError('Invalid cached source record: '+name)
    path=cache/result['file']
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=result['sha256']:raise ValueError('Cached source checksum mismatch: '+name)
    return result,data


def python_components(output,cache,fetch):
    components=[];records=[];errors=[]
    for dist in sorted(metadata.distributions(),key=lambda item:item.metadata['Name'].lower()):
        name=normalized(dist.metadata['Name'])
        # This component directory is generated output. Remove obsolete notice
        # layouts on retries so an earlier long-path bundle cannot leak back in.
        notice_root=(output/'licenses/python').resolve()
        notice_dir=output/'licenses/python'/name
        checked=notice_dir.resolve()
        if not checked.is_relative_to(notice_root) or checked==notice_root or notice_dir.is_symlink():
            raise ValueError('Unsafe generated license directory: '+str(notice_dir))
        if notice_dir.exists():
            deletion=str(checked)
            if os.name=='nt' and not deletion.startswith('\\\\?\\'):deletion='\\\\?\\'+deletion
            shutil.rmtree(deletion)
        identifier='pkg:pypi/'+name+'@'+dist.version
        license=dist.metadata.get('License-Expression') or dist.metadata.get('License') or ''
        license_files=[];base=Path(dist.locate_file('')).resolve()
        for file in dist.files or []:
            if not any(term in Path(str(file)).name.lower() for term in ('license','licence','copying','notice','copyright')):continue
            path=Path(dist.locate_file(file)).resolve()
            if not path.is_relative_to(base) or not path.is_file():continue
            if path.suffix.lower() in ('.py','.pyc','.pyd','.dll','.lic'):continue
            # Repeating the full .dist-info/package tree can exceed MAX_PATH
            # after Electron stages the legal bundle inside both runtimes.
            origin=str(file).replace('\\','/')
            filename='notice-'+hashlib.sha256(origin.encode()).hexdigest()[:12]+'.txt'
            target='licenses/python/'+name+'/'+filename
            license_files.append({**save(output,target,path.read_bytes()),'originalFile':origin})
        if name=='saxonche' and not license_files:
            # Upstream wheel omits license metadata; retain the publisher's MPL
            # terms and explicit source location rather than inventing a grant.
            mpl=ROOT/'compliance/third_party/saxonche/LICENSE'
            if mpl.is_file():license_files.append(save(output,'licenses/python/saxonche/LICENSE',mpl.read_bytes()))
            license='MPL-2.0'
        if not license_files:
            fallback=ROOT/'compliance/third_party'/name
            if fallback.is_dir():
                for file in fallback.iterdir():
                    if file.is_file():license_files.append(save(output,'licenses/python/'+name+'/'+file.name,file.read_bytes()))
        if not license_files:errors.append('No installed license/notice file found for '+name+' '+dist.version)
        source={'url':f'https://pypi.org/project/{name}/{dist.version}/#files'}
        if name in SOURCE_REQUIRED:
            try:
                source,data=source_archive(name,dist.version,cache,fetch)
                source={**source,**save(output,'sources/'+source['file'],data)}
            except (ValueError,OSError) as error:errors.append(str(error))
        if name=='saxonche':source={'url':'https://github.com/Saxonica/Saxon-HE/releases','note':'Obtain corresponding SaxonC-HE source and upstream native-runtime notices for this exact release.'}
        component={'type':'library','name':name,'version':dist.version,'bom-ref':identifier,'purl':identifier,
                   'externalReferences':[{'type':'distribution','url':f'https://pypi.org/project/{name}/{dist.version}/'}],
                   'properties':[{'name':'mina:inventory','value':'runtime-build-environment; artifact file inventory records actual payload'}]}
        if name in BUILD_ONLY:component['scope']='optional'
        if license:component['licenses']=[{'license':{'name':license[:500]}}]
        components.append(component)
        records.append({'name':name,'version':dist.version,'license':license[:500],'notices':license_files,'source':source})
    return components,records,errors


def node_components(output):
    components=[];records=[]
    # Renderer imports, not Vite/TypeScript/build-only packages.
    pending=['react','react-dom','scheduler','lucide-react'];seen=set()
    while pending:
        name=pending.pop()
        if name in seen:continue
        seen.add(name);folder=ROOT/'frontend/node_modules'/name
        package=json.loads((folder/'package.json').read_text(encoding='utf-8'))
        pending.extend(package.get('dependencies',{}))
        ref='pkg:npm/'+name+'@'+package['version'];notices=[]
        for file in folder.iterdir():
            if file.is_file() and any(word in file.name.lower() for word in ('license','licence','notice','copying')):
                notices.append(save(output,'licenses/npm/'+name+'/'+file.name,file.read_bytes()))
        if not notices:raise ValueError('Missing npm license: '+name)
        components.append({'type':'library','name':name,'version':package['version'],'bom-ref':ref,'purl':ref,
                           'licenses':[{'license':{'name':str(package.get('license','UNKNOWN'))}}]})
        records.append({'name':name,'version':package['version'],'notices':notices,'source':{'url':'https://www.npmjs.com/package/'+name+'/v/'+package['version']}})
    return components,records


def bundled_assets(output):
    result=[]
    for folder in sorted((ROOT/'compliance/third_party').glob('*')):
        if folder.is_dir():
            for file in sorted(folder.rglob('*')):
                if file.is_file():result.append(save(output,'licenses/assets/'+folder.name+'/'+file.relative_to(folder).as_posix(),file.read_bytes()))
    return result


def java_components(output,home):
    # Defensive normalization for direct CLI callers and legacy PowerShell
    # native argument quoting. Double quotes cannot be Windows path characters.
    raw_home=os.fspath(home).strip()
    if os.name=='nt':raw_home=raw_home.strip('"')
    home=Path(raw_home).resolve();release=home/'release';legal=home/'legal'
    if not release.is_file() or not legal.is_dir():
        raise ValueError(f'JDK release metadata/legal directory missing under {home}; select a complete OpenJDK with MINA_JAVA_HOME')
    text=release.read_text(encoding='utf-8')
    details=dict(re.findall(r'^([A-Z0-9_]+)="([^"\r\n]*)"',text,re.M))
    vendor=details.get('IMPLEMENTOR','').strip()
    version=details.get('JAVA_RUNTIME_VERSION') or details.get('JAVA_VERSION','')
    if not vendor or not version:raise ValueError('JDK release metadata must identify IMPLEMENTOR and JAVA_VERSION')
    license_paths=[path for path in (legal/'java.base/LICENSE',home/'LICENSE',home/'LICENSE.txt') if path.is_file()]
    license_text='\n'.join(path.read_text(encoding='utf-8',errors='replace') for path in license_paths)
    if not (re.search(r'GNU\s+General\s+Public\s+License',license_text,re.I) and
            re.search(r'Version\s+2\b',license_text,re.I) and
            re.search(r'classpath[^\n]{0,100}exception',license_text,re.I)):
        raise ValueError(f'JDK {vendor} {version} at {home} does not provide the expected GPLv2/Classpath license text. '
                         'Set MINA_JAVA_HOME to a complete GPLv2-with-Classpath OpenJDK; proprietary JDK redistribution is not automatically approved.')
    source=home/'lib/src.zip'
    if not source.is_file():raise ValueError(f'JDK library sources missing: {source}; install a complete OpenJDK including sources')
    save(output,'java/release',release.read_bytes())
    for file in legal.rglob('*'):
        if file.is_file():save(output,'java/legal/'+file.relative_to(legal).as_posix(),file.read_bytes())
    for file in license_paths:
        if not file.is_relative_to(legal):save(output,'java/'+file.name,file.read_bytes())
    save(output,'java/library-sources.zip',source.read_bytes())
    record={'implementor':vendor,'version':version,'releaseMetadata':details,
            'license':'GPL-2.0-only WITH Classpath-exception-2.0','sourceAccessStatus':'review-required'}
    save(output,'java/PROVENANCE.json',json.dumps(record,indent=2).encode())
    save(output,'java/SOURCE_ACCESS.txt',(f'Bundled {vendor} OpenJDK {version}: see java/release and PROVENANCE.json for the actual build.\n'
        'Obtain matching native/JDK build sources and source-access evidence from this distributor before public redistribution.\n'
        'The included library-sources.zip contains Java library sources, not the full native JDK build source.\n'
        'License-text detection is a technical check, not distribution-specific legal approval.\n').encode())
    return {'type':'application','name':vendor+' OpenJDK','version':version,'bom-ref':'runtime:openjdk:'+version,
            'licenses':[{'expression':record['license']}],'properties':[{'name':'mina:source-access','value':'review-required'}]}


def generate(args):
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    components,records=node_components(output);errors=[]
    if args.python:
        python,python_records,python_errors=python_components(output,Path(args.cache).resolve(),args.fetch_sources)
        components+=python;records+=python_records;errors+=python_errors
        # The interpreter is embedded by PyInstaller, independently of wheels.
        license=Path(sys.base_prefix)/'LICENSE.txt'
        if license.is_file():save(output,'licenses/python-interpreter/LICENSE.txt',license.read_bytes())
        else:errors.append('Python interpreter LICENSE.txt not found at '+str(license))
    assets=bundled_assets(output)
    if args.java_home:
        try:components.append(java_components(output,args.java_home))
        except ValueError as error:errors.append(str(error))
    notices=['MINA THIRD-PARTY NOTICES',
        'This document does not relicense MINA or customer application source.',
        'The licenses and copyright notices below apply to the identified third-party components.',
        'Third-party license rights take precedence over conflicting product restrictions for those components.',
        'Recipients may modify/replace LGPL-covered libraries and reverse engineer for debugging those modifications as permitted by their licenses.',
        'MINA_LIBRARY_PATH selects recipient-controlled replacement libraries before application imports. See REPLACEMENT_LIBRARIES.txt.',
        'Distribute this complete legal directory, including sources and source-access records, with the application.',
        'Build-environment inventory is identified separately from the artifact file inventory. No legal-clearance certification is asserted.']
    notices.extend(record['name']+' '+record['version']+'\n'+ '\n'.join(file['path'] for file in record['notices']) for record in records)
    save(output,'THIRD_PARTY_NOTICES.txt',('\n\n'.join(notices)+'\n').encode())
    save(output,'REPLACEMENT_LIBRARIES.txt',b'Set MINA_LIBRARY_PATH to an existing absolute directory containing compatible replacement paramiko, ldap3, psycopg, psycopg_binary, certifi or saxonche libraries.\nRestart the runtime; use MINARuntime.exe --mina-library-info or MINAWorker.exe --mina-library-info to inspect resolution.\nOnly these library names can be overridden; MINA application modules are not overridden. The setting is controlled by the process owner, never project input.\nKeep Python ABI and native DLL compatibility. An incompatible replacement can prevent startup; remove the setting to restore bundled libraries.\n')
    save(output,'COMPONENTS.json',json.dumps({'components':records,'assets':assets},indent=2).encode())
    save(output,'SBOM.cdx.json',json.dumps(sbom('MINA Studio runtime build inventory','1.0.3',components),indent=2).encode())
    report={'technicalChecks':'passed' if not errors else 'failed','errors':errors,
            'legalClearance':'not-certified','runtimeComponents':len(components),
            'remainingReleaseReview':['Confirm vendor binary redistribution rights or exclude them.','Verify exact SaxonC native-runtime source/notices and full JDK corresponding-source access.','Confirm asset/trademark provenance for externally supplied artwork.']}
    save(output,'RELEASE_REVIEW.json',json.dumps(report,indent=2).encode())
    if errors:raise ValueError('\n'.join(errors))
    print(json.dumps({'output':str(output),'components':len(components),'technicalChecks':'passed'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--python',action='store_true')
    parser.add_argument('--cache',default=str(ROOT/'tmp/compliance-source-cache'))
    parser.add_argument('--fetch-sources',action='store_true');parser.add_argument('--java-home')
    generate(parser.parse_args())
