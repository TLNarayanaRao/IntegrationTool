"""Extract and verify NSIS payloads without installing over the user's Studio."""
from __future__ import annotations
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run(*arguments,**options):
    result=subprocess.run(list(map(str,arguments)),capture_output=True,text=True,**options)
    if result.returncode:raise RuntimeError(result.stdout[-5000:]+result.stderr[-5000:])
    return result.stdout


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('installer');args=parser.parse_args()
    installer=Path(args.installer).resolve()
    candidates=[ROOT/'frontend/node_modules/7zip-bin/win/x64/7za.exe',
                ROOT/'frontend/node_modules/electron-winstaller/vendor/7z.exe']
    seven=next((path for path in candidates if path.is_file()),None)
    if seven is None:raise ValueError('Install frontend build dependencies to obtain 7-Zip')
    with tempfile.TemporaryDirectory(prefix='installer-legal-',dir=ROOT/'tmp') as folder:
        folder=Path(folder)
        run(seven,'x',installer,'-o'+str(folder/'outer'),'-y',timeout=180)
        packages=list((folder/'outer').rglob('app-64.7z'))
        if len(packages)!=1:raise ValueError('Expected one x64 application payload inside NSIS')
        target=folder/'payload';run(seven,'x',packages[0],'-o'+str(target),'-y',timeout=180)
        manifest=installer.with_name(installer.name.replace('-Setup.exe','-Payload-SBOM.cdx.json'))
        print(run(sys.executable,ROOT/'scripts/artifact-sbom.py',target,'--output',manifest,'--installer',installer,'--verify',timeout=180).strip())
        for name in ('MINARuntime','MINAWorker'):
            runtime=target/'resources/runtime'/name
            print(run(sys.executable,ROOT/'scripts/artifact-sbom.py',runtime,'--output',runtime/'legal/SBOM.artifact.cdx.json','--verify',timeout=180).strip())
            legal=runtime/'legal'
            for file in ('THIRD_PARTY_NOTICES.txt','SBOM.cdx.json','RELEASE_REVIEW.json','REPLACEMENT_LIBRARIES.txt'):
                if not (legal/file).is_file():raise ValueError('Missing packaged legal document: '+str(file))
            for library in ('paramiko','ldap3','psycopg','certifi'):
                if not (legal/'licenses/python'/library).is_dir():raise ValueError('Missing library license: '+library)
            bundled=json.loads((legal/'SBOM.artifact.cdx.json').read_text(encoding='utf-8'))
            for component in bundled['components']:
                if component.get('purl','').startswith('pkg:pypi/') and not (legal/'licenses/python'/component['name']).is_dir():
                    raise ValueError('Bundled Python component has no license directory: '+component['name'])
            if not list((legal/'sources').glob('*')):raise ValueError('Missing corresponding-source archives')
            if not (legal/'java/library-sources.zip').is_file():raise ValueError('Missing Java library source material')
            bridge=runtime/'java-bridge/classes/com/mina/bridge/MinaJavaBridge.class'
            java=runtime/'java-bridge/runtime/bin/java.exe'
            if not bridge.is_file() or not java.is_file():raise ValueError('Missing bundled Java bridge/runtime: '+name)
            run(java,'-version',timeout=30)
            replacement=folder/'replacement';(replacement/'paramiko').mkdir(parents=True,exist_ok=True)
            (replacement/'paramiko/__init__.py').write_text('RECIPIENT_REPLACEMENT=True\n')
            resolved=json.loads(run(runtime/(name+'.exe'),'--mina-library-info',env={**os.environ,'MINA_LIBRARY_PATH':str(replacement)},timeout=30))
            if Path(resolved['paramiko']).resolve()!=(replacement/'paramiko/__init__.py').resolve():
                raise ValueError('Frozen runtime did not honor the library replacement directory')
        runtime=target/'resources/runtime/MINARuntime/MINARuntime.exe'
        print(run(sys.executable,ROOT/'scripts/smoke-test-packaged-runtime.py',runtime,timeout=90).strip())
        print('Installer payload: hashes, notices, sources, bundled Java, replacement-library resolution and designer/runtime HTTP checks passed.')


if __name__=='__main__':main()
