"""Exercise isolated desktop sidecars with concurrent development, Run and Debug traffic."""
import argparse
import asyncio
from collections import defaultdict
from contextlib import contextmanager
import ctypes
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.parse import urljoin

import certifi
import httpx


PROJECT = '/api/projects/shared-workflow'
HEADER = 'X-MINA-Desktop-Token'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def summary(values):
    ordered = sorted(values)
    return {'count': len(values), 'p50Ms': round(ordered[math.ceil(len(values) * .5) - 1], 2),
            'p95Ms': round(ordered[math.ceil(len(values) * .95) - 1], 2), 'maxMs': round(ordered[-1], 2)}

@contextmanager
def keep_test_host_awake():
    if os.name != 'nt':
        yield
        return
    set_state = ctypes.WinDLL('kernel32').SetThreadExecutionState
    set_state.argtypes = (ctypes.c_uint,)
    set_state.restype = ctypes.c_uint
    continuous = 0x80000000
    previous = set_state(continuous | 0x00000001)  # System idle sleep only.
    try:
        yield
    finally:
        if previous:
            set_state(previous | continuous)


def windows_memory(pids):
    if os.name != 'nt':
        return {}
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peakRss', 'rss', 'peakPagedPool', 'pagedPool',
                                               'peakNonPagedPool', 'nonPagedPool', 'pageFile',
                                               'peakPageFile', 'privateBytes')]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    read = kernel.K32GetProcessMemoryInfo
    read.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    rss = private = measured = cpu_ticks = 0
    for pid in pids:
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            continue
        try:
            counters = Counters(size=ctypes.sizeof(Counters))
            if read(handle, ctypes.byref(counters), counters.size):
                measured += 1
                rss += counters.rss
                private += counters.privateBytes
                created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
                if kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in (created, exited, system, user))):
                    cpu_ticks += sum((item.dwHighDateTime << 32) | item.dwLowDateTime for item in (system, user))
        finally:
            kernel.CloseHandle(handle)
    return {'processes': measured, 'aggregateWorkingSetMiB': round(rss / 2**20, 1),
            'aggregatePrivateMiB': round(private / 2**20, 1), 'aggregateCpuSeconds': round(cpu_ticks / 10**7, 2)}


def fixture(profile, cycle=0):
    return {'id': 'shared-workflow', 'name': f'Workspace-{profile}', 'description': f'Edit {profile}/{cycle}',
            'tasks': [{'id': 'main', 'name': 'Main', 'kind': 'starter', 'activities': [
                {'id': 'start', 'type': 'start', 'name': 'Start'},
                {'id': 'log', 'type': 'log', 'name': f'Log-{cycle}', 'config': {'message': '${input.marker}'}},
                {'id': 'end', 'type': 'end', 'name': 'End'},
            ], 'transitions': [{'id': 'to-log', 'source': 'start', 'target': 'log'},
                               {'id': 'to-end', 'source': 'log', 'target': 'end'}]}]}

def hosted_fixture(profile, mode, port):
    return {'id': f'hosted-{mode}', 'name': f'Hosted-{mode}-{profile}', 'resources': [
        {'id': 'server', 'name': 'Server', 'type': 'http', 'config': {
            'connectorMode': 'server', 'host': '127.0.0.1', 'port': port,
            'minimumQtpThreads': 1, 'maximumQtpThreads': 4,
        }}], 'tasks': [{'id': 'main', 'name': 'Hosted-Main', 'kind': 'starter', 'activities': [
            {'id': 'receive', 'type': 'http_listener', 'name': 'Receive',
             'config': {'resourceId': 'server', 'path': '/soak', 'operation': 'listen', 'methods': 'GET'}},
            {'id': 'reply', 'type': 'http_response', 'name': 'Reply',
             'config': {'contentType': 'application/json', 'body': {'profile': profile, 'mode': mode}}},
        ], 'transitions': [{'id': 'reply-next', 'source': 'receive', 'target': 'reply'}]}]}


