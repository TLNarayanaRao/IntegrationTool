"""Launch an extracted MINA deployment archive from the container image."""

import json
import os
import sys
from pathlib import Path


def package_entrypoint(root: Path) -> tuple[list[str], str]:
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'mina-deployment':
        raise ValueError('Expected a MINA deployment package exported from Package in Studio')
    source = manifest.get('pythonSource')
    if source and source.get('entrypoint') == 'application/main.py' and (root / 'application/main.py').is_file():
        command = ['-m', 'application.main']
    elif not source and manifest.get('runtime') == 'mina-python' and (root / 'application/project.json').is_file():
        command = [str(Path(__file__).with_name('run_deployment.py')), '--application', str(root / 'application')]
    else:
        raise ValueError('The deployment archive is missing a supported application entry point')
    environments = manifest.get('environments') or []
    return command, manifest.get('environment') or (environments[0] if environments else 'local')


def main() -> None:
    root = Path.cwd()
    try:
        command, default_environment = package_entrypoint(root)
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise SystemExit(f'MINA package validation failed: {error}') from None
    if sys.argv[1:] == ['--check-package']:
        return
    os.environ.setdefault('MINA_ENVIRONMENT', default_environment)
    os.execv(sys.executable, [sys.executable, *command, *sys.argv[1:]])


if __name__ == '__main__':
    main()
