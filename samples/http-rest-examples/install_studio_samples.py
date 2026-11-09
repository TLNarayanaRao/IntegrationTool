"""Copy portable API project templates into the installed Studio Samples gallery."""
import json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DEST=ROOT.parents[1]/'frontend/public/samples'

def install():
    target=DEST/'http-rest';target.mkdir(exist_ok=True)
    catalog=json.loads((DEST/'catalog.json').read_text(encoding='utf-8'))
    catalog=[item for item in catalog if item.get('family')!='http-rest']
    scenarios=json.loads((ROOT/'catalog.json').read_text())['scenarios']
    for item in scenarios:
        slug=Path(item['file']).stem
        with zipfile.ZipFile(ROOT/item['file']) as archive:project=json.loads(archive.read('project.json'))
        for properties in project['properties'].values():
            for prop in properties:
                if prop['key']=='demo.directory':prop['value']=''
        (target/(slug+'.json')).write_text(json.dumps(project,indent=2),encoding='utf-8')
        secure=item['port']>=9443
        description=('Host on port '+str(item['port'])+'. ' if item['role']=='host' else 'Start '+str(item['pairedProject'])+' first. ')
        description+=('Set local demo.directory to the prepared helper kit local folder. ' if secure else '')
        if item['port']==9446:description+='Start the local OAuth fixture before running this example. '
        if slug.startswith('13'):description+='Default confidentiality enforces HTTPS with certificate and hostname verification. '
        activities=sorted({activity['name'] for task in project['tasks'] for activity in task['activities']})
        catalog.append({'id':'http-rest-'+slug,'name':slug[:2]+' · '+item['title'],'category':'HTTP & REST / '+('Hosting' if item['role']=='host' else 'Calls'),'description':description.strip(),'activities':activities,'file':'/samples/http-rest/'+slug+'.json','ready':item['role']=='host' and not secure,'family':'http-rest'})
    (DEST/'catalog.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
    shutil.copyfile(ROOT/'README.md',target/'README.md')
    shutil.copyfile(ROOT.parent/'MINA-HTTP-REST-Examples.zip',target/'MINA-HTTP-REST-Examples.zip')
    print('Installed 20 API examples in the Studio Samples gallery; machine paths and generated certificates excluded.')

if __name__=='__main__':install()
