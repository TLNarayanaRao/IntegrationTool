import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import raw_python
from app.distribution_compliance import archive_legal_files

ROOT=Path(__file__).resolve().parents[2]


def script(name):
    spec=importlib.util.spec_from_file_location('_legal_'+name.replace('-','_'),ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class DistributionComplianceTests(unittest.TestCase):
    def test_archive_inventory_hashes_and_external_dependencies_are_honest(self):
        files={'application/main.py':b'print("hello")\n'}
        output=archive_legal_files(files,{},'Direct',[{'name':'HTTP','modules':['httpx'],'install':'python -m pip install httpx'}],[])
        bom=json.loads(output['legal/SBOM.cdx.json'])
        self.assertEqual(bom['specVersion'],'1.6')
        shipped=next(item for item in bom['components'] if item['type']=='file')
        self.assertEqual(shipped['hashes'][0]['content'],hashlib.sha256(files[shipped['name']]).hexdigest())
        external=next(item for item in bom['components'] if item['name']=='httpx')
        self.assertNotIn('version',external)
        self.assertEqual(external['scope'],'optional')
        self.assertIn('not-bundled',str(external))

    def test_both_formats_include_actual_swagger_license_and_notice(self):
        from tests.test_api_blueprint import plan_project
        from app.swagger_assets import VERSION
        project,_=plan_project()
        for compiler in (raw_python.raw_python_files,raw_python.engine_python_files):
            files=compiler(project.model_dump(),{'local':[]})
            self.assertIn(b'Apache License',files['legal/swagger-ui/LICENSE'])
            self.assertTrue(files['legal/swagger-ui/NOTICE'])
            bom=json.loads(files['legal/SBOM.cdx.json'])
            self.assertTrue(any(item['name']=='swagger-ui-dist' and item['version']==VERSION for item in bom['components']))
            for item in bom['components']:
                if item['type']=='file':self.assertEqual(item['hashes'][0]['content'],hashlib.sha256(files[item['name']]).hexdigest())

    def test_artifact_rejects_vendor_binaries_and_detects_tampering(self):
        module=script('artifact-sbom')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'legal/sbom.json';(root/'app.py').write_text('print(1)')
            before=module.inventory(root,manifest)
            (root/'app.py').write_text('print(2)')
            self.assertNotEqual(before,module.inventory(root,manifest))
            (root/'tibems.lib').write_bytes(b'vendor')
            with self.assertRaisesRegex(ValueError,'Unverified vendor binary'):module.inventory(root,manifest)

    def test_recipient_can_replace_library_without_overriding_application(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('paramiko','app'):
                (root/name).mkdir();(root/name/'__init__.py').write_text('REPLACED=True\n')
            code='from app.library_overrides import activate; activate(); import paramiko,app; assert paramiko.REPLACED; assert not hasattr(app,"REPLACED")'
            result=subprocess.run([sys.executable,'-c',code],cwd=ROOT/'backend',env={**os.environ,'MINA_LIBRARY_PATH':str(root)},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            invalid=subprocess.run([sys.executable,'-c','from app.library_overrides import activate; activate()'],cwd=ROOT/'backend',env={**os.environ,'MINA_LIBRARY_PATH':'relative-path'},capture_output=True,text=True)
            self.assertNotEqual(invalid.returncode,0)
            self.assertIn('absolute directories',invalid.stderr)

    def test_source_cache_checksums_and_public_release_review_fail_closed(self):
        builder=script('build-compliance');reviewer=script('verify-release-compliance')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'example.tar.gz';data.write_bytes(b'original')
            (root/'example-1.json').write_text(json.dumps({'file':data.name,'sha256':'0'*64,'url':'https://example.test/source'}))
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):builder.source_archive('example','1',root,False)
            (root/'RELEASE_REVIEW.json').write_text('{"technicalChecks":"passed"}')
            review=root/'review.json';review.write_text('{"reviewer":"","decisions":[]}')
            with self.assertRaises(ValueError):reviewer.verify(root,review)


if __name__=='__main__':unittest.main()
