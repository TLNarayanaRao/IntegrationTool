"""Record and verify the files actually present in a staged MINA artifact."""
import argparse,hashlib,importlib.metadata as metadata,json,platform,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.distribution_compliance import sbom

DENIED=re.compile(r'^(?:lib)?(?:tibems|tibjms|sapjco|sapidoc)',re.I)
BINARY=re.compile(r'\.(?:lib|a|dll|jar|dylib|lic|so(?:\.[0-9]+)*)$',re.I)


def bundled_components(root):
    """Identify actual frozen imports/native extensions, not every build tool."""
    from PyInstaller.archive.readers import CArchiveReader
    modules=set();native_names={path.name.lower() for path in root.rglob('*.pyd')}
    for executable in root.rglob('*.exe'):
        if executable.name not in {'MINARuntime.exe','MINAWorker.exe'}:continue
        archive=CArchiveReader(str(executable))
        for name in archive.toc:
            if name.lower().endswith('.pyz'):modules.update(archive.open_embedded_archive(name).toc)
    found={}
    for dist in metadata.distributions():
        included=False
        for file in dist.files or []:
            text=str(file).replace('\\','/')
            if text.endswith('.py'):
                name=text[:-3].replace('/','.').removesuffix('.__init__')
                if name in modules:included=True;break
            elif text.endswith('.pyd') and Path(text).name.lower() in native_names:included=True;break
        if not included:continue
        name=re.sub(r'[-_.]+','-',dist.metadata['Name']).lower();ref=f'pkg:pypi/{name}@{dist.version}'
        component={'type':'library','name':name,'version':dist.version,'bom-ref':ref,'purl':ref}
        license=dist.metadata.get('License-Expression') or dist.metadata.get('License')
        if license:component['licenses']=[{'license':{'name':license[:500]}}]
        found[ref]=component
    version_file=root/'version'
    if version_file.is_file():
        version=version_file.read_text(encoding='utf-8').strip()
        found['electron']={'type':'application','name':'electron','version':version,'bom-ref':'runtime:electron',
                           'licenses':[{'license':{'id':'MIT'}}]}
    if modules:
        found['python']={'type':'application','name':'CPython','version':platform.python_version(),
                         'bom-ref':'runtime:cpython','licenses':[{'license':{'id':'PSF-2.0'}}]}
    for release in root.glob('**/legal/java/release'):
        text=release.read_text(encoding='utf-8')
        version=re.search(r'^JAVA_RUNTIME_VERSION="([^"]+)"',text,re.M) or re.search(r'^JAVA_VERSION="([^"]+)"',text,re.M)
        if version:
            value=version.group(1)
            vendor=re.search(r'^IMPLEMENTOR="([^"\r\n]+)"',text,re.M)
            name=(vendor.group(1) if vendor else 'Unknown distributor')+' OpenJDK'
            found['openjdk:'+value]={'type':'application','name':name,'version':value,
                'bom-ref':'runtime:openjdk:'+value,
                'licenses':[{'expression':'GPL-2.0-only WITH Classpath-exception-2.0'}]}
    return sorted(found.values(),key=lambda item:item['bom-ref'])


def inventory(root,output):
    root=root.resolve();output=output.resolve();components=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.resolve()==output:continue
        relative=path.relative_to(root).as_posix()
        if DENIED.match(path.name) and BINARY.search(path.name):
            raise ValueError('Unverified vendor binary in release: '+relative)
        if 'drivers' in path.parts and BINARY.search(path.name):
            raise ValueError('Customer-supplied driver must not be bundled: '+relative)
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        components.append({'type':'file','name':relative,'bom-ref':'file:'+relative,
                           'hashes':[{'alg':'SHA-256','content':digest}]})
    return components


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root');parser.add_argument('--output',required=True)
    parser.add_argument('--verify',action='store_true');parser.add_argument('--version',default='1.0.3')
    parser.add_argument('--software-only',action='store_true')
    parser.add_argument('--installer')
    args=parser.parse_args();root=Path(args.root);output=Path(args.output)
    components=inventory(root,output)
    if args.installer:
        installer=Path(args.installer)
        with installer.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        components.append({'type':'file','name':installer.name,'bom-ref':'installer:'+installer.name,
                           'hashes':[{'alg':'SHA-256','content':digest}]})
    if args.verify:
        recorded=[item for item in json.loads(output.read_text(encoding='utf-8'))['components'] if item['type']=='file']
        if recorded!=components:raise ValueError('Artifact files changed after SBOM generation')
        print('Artifact SBOM hashes verified:',len(components))
    else:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(sbom('MINA distributed artifact',args.version,([] if args.software_only else components)+bundled_components(root)),indent=2),encoding='utf-8')
        print('Artifact SBOM generated:',len(components))
