import base64
import io
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient

from app import integration_libraries as libraries, main
from app.models import Project


def starter(project_id):
    activities = [
        {'id': 'start', 'name': 'Start', 'type': 'start'},
        {'id': 'audit', 'name': 'Audit', 'type': 'call_task', 'config': {
            'operation': 'call', 'taskId': libraries.asset_id('ops', 'write-log'),
            'inputMappings': {'payload.message': 'library regression'},
        }},
        {'id': 'query', 'name': 'Query', 'type': 'jdbc', 'config': {
            'operation': 'query', 'resourceId': libraries.asset_id('connections', 'database'),
            'sql': 'SELECT name FROM environment',
        }},
        {'id': 'end', 'name': 'End', 'type': 'end'},
    ]
    return Project.model_validate({'id': project_id, 'name': project_id, 'tasks': [
        {'id': 'main', 'name': 'Main', 'kind': 'starter', 'activities': activities,
         'transitions': [{'id': f'edge-{index}', 'source': left['id'], 'target': right['id']}
                         for index, (left, right) in enumerate(zip(activities, activities[1:]))]},
    ]})


class IntegrationLibraryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.addCleanup(patch.stopall)
        patch('app.store.PROJECTS_DIR', self.root / 'projects').start()
        patch('app.integration_libraries.catalog_location', return_value=self.root / 'catalog').start()
        patch('app.main._write_runtime_logs').start()
        patch('app.main._persist_debug_logs').start()
        patch.dict(os.environ, {libraries.ARCHIVE_KEY_ENV: '', 'MINA_LIBRARY_CONTROL_PLANE_URL': ''}).start()

    def attach(self, client, project, release, alias, **options):
        return client.post('/api/libraries/attach', json={
            'project': project, 'library_id': release.id, 'version': release.version,
            'alias': alias, 'sha256': libraries.digest(release), **options,
        })

    def test_reuse_two_projects_in_studio_run_debug_and_all_deployment_archives(self):
        operations, connections = libraries.sample_libraries()
        with TestClient(main.app) as client:
            self.assertEqual({entry['id'] for entry in client.get('/api/libraries').json()}, {operations.id, connections.id})
            for name in ('library-app-a', 'library-app-b'):
                with self.subTest(project=name):
                    path = self.root / f'{name}.sqlite'
                    with closing(sqlite3.connect(path)) as db:
                        db.execute('CREATE TABLE environment (name TEXT)')
                        db.execute('INSERT INTO environment VALUES (?)', (name,))
                        db.commit()
                    model = starter(name)
                    # Attach both pins before writing the references to the project.
                    draft = model.model_dump()
                    draft['tasks'][0]['activities'][1]['config'].pop('taskId')
                    draft['tasks'][0]['activities'][2]['config'].pop('resourceId')
                    for release, alias in ((operations, 'ops'), (connections, 'connections')):
                        response = self.attach(client, draft, release, alias)
                        self.assertEqual(response.status_code, 200, response.text)
                        draft = response.json()['project']
                    draft['tasks'][0]['activities'] = model.model_dump()['tasks'][0]['activities']
                    local = draft['properties']['local']
                    if name == 'library-app-b':
                        config = draft['tasks'][0]['activities'][1]['config']
                        config.pop('taskId')
                        config['dynamicTaskId'] = '${properties.routing.task}'
                        local.append({'key': 'routing.task', 'value': 'WriteLog'})
                    binding = next(row for row in local if row['key'] == 'library.connections.database-path')
                    binding['value'] = str(path)
                    response = client.post('/api/projects', json=draft)
                    self.assertEqual(response.status_code, 200, response.text)
                    saved = client.get(f'/api/projects/{name}').json()
                    self.assertEqual({pin['sha256'] for pin in saved['libraries']}, {libraries.digest(operations), libraries.digest(connections)})
                    self.assertTrue(any(task.get('library_origin', {}).get('alias') == 'ops' for task in saved['tasks'] if task.get('library_origin')))
                    public_task = next(task for task in saved['tasks'] if task['id'] == libraries.asset_id('ops', 'write-log'))
                    self.assertEqual(public_task['activities'], [])
                    self.assertTrue(public_task['library_contract']['input'])
                    self.assertTrue(all('tasks' not in pin['library'] for pin in saved['libraries']))
                    denied = client.post(f'/api/projects/{name}/debug', json={'task_id': public_task['id'], 'pause_at_entry': True})
                    self.assertEqual(denied.status_code, 400, denied.text)
                    run = client.post(f'/api/projects/{name}/run', json={'task_id': 'main'})
                    self.assertEqual(run.status_code, 200, run.text)
                    self.assertEqual(run.json()['status'], 'completed', run.text)
                    self.assertIn(name, str(run.json()['output']))
                    self.assertTrue(all(row.get('taskId') != public_task['id'] for row in run.json()['logs']))
                    with patch('app.main.get_project', side_effect=AssertionError('polling deserialized the project')):
                        monitor = client.get(f'/api/projects/{name}/runtime-state')
                    self.assertEqual(monitor.status_code, 200, monitor.text)
                    self.assertNotIn('activities', monitor.json()['taskOutputs'][public_task['id']])
                    debug = client.post(f'/api/projects/{name}/debug', json={'task_id': 'main', 'pause_at_entry': True}).json()
                    url = f"/api/debug/{debug['sessionId']}/action"
                    client.post(url, json={'action': 'step_over'})
                    stepped = client.post(url, json={'action': 'step_in'}).json()
                    self.assertEqual(stepped['currentTaskId'], 'main')
                    self.assertEqual(stepped['currentActivityId'], 'query')
                    self.assertEqual(stepped['activityOutputs']['audit']['calledTaskId'], public_task['id'])
                    done = client.post(f"/api/debug/{debug['sessionId']}/action", json={'action': 'continue'})
                    self.assertEqual(done.json()['status'], 'completed', done.text)
                    self.assertIn(name, str(done.json()['output']))
                    self.assertTrue(all(row.get('taskId') != public_task['id'] for row in done.json()['logs']))
                    trace = client.get(f"/api/debug/{debug['sessionId']}/trace", params={'download': True})
                    self.assertNotIn(public_task['id'], trace.text)
                    for archive in ('mpkg', 'python-direct', 'python-engine'):
                        response = client.get(f'/api/projects/{name}/package', params={
                            'archive': archive, 'starters': 'main', 'environment': 'local',
                        })
                        self.assertEqual(response.status_code, 200, response.text)
                        self.check_runtime_package(response.content, archive, name)

    def check_runtime_package(self, data, kind, expected):
        with ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual({item['id'] for item in manifest['libraries']}, {'operations', 'enterprise-connections'})
            folder = self.root / expected / kind
            archive.extractall(folder)
            if kind == 'mpkg':
                script = """
import asyncio, json
from pathlib import Path
from run_deployment import load_project
from app.runtime import WorkflowRuntime
project = load_project(Path('application'))
assert not project.libraries
resources = {item.id: item for item in project.resources}
props = {item.key: item.value for item in project.properties['local']}
result = asyncio.run(WorkflowRuntime().run(project.tasks[0], {}, resources, props, project=project))
assert result.status == 'completed', result.logs
print(json.dumps(result.output))
"""
            else:
                script = """
import asyncio, json
from application.main import run_task
print(json.dumps(asyncio.run(run_task('main', {}, 'local'))))
"""
            result = subprocess.run([sys.executable, '-c', script], cwd=folder, env=os.environ,
                                    capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout)

    def test_author_can_publish_export_and_install_immutable_library(self):
        sample = libraries.sample_libraries()[0]
        authored = Project(id='author', name='Author', tasks=sample.tasks)
        request = {'project': authored.model_dump(), 'id': 'team-operations', 'name': 'Team Operations',
                   'version': '1.0.0', 'exports': {'tasks': ['write-log']}}
        with TestClient(main.app) as client:
            created = client.post('/api/libraries/publish', json=request)
            self.assertEqual(created.status_code, 200, created.text)
            exported = client.get('/api/libraries/team-operations/1.0.0/archive')
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertIn('.mlib', exported.headers['content-disposition'])
            with patch('app.integration_libraries.catalog_location', return_value=self.root / 'other-catalog'):
                installed = client.post('/api/libraries/install', files={'file': ('team.mlib', exported.content, 'application/zip')})
                self.assertEqual(installed.status_code, 200, installed.text)
                self.assertEqual(installed.json()['sha256'], created.json()['sha256'])
            rejected = client.post('/api/libraries/publish', json={**request, 'description': 'different bytes'})
            self.assertEqual(rejected.status_code, 400, rejected.text)

    def test_upgrade_preview_and_pin_isolation(self):
        release = libraries.sample_libraries()[0]
        revised = release.model_copy(deep=True)
        revised.version = '2.0.0'
        revised.tasks[0].output_schema = {'type': 'string'}
        libraries.save_release(revised)
        with TestClient(main.app) as client:
            first = self.attach(client, Project(id='one', name='One').model_dump(), release, 'ops').json()['project']
            second = self.attach(client, Project(id='two', name='Two').model_dump(), release, 'ops').json()['project']
            preview = self.attach(client, first, revised, 'ops', preview=True).json()
            self.assertIn('changed', preview['breakingChanges'][0])
            self.assertEqual(self.attach(client, first, revised, 'ops').status_code, 409)
            upgraded = self.attach(client, first, revised, 'ops', allow_breaking=True).json()['project']
            self.assertEqual(upgraded['libraries'][0]['library']['version'], '2.0.0')
            self.assertEqual(second['libraries'][0]['library']['version'], '1.0.0')
            self.assertEqual({item['id'] for item in first['tasks']}, {item['id'] for item in upgraded['tasks']})
            restored = self.attach(client, upgraded, release, 'ops', allow_breaking=True).json()['project']
            self.assertEqual(restored['libraries'][0]['sha256'], libraries.digest(release))

    def test_publish_includes_referenced_schemas_and_omits_unrelated_assets(self):
        prefix = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        project = Project.model_validate({'id': 'schemas', 'name': 'Schemas', 'schemas': [
            {'id': 'root', 'name': 'Root.xsd', 'source_path': 'contracts/Root.xsd',
             'content': prefix + '<xs:include schemaLocation="../types/Base.xsd"/></xs:schema>'},
            {'id': 'base', 'name': 'Base.xsd', 'source_path': 'types/Base.xsd', 'content': prefix + '</xs:schema>'},
            {'id': 'unrelated', 'name': 'Unrelated.xsd', 'content': prefix + '</xs:schema>'},
        ]})
        release = libraries.publish(project, 'contracts', 'Contracts', '1.0.0', '', {'schemas': ['root']})
        self.assertEqual({asset.id for asset in release.schemas}, {'root', 'base'})
        self.assertEqual(release.exports['schemas'], ['root'])
        revised = release.model_copy(deep=True)
        next(asset for asset in revised.schemas if asset.id == 'base').content = (
            prefix + '<xs:element name="Field" type="xs:string"/></xs:schema>')
        self.assertTrue(any('Root.xsd' in change for change in libraries.broken_exports(release, revised)))

    def test_workspace_pin_can_export_without_the_original_catalog(self):
        release = libraries.sample_libraries()[0].model_copy(update={'id': 'portable'})
        libraries.save_release(release)
        item = Project(id='portable-app', name='Portable')
        with TestClient(main.app) as client:
            installed = self.attach(client, item.model_dump(), release, 'portable')
            self.assertEqual(installed.status_code, 200, installed.text)
            saved = client.post('/api/projects', json=installed.json()['project'])
            self.assertEqual(saved.status_code, 200, saved.text)
            workspace = client.get('/api/projects/portable-app/export')
            self.assertEqual(workspace.status_code, 200, workspace.text)
            legacy = main.get_project('portable-app').model_dump_json().encode()
            with ZipFile(io.BytesIO(workspace.content)) as archive:
                descriptor = json.loads(archive.read('project.json'))
                self.assertNotIn('tasks', descriptor['libraries'][0]['library'])
                self.assertTrue(all('mina-library-' not in name for name in archive.namelist()))
            with patch('app.integration_libraries.catalog_location', return_value=self.root / 'clean-catalog'):
                self.assertEqual(client.get('/api/libraries/portable/1.0.0/archive').status_code, 404)
                with patch('app.store.PROJECTS_DIR', self.root / 'clean-projects'):
                    missing = client.post('/api/projects/import', files={'file': ('portable.mpackage', workspace.content)})
                    self.assertEqual(missing.status_code, 400)
                    self.assertIn('pinned checksum', missing.text)
                    inherited = client.post('/api/projects/import', files={'file': ('legacy.json', legacy)})
                    self.assertEqual(inherited.status_code, 200, inherited.text)
                    self.assertNotIn('tasks', inherited.json()['libraries'][0]['library'])
                    libraries.save_release(release)
                    recovered = client.post('/api/projects/import', files={'file': ('portable.mpackage', workspace.content)})
                    self.assertEqual(recovered.status_code, 200, recovered.text)
                    # Restore the empty catalog to exercise pin export from the backend's saved project.
                    with patch('app.integration_libraries.catalog_location', return_value=self.root / 'empty-catalog'):
                        self.assertEqual(client.get('/api/libraries/portable/1.0.0/archive').status_code, 404)
                        pin = {**recovered.json()['libraries'][0], 'project_id': 'portable-app'}
                        archive = client.post('/api/libraries/pin/archive', json=pin)
                        self.assertEqual(archive.status_code, 200, archive.text)
                        self.assertEqual(libraries.digest(libraries.read_archive(archive.content)), pin['sha256'])
                        self.assertEqual(client.post('/api/libraries/pin/archive', json={**pin, 'sha256': '0' * 64}).status_code, 400)
                restored = client.post('/api/projects/import', files={'file': ('portable.mpackage', workspace.content)})
                self.assertEqual(restored.status_code, 200, restored.text)

    def test_managed_archive_seals_code_and_rejects_missing_or_wrong_key(self):
        from administrator.app.library_catalog import describe
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        release = libraries.sample_libraries()[0]
        legacy = libraries.archive_bytes(release)
        with patch.dict(os.environ, {libraries.ARCHIVE_KEY_ENV: key}), TestClient(main.app) as client:
            archive = client.get('/api/libraries/operations/1.0.0/archive')
            self.assertEqual(archive.status_code, 200, archive.text)
            with ZipFile(io.BytesIO(archive.content)) as sealed:
                self.assertEqual(set(sealed.namelist()), {'manifest.json', 'library.aes'})
                metadata = json.loads(sealed.read('manifest.json'))
                metadata['name'] = 'Changed metadata'
                with ZipFile(tampered := io.BytesIO(), 'w') as modified:
                    modified.writestr('manifest.json', json.dumps(metadata))
                    modified.writestr('library.aes', sealed.read('library.aes'))
            with self.assertRaisesRegex(ValueError, 'authenticate'):
                libraries.read_archive(tampered.getvalue())
            self.assertTrue(describe(archive.content)['protected'])
            self.assertEqual(libraries.digest(libraries.read_archive(archive.content)), libraries.digest(release))
            self.assertEqual(libraries.digest(libraries.read_archive(legacy)), libraries.digest(release))
            item = self.attach(client, Project(id='managed-app', name='Managed').model_dump(), release, 'ops').json()['project']
            self.assertEqual(client.post('/api/projects', json=item).status_code, 200)
            self.assertEqual(client.get('/api/projects/managed-app/package').status_code, 403)
            rejected = client.post('/api/projects/managed-app/package/deploy',
                                   json={'controlPlaneUrl': 'https://other.example', 'deploymentEnvironment': 'local'})
            self.assertEqual(rejected.status_code, 403)
            original_client = httpx.AsyncClient
            received = []
            def control_plane(request):
                received.append((request.url.host, request.url.path))
                return httpx.Response(200, json={'packageId': 'library-package'} if request.url.path == '/api/packages' else {'id': 'deployment'})
            with patch.dict(os.environ, {'MINA_LIBRARY_CONTROL_PLANE_URL': 'https://approved.example'}), \
                 patch.object(main, 'build_deployment_archive', return_value=(b'test-package', 'app.mpkg', 'application/zip', {})), \
                 patch.object(main.httpx, 'AsyncClient', side_effect=lambda **options: original_client(transport=httpx.MockTransport(control_plane), **options)):
                request = {'controlPlaneUrl': 'https://approved.example', 'deploymentEnvironment': 'local', 'start': False}
                self.assertEqual(client.post('/api/projects/managed-app/package/deploy', json={**request, 'verifyTls': False}).status_code, 403)
                approved = client.post('/api/projects/managed-app/package/deploy', json=request)
                self.assertEqual(approved.status_code, 200, approved.text)
                self.assertEqual(received, [('approved.example', '/api/packages'), ('approved.example', '/api/deployments')])
            with patch.dict(os.environ, {libraries.ARCHIVE_KEY_ENV: base64.urlsafe_b64encode(os.urandom(32)).decode()}):
                with self.assertRaisesRegex(ValueError, 'authenticate'):
                    libraries.read_archive(archive.content)
        with self.assertRaisesRegex(ValueError, 'requires MINA_LIBRARY_ARCHIVE_KEY'):
            libraries.read_archive(archive.content)

    def test_public_interface_projects_fields_from_private_xsd_dependencies(self):
        prefix = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        source = Project.model_validate({
            'id': 'author', 'name': 'Author',
            'tasks': [{'id': 'work', 'name': 'Work', 'kind': 'subtask', 'activities': [
                {'id': 'start', 'name': 'Start', 'type': 'start', 'config': {'interfaceSchemaId': 'entry'}},
            ]}],
            'schemas': [
                {'id': 'entry', 'name': 'Entry.xsd', 'source_path': 'contract/Entry.xsd',
                 'content': prefix + '<xs:include schemaLocation="../types/Fields.xsd"/><xs:element name="Record" type="Fields"/></xs:schema>'},
                {'id': 'fields', 'name': 'Fields.xsd', 'source_path': 'types/Fields.xsd',
                 'content': prefix + '<xs:complexType name="Fields"><xs:sequence><xs:element name="orderId" type="xs:string"/></xs:sequence></xs:complexType></xs:schema>'},
            ],
        })
        release = libraries.publish(source, 'contracts', 'Contracts', '1.0.0', '', {'tasks': ['work']})
        libraries.save_release(release)
        with TestClient(main.app) as client:
            installed = self.attach(client, Project(id='consumer', name='Consumer').model_dump(), release, 'contracts')
        self.assertEqual(installed.status_code, 200, installed.text)
        view = installed.json()['project']
        self.assertEqual(view['schemas'], [])
        task = next(item for item in view['tasks'] if item.get('library_origin'))
        self.assertEqual(task['activities'], [])
        self.assertEqual(task['library_contract']['input']['properties']['Record']['properties']['orderId']['type'], 'string')

    def test_publisher_includes_data_format_and_transitive_schema_dependencies(self):
        xsd = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
        item = Project.model_validate({'id': 'format', 'name': 'Format', 'schemas': [
            {'id': 'format', 'name': 'Record.json', 'content': '{"dataFormat":{"schemaId":"contract"}}'},
            {'id': 'contract', 'name': 'contract.json', 'source_path': 'types/contract.json',
             'content': '{"$ref":"extra.json#/$defs/Record"}'},
            {'id': 'extra', 'name': 'extra.json', 'source_path': 'types/extra.json',
             'content': '{"$defs":{"Record":{"type":"object"}}}'},
            {'id': 'unused', 'name': 'Unused.xsd', 'content': xsd},
        ], 'tasks': [{'id': 'parse', 'name': 'Parse', 'kind': 'subtask', 'activities': [
            {'id': 'data', 'name': 'Data', 'type': 'flat', 'config': {'dataFormatId': 'format'}},
        ]}]})
        release = libraries.publish(item, 'formats', 'Formats', '1.0.0', '', {'tasks': ['parse']})
        self.assertEqual({asset.id for asset in release.schemas}, {'format', 'contract', 'extra'})
        pin = {'alias': 'shared', 'sha256': libraries.digest(release), 'library': release.model_dump()}
        consumer = Project(id='consumer', name='Consumer', libraries=[pin])
        task = next(task for task in consumer.tasks if task.library_origin)
        self.assertEqual(task.activities[0].config['dataFormatId'], libraries.asset_id('shared', 'format'))
        format_asset = next(asset for asset in consumer.schemas if asset.id == libraries.asset_id('shared', 'format'))
        self.assertEqual(json.loads(format_asset.content)['dataFormat']['schemaId'], libraries.asset_id('shared', 'contract'))
        self.assertTrue(all(not asset.library_origin['public'] for asset in consumer.schemas))

    def test_removed_export_blocks_upgrade_and_removal_of_named_references(self):
        release = libraries.sample_libraries()[0]
        revised = release.model_copy(update={'version': '2.0.0', 'exports': {'tasks': ['handle-exception']}})
        libraries.save_release(revised)
        with TestClient(main.app) as client:
            project = self.attach(client, Project(id='consumer', name='Consumer').model_dump(), release, 'ops').json()['project']
            task = next(item for item in project['tasks'] if item['id'] == libraries.asset_id('ops', 'write-log'))
            reference = f'{task["package_path"]}/{task["name"]}'
            project['tasks'][0]['activities'].append({'id': 'call', 'name': 'Call', 'type': 'call_task', 'config': {'taskId': reference}})
            preview = self.attach(client, project, revised, 'ops', preview=True).json()
            self.assertIn(task['id'], preview['blockedBy'])
            self.assertEqual(self.attach(client, project, revised, 'ops', allow_breaking=True).status_code, 400)
            removal = client.post('/api/libraries/remove', json={'project': project, 'alias': 'ops'})
            self.assertEqual(removal.status_code, 400, removal.text)
            call = project['tasks'][0]['activities'][-1]['config']
            call.clear()
            call['dynamicTaskId'] = '${properties.selectedTask}'
            project['properties']['local'].append({'key': 'selectedTask', 'value': reference})
            self.assertIn(task['id'], self.attach(client, project, revised, 'ops', preview=True).json()['blockedBy'])
            self.assertEqual(client.post('/api/libraries/remove', json={'project': project, 'alias': 'ops'}).status_code, 400)

    def test_boundary_schema_changes_are_reported_on_upgrade(self):
        release = libraries.sample_libraries()[0]
        revised = release.model_copy(deep=True)
        end = next(activity for activity in revised.tasks[0].activities if activity.type == 'end')
        end.config['interfaceSchemaText'] = '{"type":"string"}'
        self.assertTrue(any('WriteLog' in change for change in libraries.broken_exports(release, revised)))

    def test_archive_checks_exact_bytes_in_studio_and_control_plane(self):
        from administrator.app.library_catalog import describe
        release = libraries.sample_libraries()[0]
        archive = libraries.archive_bytes(release)
        with ZipFile(io.BytesIO(archive)) as source:
            with ZipFile(buffer := io.BytesIO(), 'w') as changed:
                changed.writestr('library.json', source.read('library.json') + b' ')
                changed.writestr('manifest.json', source.read('manifest.json'))
        for reader in (describe, libraries.read_archive):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                reader(buffer.getvalue())
        self.assertEqual(describe(archive)['sha256'], libraries.digest(libraries.read_archive(archive)))

    def test_publication_rejects_inline_connection_secrets(self):
        for config in ({'serviceAccountJson': {'private_key': 'inline'}},
                       {'openApiApiKeySecrets': {'client-key': 'inline'}},
                       {'DynamicHTTPHeaders': {'Headers': [{'headerName': 'Authorization', 'headerValue': 'inline'}]}}):
            with self.subTest(config=list(config)):
                item = Project(id='author', name='Author', resources=[
                    {'id': 'connection', 'name': 'Connection', 'type': 'pubsub', 'config': config}])
                with self.assertRaisesRegex(ValueError, 'through .*properties|through a project property'):
                    libraries.publish(item, 'shared', 'Shared', '1.0.0', '', {'resources': ['connection']})
        item = Project(id='author', name='Author', resources=[{'id': 'connection', 'name': 'Connection', 'type': 'pubsub',
                       'config': {'serviceAccountJson': '${properties.auth}'}}],
                       properties={'local': [{'key': 'auth', 'value': 'local-value', 'data_type': 'string'}]})
        release = libraries.publish(item, 'shared', 'Shared', '1.0.0', '', {'resources': ['connection']})
        self.assertEqual(release.settings[0].data_type, 'password')
        self.assertNotIn('local-value', release.model_dump_json())

    def test_control_plane_publishes_lists_and_downloads_the_exact_release(self):
        from administrator.app import main as admin

        release = libraries.sample_libraries()[0]
        teams = self.root / 'teams.json'
        teams.write_text(json.dumps([{'id': admin.TECHNOLOGY_TEAM_ID, 'status': 'ACTIVE'}]), encoding='utf-8')
        options = {
            'controlPlaneUrl': 'http://control.example', 'credential': 'library-test-key',
            'library_id': release.id, 'version': release.version, 'sha256': libraries.digest(release),
        }
        real_client = httpx.AsyncClient
        transport = httpx.ASGITransport(app=admin.app)
        def admin_client(**kwargs):
            return real_client(transport=transport, **kwargs)
        with patch.object(admin, 'DATA_DIR', self.root / 'admin'), patch.object(admin, 'TEAMS_FILE', teams), \
             patch.object(admin, 'API_KEY', options['credential']), patch.object(admin, 'AUDIT_FILE', self.root / 'audit.json'), \
             patch.object(main.httpx, 'AsyncClient', side_effect=admin_client), TestClient(main.app) as client:
            publish = client.post('/api/libraries/control-plane/publish', json=options)
            self.assertEqual(publish.status_code, 200, publish.text)
            inventory = client.post('/api/libraries/control-plane/list', json=options)
            self.assertEqual(inventory.json()[0]['sha256'], options['sha256'])
            install = client.post('/api/libraries/control-plane/install', json=options)
            self.assertEqual(install.status_code, 200, install.text)
            self.assertEqual(install.json()['sha256'], options['sha256'])
            archive = next((self.root / 'admin').rglob('library.mlib'))
            archive.unlink()
            self.assertEqual(client.post('/api/libraries/control-plane/install', json=options).status_code, 404)
            self.assertEqual(client.post('/api/libraries/control-plane/publish', json=options).status_code, 200)
            self.assertEqual(client.post('/api/libraries/control-plane/install', json=options).status_code, 200)
            with patch.dict(os.environ, {libraries.ARCHIVE_KEY_ENV: base64.urlsafe_b64encode(os.urandom(32)).decode()}):
                replacement = client.post('/api/libraries/control-plane/publish', json=options)
                self.assertTrue(replacement.json()['protected'], replacement.text)
                self.assertEqual(client.post('/api/libraries/control-plane/install', json=options).status_code, 200)
            self.assertEqual(client.post('/api/libraries/control-plane/publish', json=options).status_code, 409)
            forbidden = client.post('/api/libraries/control-plane/list', json={**options, 'credential': 'invalid'})
            self.assertEqual(forbidden.status_code, 401, forbidden.text)
