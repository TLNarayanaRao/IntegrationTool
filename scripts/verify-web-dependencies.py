"""Fail packaging if the installed web stack differs from reviewed security pins."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def verify() -> None:
    requirements = Path(__file__).resolve().parents[1] / 'backend' / 'requirements.txt'
    pins = dict(line.split('==', 1) for line in requirements.read_text().splitlines()
                if line.startswith(('fastapi==', 'starlette==', 'python-multipart==')))
    failures = []
    for name, expected in pins.items():
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = 'missing'
        if installed != expected:
            failures.append(f'{name}: expected {expected}, installed {installed}')
    if failures:
        raise SystemExit('Web dependency verification failed: ' + '; '.join(failures))
    print('Reviewed web dependency versions verified.')


if __name__ == '__main__':
    verify()
