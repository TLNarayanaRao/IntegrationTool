"""Build a standard MINA EAR from a saved Studio project."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from fastapi import HTTPException
from app.integration_libraries import studio_project_input, validate_project_references
from app.main import build_deployment_archive, packaging_task_closure, protected_library_deployment
from app.project_import import MAX_IMPORT_BYTES, project_payload
from app.raw_python import validate_export_mappings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Studio project JSON or .mpackage')
    parser.add_argument('--environment', action='append', required=True, help='Packaged profile. Repeat for multiple profiles.')
    parser.add_argument('--starter', action='append', help='Starter Task ID. Defaults to all starters.')
    parser.add_argument('--version', help='Override the project packaging version for this build')
    parser.add_argument('--output-dir', type=Path, default=Path('dist/ear'))
    args = parser.parse_args()
    try:
        if args.project.suffix.lower() not in {'.json', '.mpackage'}:
            raise ValueError('Choose an exported Studio project JSON or .mpackage')
        with args.project.open('rb') as project_file:
            definition = project_payload(project_file.read(MAX_IMPORT_BYTES + 1), args.project.name)
        project = studio_project_input(json.loads(definition))
        if protected_library_deployment(project):
            raise ValueError('Protected Integration Libraries require the managed Studio deployment path')
        validate_project_references(project)
        if args.version:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.version):
                raise ValueError('Version can contain letters, numbers, dots, underscores and hyphens')
            project.packaging['version'] = args.version
        selected, _, _ = packaging_task_closure(project, args.starter, args.environment)
        validate_export_mappings(selected.model_dump())
        data, filename, _, _ = build_deployment_archive(project, 'on-prem', args.environment, args.starter, 'ear', None)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / filename
        with target.open('xb') as archive:
            archive.write(data)
    except HTTPException as error:
        raise SystemExit(f'EAR build failed: {error.detail}') from None
    except (OSError, ValueError) as error:
        message = error.errors(include_input=False, include_context=False) if hasattr(error, 'errors') else str(error)
        raise SystemExit(f'EAR build failed: {message}') from None
    print(target)


if __name__ == '__main__':
    main()
