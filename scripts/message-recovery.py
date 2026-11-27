"""Inspect failed messages or make one key available to a recovery flow."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.message_state import MessageStateException, operate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'requeue'])
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--backend', choices=['sqlite', 'postgresql'], default='sqlite')
    parser.add_argument('--state-file')
    parser.add_argument('--key')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--include-payload', action='store_true')
    args = parser.parse_args()
    if args.command == 'requeue' and not args.key:
        parser.error('--key is required for requeue')
    try:
        result = operate('replay_messages', {
            'namespace': args.namespace, 'stateBackend': args.backend, 'stateFile': args.state_file,
            'action': 'requeue_one' if args.command == 'requeue' else 'list',
            'limit': args.limit, 'messageKey': args.key, 'metadataOnly': not args.include_payload,
        }, None)
    except MessageStateException as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
