import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jira_story import issue_address, router
from app.models import Project
from app.runtime import WorkflowRuntime


class JiraStories(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_reads_one_issue_and_flattens_rich_description(self):
        async_client = httpx.AsyncClient

        def reply(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.host, 'example.atlassian.net')
            self.assertEqual(request.url.path, '/rest/api/3/issue/INT-42')
            self.assertEqual(request.url.params['fields'], 'summary,description')
            self.assertEqual(request.headers['Authorization'], 'Basic cWE6dGVzdC10b2tlbg==')
            return httpx.Response(200, json={'fields': {
                'summary': 'Import orders',
                'description': {'type': 'doc', 'content': [
                    {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Parse JSON.'}]},
                    {'type': 'bulletList', 'content': [{'type': 'listItem', 'content': [
                        {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Publish to Kafka.'}]},
                    ]}]},
                ]},
            }})

        with patch('app.jira_story.httpx.AsyncClient', side_effect=lambda **options: async_client(
            transport=httpx.MockTransport(reply), **options,
        )):
            response = self.client.post('/api/ai/jira/read', json={
                'url': 'https://example.atlassian.net/browse/INT-42?from=notification',
                'email': 'qa', 'token': 'test-token',
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            'key': 'INT-42', 'title': 'Import orders', 'story': 'INT-42 Import orders\n\nParse JSON.\n- Publish to Kafka.',
        })

    def test_rejects_credential_forwarding_and_redirects(self):
        for url in (
            'https://example.atlassian.net.evil.example/browse/INT-1',
            'https://example.atlassian.net@localhost/browse/INT-1',
            'https://example.atlassian.net:8443/browse/INT-1',
            'https://example.atlassian.net/browse/INT-1%2F..',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                issue_address(url)
        async_client = httpx.AsyncClient
        requests = []

        def redirect(request):
            requests.append(request.url)
            return httpx.Response(302, headers={'Location': 'https://another.example/'})

        with patch('app.jira_story.httpx.AsyncClient', side_effect=lambda **options: async_client(
            transport=httpx.MockTransport(redirect), **options,
        )):
            response = self.client.post('/api/ai/jira/read', json={
                'url': 'https://example.atlassian.net/browse/INT-1',
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(requests), 1)

    def test_reads_requested_acceptance_field_and_limited_issue_context(self):
        async_client = httpx.AsyncClient

        def reply(request):
            fields = request.url.params['fields'].split(',')
            self.assertEqual(fields, ['summary', 'description', 'customfield_10042', 'parent', 'subtasks', 'status', 'issuetype'])
            return httpx.Response(200, json={'key': 'NEW-42', 'fields': {
                'summary': 'Import orders', 'description': 'Publish order events.',
                'customfield_10042': {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Each order produces one event.'}]},
                'status': {'name': 'Open'}, 'issuetype': {'name': 'Story'},
                'parent': {'key': 'NEW-1', 'fields': {'summary': 'Upgrade order routing'}},
                'subtasks': [{'key': f'NEW-{number}', 'fields': {'summary': f'Work item {number}'}} for number in range(50, 75)],
            }})

        with patch('app.jira_story.httpx.AsyncClient', side_effect=lambda **options: async_client(
            transport=httpx.MockTransport(reply), **options,
        )):
            response = self.client.post('/api/ai/jira/read', json={
                'url': 'https://example.atlassian.net/browse/INT-42',
                'acceptance_field': 'customfield_10042', 'include_related': True,
            })
            invalid = self.client.post('/api/ai/jira/read', json={
                'url': 'https://example.atlassian.net/browse/INT-42', 'acceptance_field': 'customfield_10,attachment',
            })
        self.assertEqual(response.status_code, 200, response.text)
        story = response.json()['story']
        self.assertEqual(response.json()['key'], 'NEW-42')
        self.assertIn('Acceptance criteria\nEach order produces one event.', story)
        self.assertIn('Story\nStatus Open\nParent NEW-1', story)
        self.assertIn('Subtask NEW-69', story)
        self.assertNotIn('Subtask NEW-70', story)
        self.assertEqual(invalid.status_code, 422)

    def test_project_review_and_extension_with_local_blueprint(self):
        flow = {
            'name': 'Existing', 'source': 'Parse', 'target': 'End',
            'activities': [
                {'id': 'Start', 'name': 'Start', 'type': 'start'},
                {'id': 'Parse', 'name': 'Parse', 'type': 'json', 'operation': 'parse'},
                {'id': 'End', 'name': 'End', 'type': 'end'},
            ],
            'transitions': [['Start', 'Parse', 'success'], ['Parse', 'End', 'success']],
        }
        request = {'name': 'Order import', 'story': 'Parse JSON and then publish to Kafka.', 'issue_key': 'INT-42'}
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            new_project = self.client.post('/api/ai/jira/design', json={**request, 'scope': 'project'})
            review = self.client.post('/api/ai/jira/design', json={**request, 'scope': 'analyze', 'flow': flow})
            extend = self.client.post('/api/ai/jira/design', json={
                'name': 'Kafka publishing', 'story': 'Publish to Kafka after the selected parse step.',
                'scope': 'task', 'flow': flow,
            })
            empty = self.client.post('/api/ai/jira/design', json={
                'name': 'No actions', 'story': 'An unspecified acceptance criterion.', 'scope': 'project',
            })

        for response in (new_project, review, extend, empty):
            self.assertEqual(response.status_code, 200, response.text)
        draft = new_project.json()['project']
        self.assertEqual(draft['name'], 'Order-import')
        self.assertIn('INT-42', draft['description'])
        self.assertEqual([item['type'] for item in draft['tasks'][0]['activities']], ['start', 'json', 'kafka', 'end'])
        self.assertEqual(draft['resources'][0]['type'], 'kafka')
        self.assertIsNone(review.json()['project'])
        self.assertIn('found: Parse JSON', review.json()['summary'])
        self.assertIn('missing: Kafka Publish Message', review.json()['summary'])
        self.assertEqual([item['type'] for item in extend.json()['project']['tasks'][0]['activities']], ['kafka'])
        self.assertEqual(empty.json()['project']['tasks'], [])

    def test_generated_project_runs_with_mina_runtime(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            response = self.client.post('/api/ai/jira/design', json={
                'name': 'Synthetic flow', 'scope': 'project', 'story': 'Log a status message for the incoming record.',
            })
        self.assertEqual(response.status_code, 200, response.text)
        draft = Project.model_validate(response.json()['project'])
        result = asyncio.run(WorkflowRuntime().run(draft.tasks[0], {'id': 'synthetic'}))
        self.assertEqual(result.status, 'completed')
        self.assertTrue(any('Jira story activity executed' in entry['message'] for entry in result.logs))

    def test_model_receives_story_and_flow_as_data_for_read_only_review(self):
        async_client = httpx.AsyncClient
        story = 'Compare this requirement with the running design.'

        def reply(request):
            payload = json.loads(request.content)
            self.assertIn('analysis only', payload['instructions'])
            self.assertNotIn(story, payload['instructions'])
            model_input = json.loads(payload['input'])
            self.assertEqual(model_input['story'], story)
            self.assertEqual(model_input['flow']['name'], 'Existing')
            return httpx.Response(200, json={'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps({'summary': 'Check the output contract.', 'project': {'tasks': [], 'resources': []}})},
            ]}]})

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-model-key'}), patch(
            'app.ai_builder.httpx.AsyncClient', side_effect=lambda **options: async_client(
                transport=httpx.MockTransport(reply), **options,
            ),
        ):
            response = self.client.post('/api/ai/jira/design', json={
                'name': '', 'scope': 'analyze', 'story': story,
                'flow': {'name': 'Existing', 'activities': []},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'provider': 'openai', 'summary': 'Check the output contract.', 'project': None})