def reserve_loopback_port():
    listener = socket.socket()
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(('127.0.0.1', 0))
    return listener

class Profile:
    def __init__(self, index, folder, command, cwd, timings, timeout, live_http, tls):
        self.index = index
        self.folder = folder / f'profile-{index:03}'
        self.folder.mkdir()
        self.command, self.cwd, self.timeout = command, cwd, timeout
        self.tls = tls
        self.timings = timings
        self.client = self.child = self.log_file = None
        self.stdout_task = None
        self.token = secrets.token_hex(32)
        self.port = None
        self.cycles = 0
        self.reservations = {mode: reserve_loopback_port() for mode in ('run', 'debug')} if live_http else {}
        self.hosted = {}
        self.hosted_client = None

    async def start(self):
        started = time.perf_counter()
        self.log_file = (self.folder / 'runtime.log').open('wb')
        environment = dict(os.environ, MINA_PORT='0', MINA_DESKTOP_TOKEN=self.token,
                           MINA_DATA_DIR=str(self.folder / 'workspace-data'), MINA_LOG_LEVEL='warning', PYTHONUTF8='1')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.child = await asyncio.create_subprocess_exec(*self.command, cwd=self.cwd, env=environment,
                                                          stdout=asyncio.subprocess.PIPE, stderr=self.log_file,
                                                          creationflags=flags)
        try:
            async with asyncio.timeout(self.timeout):
                while line := await self.child.stdout.readline():
                    self.log_file.write(line)
                    match = re.fullmatch(rb'MINA_DESKTOP_PORT=(\d+)\r?\n', line)
                    if match:
                        self.port = int(match.group(1))
                        break
                require(self.port is not None, f'Profile {self.index} runtime exited during startup')
                self.stdout_task = asyncio.create_task(self.drain_stdout())
                self.client = httpx.AsyncClient(base_url=f'http://127.0.0.1:{self.port}', trust_env=False, verify=self.tls,
                                                headers={HEADER: self.token}, timeout=20)
                while self.child.returncode is None:
                    try:
                        if (await self.client.get('/api/health')).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(.1)
                require(self.child.returncode is None, f'Profile {self.index} runtime exited before health')
        except TimeoutError as exc:
            raise RuntimeError(f'Profile {self.index} readiness exceeded {self.timeout}s') from exc
        self.timings['startup'].append((time.perf_counter() - started) * 1000)
        await self.request('create', 'POST', '/api/projects', fixture(self.index))

    async def drain_stdout(self):
        while chunk := await self.child.stdout.read(65536):
            self.log_file.write(chunk)

    async def inspect_designer(self):
        try:
            # Chromium opens its own connections after launcher readiness.
            async with httpx.AsyncClient(base_url=self.client.base_url, trust_env=False, verify=self.tls, timeout=20) as designer:
                html = (await designer.get('/')).raise_for_status().text
                assets = set(re.findall(r'(?:src|href)="(/assets/[^"<>]+)"', html))
                require(assets, f'Profile {self.index} designer has no compiled assets')
                for asset in sorted(assets):
                    result = (await designer.get(asset)).raise_for_status()
                    require(len(result.content) > 0 and 'text/html' not in result.headers.get('content-type', ''),
                            f'Profile {self.index} designer asset was not served: {asset}')
        except httpx.HTTPError as error:
            raise RuntimeError(f'Profile {self.index} designer fetch failed: {error!r}') from error

    async def prepare_hosted(self):
        for mode, listener in self.reservations.items():
            await self.request('hostedCreate', 'POST', '/api/projects', hosted_fixture(self.index, mode, listener.getsockname()[1]))

    async def start_hosted(self):
        if not self.reservations:
            return
        self.hosted_client = httpx.AsyncClient(trust_env=False, verify=self.tls, timeout=20)
        for mode, listener in self.reservations.items():
            port = listener.getsockname()[1]
            listener.close()
            started = await self.request('hostedStartup', 'POST', f'/api/projects/hosted-{mode}/{mode}', {'task_id': 'main'})
            expected = f'http://127.0.0.1:{port}/soak'
            require(started['status'] == 'listening' and started['endpoints'][0]['url'] == expected,
                    f'Profile {self.index} hosted {mode} listener did not start on the chosen port')
            self.hosted[mode] = expected
        preview = await self.request('studioPreview', 'GET', '/api/listeners/hosted-run/soak')
        require(preview == {'profile': self.index, 'mode': 'run'}, f'Profile {self.index} studio preview response mismatch')
        state = await self.request('previewState', 'GET', '/api/projects/hosted-run/runtime-state')
        require(self.token not in json.dumps(state) and 'x-mina-desktop-token' not in json.dumps(state).lower(),
                f'Profile {self.index} preview forwarded its desktop authentication header')

    async def request(self, phase, method, path, payload=None):
        started = time.perf_counter()
        try:
            response = await self.client.request(method, path, json=payload)
        except httpx.TransportError as error:
            raise RuntimeError(f'Profile {self.index} {phase} transport failed: {error!r}') from error
        if not response.is_success:
            raise RuntimeError(f'Profile {self.index} {phase}: HTTP {response.status_code} {response.text[:600]}')
        self.timings[phase].append((time.perf_counter() - started) * 1000)
        return response.json()

    async def work(self, end, pause, hold):
        while time.perf_counter() < end or not self.cycles:
            count = self.cycles + 1
            project = fixture(self.index, count)
            await self.request('save', 'PUT', PROJECT, project)
            opened = await self.request('read', 'GET', PROJECT)
            require(opened['description'] == project['description'] and opened['name'] == project['name'],
                    f'Profile {self.index} read different project data')
            payload = {'marker': f'profile-{self.index}/edit-{count}'}
            run = await self.request('run', 'POST', PROJECT + '/run', {'task_id': 'main', 'input': payload})
            require(run['status'] == 'completed' and run['output'] == payload, f'Profile {self.index} Run output mismatch')
            debug = await self.request('debugStart', 'POST', PROJECT + '/debug',
                                       {'task_id': 'main', 'input': payload, 'pause_at_entry': True})
            require(debug['status'] == 'paused', f'Profile {self.index} debug did not pause')
            endpoint = f"/api/debug/{debug['sessionId']}"
            current = await self.request('debugStep', 'POST', endpoint + '/action', {'action': 'step_over'})
            require(current['currentActivityId'] == 'log', f'Profile {self.index} debug step mismatch')
            await asyncio.sleep(hold)
            continued = await self.request('debugContinue', 'POST', endpoint + '/action', {'action': 'continue'})
            require(continued['status'] == 'completed' and continued['output'] == payload,
                    f'Profile {self.index} Debug output mismatch')
            report = await self.request('debugTrace', 'GET', endpoint + '/trace?limit=20')
            require([entry['transitionId'] for entry in report['events'] if entry['kind'] == 'transition'] ==
                    ['to-log', 'to-end'], f'Profile {self.index} trace mismatch')
            for mode, url in self.hosted.items():
                started = time.perf_counter()
                response = await self.hosted_client.get(url)
                require(response.status_code == 200 and response.json() == {'profile': self.index, 'mode': mode},
                        f'Profile {self.index} live {mode} response mismatch ({response.status_code})')
                self.timings[f'hosted{mode.title()}'].append((time.perf_counter() - started) * 1000)
            self.cycles = count
            await asyncio.sleep(pause)

    async def close(self):
        for listener in self.reservations.values():
            listener.close()
        if self.hosted_client:
            await self.hosted_client.aclose()
        if self.client:
            await self.client.aclose()
        if self.child and self.child.returncode is None:
            try:
                self.child.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.child.wait(), 10)
            except TimeoutError:
                self.child.kill()
                await self.child.wait()
        if self.stdout_task:
            self.stdout_task.cancel()
            await asyncio.gather(self.stdout_task, return_exceptions=True)
        if self.log_file:
            self.log_file.close()


