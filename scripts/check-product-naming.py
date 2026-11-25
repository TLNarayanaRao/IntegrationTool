"""Prevent competing product branding from re-entering maintained MINA content."""
import io
import re
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r't[i]bco|business[ -]?[w]orks|mule[ -]?s[o]ft|muel[s]oft|\bb[o]omi\b|'
    r'data[ _-]?w[e]ave|\bany[p]oint\b|web[m]ethods|inform[a]tica|biz[t]alk', re.I,
)
AREAS = ['frontend/src', 'frontend/public', 'frontend/scripts', 'frontend/electron', 'frontend/dist',
         'backend/app', 'backend/tests', 'administrator/app', 'administrator/tests',
         'java-bridge/src', 'docs', 'scripts', 'drivers', 'samples', 'output/documentation-preview']
TEXT = {'.py', '.java', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.json', '.md', '.html',
        '.css', '.svg', '.sh', '.ps1', '.ini', '.txt', '.yaml', '.yml', '.xml', '.xsd', '.xsl', '.xslt', '.nsi'}
ARCHIVES = {'.zip', '.mpackage', '.mpkg', '.mlib'}


def violations(name, data):
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    content = data.decode(encoding, errors='replace')
    matches = [name] if FORBIDDEN.search(name) else []
    return matches + [f'{name}:{n}' for n, line in enumerate(content.splitlines(), 1)
            if FORBIDDEN.search(line)]


def archive_violations(source, name, depth=0):
    with ZipFile(source) as archive:
        for member in archive.infolist():
            suffix = Path(member.filename).suffix.lower()
            label = f'{name}!{member.filename}'
            data = archive.read(member) if suffix in TEXT else b''
            yield from violations(label, data)
            if suffix in ARCHIVES and depth < 2:
                yield from archive_violations(io.BytesIO(archive.read(member)), label, depth + 1)


def main():
    errors = []
    paths = {p for area in AREAS for p in (ROOT / area).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    paths.update(ROOT.glob('*.md'))
    for path in sorted(paths):
        data = path.read_bytes() if path.suffix.lower() in TEXT else b''
        errors.extend(violations(path.relative_to(ROOT).as_posix(), data))
    bundles = {ROOT / 'release/MinaLinuxSetup.zip'}
    for area in ('samples', 'frontend/public/samples', 'output/documentation-preview/samples'):
        bundles.update(p for p in (ROOT / area).rglob('*') if p.is_file() and p.suffix.lower() in ARCHIVES)
    for bundle in sorted(bundles):
        if bundle.is_file():
            errors.extend(archive_violations(bundle, bundle.relative_to(ROOT).as_posix()))
    if errors:
        raise SystemExit('Unexpected product branding:\n' + '\n'.join(errors))
    print('MINA product naming checks passed.')


if __name__ == '__main__':
    main()
