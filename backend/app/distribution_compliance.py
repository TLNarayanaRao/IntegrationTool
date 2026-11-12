"""Offline, content-addressed legal manifests for generated Python archives.

Exported application source is distinguished from external dependencies: a
builder's installed Python versions are never presented as deployed versions.
"""
from __future__ import annotations
import hashlib,json,uuid
from pathlib import Path


def sbom(name,version,components,dependencies=None):
    root={'type':'application','name':name,'bom-ref':'mina:artifact'}
    if version:root['version']=version
    content={'bomFormat':'CycloneDX','specVersion':'1.6','version':1,
             'metadata':{'component':root},'components':components,
             'dependencies':dependencies or [{'ref':'mina:artifact','dependsOn':[item['bom-ref'] for item in components]}]}
    fingerprint=hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    content['serialNumber']='urn:uuid:'+str(uuid.uuid5(uuid.NAMESPACE_URL,'mina:sbom:'+fingerprint))
    return content


def archive_legal_files(files,project,kind,checks,external_files):
    components=[]
    for name,data in sorted(files.items()):
        components.append({'type':'file','name':name,'bom-ref':'file:'+name,
                           'hashes':[{'alg':'SHA-256','content':hashlib.sha256(data).hexdigest()}]})
    # These are installation requirements, not bundled third-party packages.
    requirements=[]
    for check in checks:
        for name in check.get('modules',[]):
            requirements.append({'name':name,'capability':check['name'],'install':check['install']})
    for item in requirements:
        ref='external:'+item['name']
        if any(component['bom-ref']==ref for component in components):continue
        components.append({'type':'library','name':item['name'],'bom-ref':ref,'scope':'optional',
            'properties':[{'name':'mina:distribution','value':'not-bundled; install on target'},
                          {'name':'mina:installation-instruction','value':item['install']}]})
    legal={'legal/SBOM.cdx.json':json.dumps(sbom('MINA '+kind+' Python application',project.get('version'),components),indent=2).encode(),
           'legal/DEPENDENCIES.json':json.dumps({'format':kind,'resolution':'external-unresolved',
               'requirements':requirements,'customerSuppliedFiles':external_files},indent=2).encode()}
    notices=['MINA GENERATED PYTHON APPLICATION — THIRD-PARTY NOTICES',
             'This manifest does not relicense MINA source, your application, or customer assets.',
             'External Python packages and vendor drivers are not bundled in this archive.',
             'Install compatible packages on the target and retain their licenses and notices.',
             'The SBOM records shipped file hashes and separately identifies unresolved installation requirements.',
             'No third-party license rights are restricted by this notice. Applicable component licenses take precedence.',
             'Vendor JARs, native clients, certificates and credentials must be supplied under your own rights.']
    if any(name.endswith('/swagger_assets.py') for name in files):
        import importlib.util
        spec=importlib.util.spec_from_file_location('_mina_export_swagger_assets',Path(__file__).with_name('swagger_assets.py'))
        assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
        ASSETS,VERSION=assets.ASSETS,assets.VERSION
        import base64,gzip
        for name in ('LICENSE','NOTICE'):
            legal['legal/swagger-ui/'+name]=gzip.decompress(base64.b64decode(ASSETS[name]['data']))
        notices.append('Bundled Swagger UI '+VERSION+' — Apache-2.0; see swagger-ui/LICENSE and NOTICE.')
        document=json.loads(legal['legal/SBOM.cdx.json'])
        document['components'].append({'type':'library','name':'swagger-ui-dist','version':VERSION,
            'bom-ref':'pkg:npm/swagger-ui-dist@'+VERSION,'purl':'pkg:npm/swagger-ui-dist@'+VERSION,
            'licenses':[{'license':{'id':'Apache-2.0'}}]})
        document['dependencies'][0]['dependsOn'].append('pkg:npm/swagger-ui-dist@'+VERSION)
        legal['legal/SBOM.cdx.json']=json.dumps(document,indent=2).encode()
    legal['legal/THIRD_PARTY_NOTICES.txt']=('\n\n'.join(notices)+'\n').encode()
    legal['legal/README.txt']=(
        'SBOM.cdx.json is CycloneDX 1.6. File hashes cover application files before legal metadata is added.\n'
        'DEPENDENCIES.json describes externally installed requirements; it is not an installed-version lock.\n'
        'No claim of legal clearance is made for user-supplied code, schemas, binaries or artwork.\n'
        'Regenerate a resolved SBOM after installing packages in the target environment.\n').encode()
    return legal