async def check_isolation(profiles, tls):
    async with httpx.AsyncClient(trust_env=False, verify=tls, timeout=15) as peer:
        async with asyncio.TaskGroup() as group:
            for index, profile in enumerate(profiles):
                other = profiles[(index + 1) % len(profiles)]
                group.create_task(check_peer(peer, profile, other))


async def check_peer(peer, profile, other):
    url = urljoin(str(profile.client.base_url), PROJECT)
    for headers in ({}, {HEADER: other.token}):
        blocked = await peer.get(url, headers=headers)
        require(blocked.status_code == 403, f'Profile {profile.index} admitted a peer without its token')


async def check_hosted_collision(first, second):
    existing = httpx.URL(first.hosted['run'])
    project = hosted_fixture(second.index, 'port-conflict', existing.port)
    await second.request('hostedCreate', 'POST', '/api/projects', project)
    refused = await second.client.post('/api/projects/hosted-port-conflict/run', json={'task_id': 'main'})
    require(refused.status_code == 400 and 'listener startup failed' in refused.text,
            f'Duplicate HTTP port was not rejected: {refused.status_code}')
    response = await first.hosted_client.get(str(existing))
    require(response.status_code == 200 and response.json() == {'profile': first.index, 'mode': 'run'},
            'The existing HTTP listener changed after the rejected bind')


