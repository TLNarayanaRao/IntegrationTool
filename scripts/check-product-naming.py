"""Prevent competing product branding from re-entering maintained MINA content."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r'tibco|mulesoft|muelsoft|dell[ -]?boomi|\bboomi\b', re.I)
FACTORY = 'com.tibco.tibjms.TibjmsConnectionFactory'
JNDI = 'com.tibco.tibjms.naming.TibjmsInitialContextFactory'
# Exact provider contracts, not arbitrary line/file exclusions.
ALLOWED = {
    'frontend/src/main.tsx': [FACTORY, JNDI],
    'backend/app/models.py': [FACTORY, JNDI],
    'backend/app/java_bridge.py': [FACTORY],
    'java-bridge/src/com/integrationfabric/bridge/FabricJavaBridge.java': [FACTORY],
    'backend/app/sap.py': ['http://www.tibco.com/xmlns/sapscalar/2015/05'],
}
AREAS = ['frontend/src', 'frontend/public', 'frontend/scripts', 'frontend/electron',
         'backend/app', 'backend/tests', 'administrator/app', 'administrator/tests',
         'java-bridge/src', 'docs', 'scripts', 'drivers']
TEXT = {'.py', '.java', '.ts', '.tsx', '.js', '.mjs', '.json', '.md', '.html',
        '.css', '.svg', '.sh', '.ps1', '.ini', '.txt', '.yaml', '.yml'}


def violations(path):
    content = path.read_text(encoding='utf-8-sig')
    for identifier in ALLOWED.get(path.relative_to(ROOT).as_posix(), []):
        content = content.replace(identifier, '')
    return [f'{path.relative_to(ROOT)}:{n}' for n, line in enumerate(content.splitlines(), 1)
            if FORBIDDEN.search(line)]


def main():
    errors = []
    paths = {p for area in AREAS for p in (ROOT / area).rglob('*')
             if p.is_file() and p.suffix in TEXT and '__pycache__' not in p.parts}
    paths.update(ROOT.glob('*.md'))
    for path in sorted(paths):
        if path.resolve() == Path(__file__).resolve():
            continue
        errors.extend(violations(path))
    if errors:
        raise SystemExit('Unexpected product branding:\n' + '\n'.join(errors))
    print('MINA naming checks passed; exact provider compatibility identifiers retained.')


if __name__ == '__main__':
    main()
