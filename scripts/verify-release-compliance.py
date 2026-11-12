"""Require a separate, evidence-backed rights review before public release."""
import argparse,json
from pathlib import Path

REQUIRED={'jdk-corresponding-source','saxon-native-source-notices','artwork-permissions','native-client-redistribution'}


def verify(legal,review):
    report=json.loads((legal/'RELEASE_REVIEW.json').read_text(encoding='utf-8'))
    if report['technicalChecks']!='passed':raise ValueError('Technical compliance checks have not passed')
    decisions=json.loads(review.read_text(encoding='utf-8'))
    if not decisions.get('reviewer') or not decisions.get('reviewedAt'):raise ValueError('Reviewer and review date are required')
    accepted={item['id'] for item in decisions.get('decisions',[]) if item.get('approved') is True and item.get('evidence')}
    missing=REQUIRED-accepted
    if missing:raise ValueError('Public release remains blocked pending evidence: '+', '.join(sorted(missing)))
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('legal');parser.add_argument('--review',required=True)
    args=parser.parse_args();verify(Path(args.legal),Path(args.review));print('Recorded release review is complete; retain its evidence with the release.')