async def monitor(profiles, snapshots, end):
    while time.perf_counter() < end:
        memory = await asyncio.to_thread(windows_memory, [profile.child.pid for profile in profiles])
        if memory:
            snapshots.append(memory)
        await asyncio.sleep(min(15, max(0, end - time.perf_counter())))

async def measure_driver_delays(samples):
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(.1)
        samples.append(max(0, (loop.time() - start - .1) * 1000))


async def simulate(args, folder):
    backend = Path(__file__).resolve().parents[1] / 'backend'
    command = [str(args.runtime.resolve())] if args.runtime else [args.python, str(backend / 'run_sidecar.py')]
    cwd = args.runtime.resolve().parent if args.runtime else backend
    timings = defaultdict(list)
    # Context creation loads a CA bundle synchronously. Reuse the default
    # verified context without sharing connections or profile credentials.
    tls = ssl.create_default_context(cafile=certifi.where())
    profiles = [Profile(index, folder, command, cwd, timings, args.startup_timeout, args.live_http, tls)
                for index in range(1, args.users + 1)]
    driver_delays = []
    driver_probe = asyncio.create_task(measure_driver_delays(driver_delays))
    try:
        async with asyncio.TaskGroup() as group:
            for profile in profiles:
                group.create_task(profile.start())
        require(len({profile.port for profile in profiles}) == args.users, 'Two users received the same runtime port')
        await check_isolation(profiles, tls)
        async with asyncio.TaskGroup() as group:
            for profile in profiles:
                group.create_task(profile.inspect_designer())
        batch = args.provision_batch or len(profiles)
        for offset in range(0, len(profiles), batch):
            wave = profiles[offset:offset + batch]
            async with asyncio.TaskGroup() as group:
                for profile in wave:
                    group.create_task(profile.prepare_hosted())
            async with asyncio.TaskGroup() as group:
                for profile in wave:
                    group.create_task(profile.start_hosted())
        if args.live_http:
            await check_hosted_collision(profiles[0], profiles[1])
        started = time.perf_counter()
        end = started + args.seconds
        print(f'{args.users} sidecars ready with unique ports and workspace isolation', flush=True)
        snapshots = []
        async with asyncio.TaskGroup() as group:
            for profile in profiles:
                group.create_task(profile.work(end, args.pause, args.debug_hold))
            group.create_task(monitor(profiles, snapshots, end))
        snapshots.append(await asyncio.to_thread(windows_memory, [profile.child.pid for profile in profiles]))
        stats = {name: summary(values) for name, values in timings.items()}
        gates = {name: row['p95Ms'] for name, row in stats.items() if name != 'startup' and row['p95Ms'] > args.max_p95_ms}
        cycles = sum(profile.cycles for profile in profiles)
        elapsed = time.perf_counter() - started
        return {'users': args.users, 'runtime': 'packaged' if args.runtime else 'source',
                'platform': platform.platform(), 'logicalCpus': os.cpu_count(), 'elapsedSeconds': round(elapsed, 2),
                'cycles': cycles, 'minCyclesPerUser': min(profile.cycles for profile in profiles), 'distinctPorts': args.users,
                'cyclesPerSecond': round(cycles / elapsed, 2),
                'hostedListeners': args.users * 2 if args.live_http else 0,
                'listenerProvisionBatch': batch if args.live_http else 0,
                'duplicateHostedPortRejected': args.live_http,
                'foreignAndAnonymousRequestsRejected': args.users * 2, 'designerAssetsCheckedFor': args.users,
                'latency': stats, 'sidecarMemory': snapshots, 'maxP95Ms': args.max_p95_ms,
                'loadDriverEventLoopDelay': summary(driver_delays),
                'latencyGateFailures': gates, 'passed': not gates}
    except Exception:
        partial = {'passed': False, 'completedCycles': sum(profile.cycles for profile in profiles),
                   'latency': {name: summary(values) for name, values in timings.items() if values},
                   'loadDriverEventLoopDelay': summary(driver_delays) if driver_delays else None}
        args.output.with_suffix('.partial.json').write_text(json.dumps(partial, indent=2) + '\n', encoding='utf-8')
        raise
    finally:
        driver_probe.cancel()
        await asyncio.gather(driver_probe, return_exceptions=True)
        await asyncio.gather(*(profile.close() for profile in profiles))


