"""Prevent competing product branding from re-entering maintained MINA content."""
import re
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r't[i]bco|business[w]orks|mule[ -]?s[o]ft|muel[s]oft|\bb[o]omi\b', re.I)
AREAS = ['frontend/src', 'frontend/public', 'frontend/scripts', 'frontend/electron',
         'backend/app', 'backend/tests', 'administrator/app', 'administrator/tests',
         'java-bridge/src', 'docs', 'scripts', 'drivers', 'output/documentation-preview']
TEXT = {'.py', '.java', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.json', '.md', '.html',
        '.css', '.svg', '.sh', '.ps1', '.ini', '.txt', '.yaml', '.yml', '.xml', '.xsd', '.xsl', '.xslt'}


def violations(name, data):
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    content = data.decode(encoding, errors='replace')
    matches = [name] if FORBIDDEN.search(name) else []
    return matches + [f'{name}:{n}' for n, line in enumerate(content.splitlines(), 1)
            if FORBIDDEN.search(line)]


def main():
    errors = []
    paths = {p for area in AREAS for p in (ROOT / area).rglob('*')
             if p.is_file() and p.suffix in TEXT and '__pycache__' not in p.parts}
    paths.update(ROOT.glob('*.md'))
    for path in sorted(paths):
        errors.extend(violations(path.relative_to(ROOT).as_posix(), path.read_bytes()))
    bundle = ROOT / 'release/MinaLinuxSetup.zip'
    if bundle.is_file():
        with ZipFile(bundle) as archive:
            for member in archive.namelist():
                data = archive.read(member) if Path(member).suffix in TEXT else b''
                errors.extend(violations(f'{bundle.relative_to(ROOT).as_posix()}!{member}', data))
    if errors:
        raise SystemExit('Unexpected product branding:\n' + '\n'.join(errors))
    print('MINA product naming checks passed.')


if __name__ == '__main__':
    main()
