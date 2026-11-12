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