def main():
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', type=int, default=52)
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--pause', type=float, default=.8, help='Think time after each development cycle.')
    parser.add_argument('--debug-hold', type=float, default=.1, help='Seconds to remain paused after a debugger step.')
    parser.add_argument('--startup-timeout', type=float, default=120)
    parser.add_argument('--max-p95-ms', type=float, default=2000)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--runtime', type=Path, help='Use this packaged sidecar instead of the source interpreter.')
    parser.add_argument('--live-http', action='store_true', help='Add one actual HTTP Run and Debug listener per user.')
    parser.add_argument('--provision-batch', type=int, default=0,
                        help='Stage initial listener provisioning in batches. All users still execute concurrently.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.users < 2 or min(args.seconds, args.startup_timeout, args.max_p95_ms) <= 0 or min(args.pause, args.debug_hold, args.provision_batch) < 0:
        parser.error('Use at least two users and positive limits.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with keep_test_host_awake(), tempfile.TemporaryDirectory(prefix='mina-sidecars-', dir=args.output.parent.resolve()) as directory:
        folder = Path(directory)
        try:
            results = asyncio.run(simulate(args, folder))
        except Exception:
            log = args.output.with_suffix('.runtime-errors.log')
            with log.open('w', encoding='utf-8') as report:
                for runtime_log in sorted(folder.glob('profile-*/runtime.log')):
                    with runtime_log.open('rb') as source:
                        source.seek(max(0, runtime_log.stat().st_size - 4096))
                        report.write(f'\n{runtime_log.parent.name}\n{source.read().decode("utf-8", errors="replace")}')
            print(f'Runtime error tails saved to {log}', flush=True)
            raise
    args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cycles': results['cycles'], 'passed': results['passed'], 'report': str(args.output)}))
    return 0 if results['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
