"""Build the distributable sample ZIP without generated certificates or private keys."""
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT.parent/'MINA-HTTP-REST-Examples.zip'

def bundle():
    files=[ROOT/name for name in ('README.md','catalog.json','requirements.txt','prepare.py','oauth_fixture.py','tokens.py','verify_examples.py','build_examples.py','bundle_examples.py','install_studio_samples.py')]
    for directory,pattern in (('projects','*.mpackage'),('specs','*.json'),('postman','*.json')):files.extend(sorted((ROOT/directory).glob(pattern)))
    if (ROOT/'verification-report.json').exists():files.append(ROOT/'verification-report.json')
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,'MINA-HTTP-REST-Examples/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUTPUT) as archive:
        assert not any('/local/' in name or name.endswith(('.pem','.key')) for name in archive.namelist())
        assert len([name for name in archive.namelist() if name.endswith('.mpackage')])==20
    print(OUTPUT)
    print(f'{len(files)} files; {OUTPUT.stat().st_size:,} bytes; no generated private keys/certificates.')

if __name__=='__main__':bundle()
