import unittest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.run_sidecar import DesktopAccess


class DesktopAccessTests(unittest.TestCase):
    def test_api_requires_its_own_single_token_and_never_forwards_it(self):
        async def echo(request):
            return JSONResponse(dict(request.headers))

        app = Starlette(routes=[Route('/api/echo', echo), Route('/', echo)])
        with TestClient(DesktopAccess(app, 'synthetic-token')) as client:
            self.assertEqual(client.get('/api/echo').status_code, 403)
            self.assertEqual(client.get('/api/echo', headers={'X-MINA-Desktop-Token': 'another-user'}).status_code, 403)
            duplicate = [('X-MINA-Desktop-Token', 'synthetic-token')] * 2
            self.assertEqual(client.get('/api/echo', headers=duplicate).status_code, 403)
            authorized = client.get('/api/echo', headers={'X-MINA-Desktop-Token': 'synthetic-token', 'X-Test': 'kept'})
            self.assertEqual(authorized.status_code, 200)
            self.assertNotIn('x-mina-desktop-token', authorized.json())
            self.assertEqual(authorized.json()['x-test'], 'kept')
            self.assertEqual(client.get('/').status_code, 200)
