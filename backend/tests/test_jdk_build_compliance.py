"""Portable JDK selection and provenance; no redistribution approval is implied."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def fixture(folder,vendor='Eclipse Adoptium',license=True):
    home=Path(folder)/'JDK With Spaces'
    (home/'legal/java.base').mkdir(parents=True);(home/'lib').mkdir()
    (home/'release').write_text(f'IMPLEMENTOR="{vendor}"\nJAVA_VERSION="17.0.16"\nJAVA_RUNTIME_VERSION="17.0.16+8"\nSOURCE="matching-source-commit"\n')
    # A minimal test fixture for the technical detector, not a distribution license.
    (home/'legal/java.base/LICENSE').write_text('GNU General Public License\nVersion 2, June 1991\n"CLASSPATH" EXCEPTION TO THE GPL\n' if license else 'Proprietary license; redistribution requires permission')
    (home/'lib/src.zip').write_bytes(b'test-source-placeholder')
    (home/'bin').mkdir()
    for name in ('java','javac','jlink'):(home/f'bin/{name}.exe').write_bytes(b'test-only')
    return home


class JdkBuildComplianceTests(unittest.TestCase):
    def test_license_paths_stay_short_and_keep_every_original_notice(self):
        builder=script('build-compliance')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);site=root/'site';output=root/'output'
            origins=['opentelemetry_exporter_http_transport-0.66b2.dist-info/licenses/LICENSE',
                     'opentelemetry/exporter/http/transport/licenses/LICENSE']
            for index,origin in enumerate(origins):
                path=site/origin;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('notice '+str(index))
            stale=output/'licenses/python/opentelemetry-exporter-http-transport/old.dist-info/licenses/LICENSE'
            stale.parent.mkdir(parents=True);stale.write_text('obsolete generated copy')
            class Distribution:
                metadata={'Name':'opentelemetry-exporter-http-transport','License':'Apache-2.0'}
                version='0.66b2';files=origins
                def locate_file(self,file):return site/file
            with patch.object(builder.metadata,'distributions',return_value=[Distribution()]):
                _,records,errors=builder.python_components(output,root/'cache',False)
            self.assertEqual(errors,[])
            self.assertFalse(stale.exists())
            notices=records[0]['notices'];self.assertEqual(len(notices),2)
            self.assertEqual({item['originalFile'] for item in notices},set(origins))
            self.assertEqual(len({item['path'] for item in notices}),2)
            for index,notice in enumerate(notices):
                path=Path(notice['path']);self.assertEqual(len(path.parts),4)
                self.assertLessEqual(len(path.name),24)
                self.assertEqual((output/path).read_text(),'notice '+str(index))

    def test_openjdk_vendors_are_recorded_without_an_openlogic_only_gate(self):
        builder=script('build-compliance')
        for vendor in ('OpenLogic','Eclipse Adoptium','Microsoft','Amazon.com Inc.','Custom OpenJDK Builder'):
            with self.subTest(vendor=vendor),tempfile.TemporaryDirectory() as folder:
                home=fixture(folder,vendor);output=Path(folder)/'out'
                component=builder.java_components(output,home)
                self.assertEqual(component['name'],vendor+' OpenJDK')
                record=json.loads((output/'java/PROVENANCE.json').read_text())
                self.assertEqual(record['implementor'],vendor)
                self.assertEqual(record['sourceAccessStatus'],'review-required')
                self.assertEqual(record['releaseMetadata']['SOURCE'],'matching-source-commit')
                self.assertTrue((output/'java/legal/java.base/LICENSE').is_file())
                self.assertTrue((output/'java/library-sources.zip').is_file())

    def test_proprietary_or_incomplete_jdk_fails_with_actionable_error(self):
        builder=script('build-compliance')
        with tempfile.TemporaryDirectory() as folder:
            home=fixture(folder,'Unreviewed Proprietary Vendor',license=False)
            with self.assertRaisesRegex(ValueError,'MINA_JAVA_HOME'):builder.java_components(Path(folder)/'out',home)
            (home/'legal/java.base/LICENSE').write_text('GNU General Public License Version 2\nClasspath exception')
            (home/'lib/src.zip').unlink()
            with self.assertRaisesRegex(ValueError,'library sources missing'):builder.java_components(Path(folder)/'out',home)

    def test_artifact_sbom_uses_actual_jdk_vendor(self):
        artifact=script('artifact-sbom')
        with tempfile.TemporaryDirectory() as folder:
            home=fixture(folder,'Microsoft');legal=Path(folder)/'payload/legal/java'
            legal.mkdir(parents=True);(legal/'release').write_bytes((home/'release').read_bytes())
            reader=types.ModuleType('PyInstaller.archive.readers');reader.CArchiveReader=None
            with patch.dict(sys.modules,{'PyInstaller':types.ModuleType('PyInstaller'),
                    'PyInstaller.archive':types.ModuleType('PyInstaller.archive'),'PyInstaller.archive.readers':reader}),\
                    patch.object(artifact.metadata,'distributions',return_value=[]):
                components=artifact.bundled_components(Path(folder)/'payload')
            self.assertEqual(components[0]['name'],'Microsoft OpenJDK')

    @unittest.skipUnless(sys.platform=='win32','Windows packaging toolchain selection')
    def test_powershell_51_passes_quoted_and_trailing_slash_jdk_paths_to_python(self):
        builder=script('build-compliance')
        with tempfile.TemporaryDirectory(prefix='jdk argument ') as folder:
            home=fixture(folder,'Microsoft')
            command=('. ./scripts/resolve-java-home.ps1; $jdkHome=Resolve-MinaJavaHome; '
                     '& $env:MINA_TEST_PYTHON -c "import json,sys;print(json.dumps(sys.argv[1:]))" --java-home $jdkHome')
            for variable in ('MINA_JAVA_HOME','JAVA_HOME'):
                for value in (str(home),str(home)+'\\','"'+str(home)+'\\"',str(home)+'/'):
                    with self.subTest(variable=variable,value=value):
                        environment={**os.environ,'MINA_JAVA_HOME':'','JAVA_HOME':'','MINA_TEST_PYTHON':sys.executable,variable:value}
                        result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],
                            cwd=ROOT,env=environment,capture_output=True,text=True,timeout=30)
                        self.assertEqual(result.returncode,0,result.stderr)
                        received=json.loads(result.stdout)
                        self.assertEqual(received,['--java-home',str(home.resolve())])
                        self.assertEqual(builder.java_components(Path(folder)/'output',received[1])['name'],'Microsoft OpenJDK')
            # Also recover a path mangled by an older caller, without bypassing
            # any license, metadata or source checks.
            self.assertEqual(builder.java_components(Path(folder)/'output',str(home)+'"')['name'],'Microsoft OpenJDK')

    @unittest.skipUnless(sys.platform=='win32','Windows packaging toolchain selection')
    def test_explicit_jdk_selection_handles_spaces_and_overrides_java_home(self):
        with tempfile.TemporaryDirectory() as folder:
            home=fixture(folder)
            command=". ./scripts/resolve-java-home.ps1; Resolve-MinaJavaHome"
            result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],cwd=ROOT,
                env={**os.environ,'MINA_JAVA_HOME':str(home),'JAVA_HOME':str(Path(folder)/'wrong')},
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(),home.resolve())
            (home/'bin/jlink.exe').unlink()
            failed=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],cwd=ROOT,
                env={**os.environ,'MINA_JAVA_HOME':str(home)},capture_output=True,text=True,timeout=30)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn('Incomplete JDK',failed.stderr)
