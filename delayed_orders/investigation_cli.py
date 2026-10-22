"""Host-side development command: preflight by default; --live explicitly invokes OpenAI."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid
from .evidence import DEVELOPMENT_CASES,Evidence
from .investigation import investigate,Limits,MODEL,WORKFLOW_VERSION,PROMPT_VERSION
from .openai_provider import OpenAIProvider,ProviderError,load_api_key
from .spend import SpendLedger,BudgetExceeded

PROJECT_ROOT=Path(__file__).resolve().parents[1]
DIMENSIONS=('grounding','diagnosis_discipline','action_quality','outcome_quality','priority_quality','decision_clarity')


def _write(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)
        stream.write('\n')


def _code_hashes():
    code=Path(__file__).resolve().parent
    names=('evidence.py','baseline.py','model_contract.py','investigation_tools.py','investigation.py',
           'openai_provider.py','spend.py','investigation_cli.py','gurgaon.py','gurgaon_cli.py','triage.py')
    return {name:hashlib.sha256((code/name).read_bytes()).hexdigest() for name in names}


def _scorecard(runs):
    cases={}
    for cid,run in runs.items():
        result=run['result']
        cases[cid]=dict(run_status=run['status'],reviewer=None,dimensions={k:None for k in DIMENSIONS},
            coverage_pass=None,critical_failures=None,case_pass=None,
            recommendations={r['id']:dict(dimensions={k:None for k in DIMENSIONS},critical_failures=None,pass_gate=None)
                             for r in result['recommendations']} if result else {},
            added_value_over_baseline=None,missed_patterns=None,unsupported_claims=None,
            substantive_corrections=None,unnecessary_human_questions=None,notes=None)
    return dict(status='pending_human_review',rubric_version='evaluation-criteria-v1',
                gate='Each material recommendation >=10/12, every dimension >=1, case coverage passes, no critical failures. No-action uses the same rubric.',cases=cases)


def main(argv=None, *, case_ids=DEVELOPMENT_CASES, evidence_type=Evidence, integrity=None):
    parser=argparse.ArgumentParser(description='Bounded development investigation; no UI/Jira or held-out cases')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--preflight',action='store_true',help='Check configuration without calling an API (default)')
    modes.add_argument('--live',action='store_true',help='Run OpenAI under the persistent US$2 development ceiling')
    parser.add_argument('--case',choices=case_ids,help='One development case; default is all four')
    args=parser.parse_args(argv)
    cases=[args.case] if args.case else list(case_ids)
    integrity_report=integrity() if integrity else None
    try:
        key=load_api_key(PROJECT_ROOT/'.env')
        configured=True
        credential_error=None
    except ProviderError as error:
        key=None
        configured=False
        credential_error=str(error)
    manifest=dict(workflow_version=WORKFLOW_VERSION,prompt_version=PROMPT_VERSION,model=MODEL,
        cases=cases,campaign_ceiling_usd=2,credential_configured=configured,credential_error=credential_error,
        limits=Limits().__dict__,provider='OpenAI',reasoning_effort='none',store=False,integrity=integrity_report,
        fixture_versions=sorted({evidence_type(cid).provenance()['fixture_version'] for cid in cases}),
        token_rates_usd_per_million=dict(input=.75,output=4.5),code_sha256=_code_hashes(),
        mode='live' if args.live else 'preflight',quality_evaluation='Human review required; automatic checks do not establish semantic grounding.')
    if not args.live:
        print(json.dumps(manifest,indent=2))
        return 0
    if not configured:
        print(json.dumps(dict(status='blocked',reason=credential_error,paid_requests=0)),file=sys.stderr)
        return 2
    output_root=PROJECT_ROOT/'investigation-runs'
    if output_root.resolve()!=PROJECT_ROOT.resolve()/'investigation-runs':
        print('Investigation output directory may not redirect outside the project.',file=sys.stderr)
        return 2
    output_root.mkdir(exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    folder=output_root/run_id
    folder.mkdir()
    manifest['run_id']=run_id
    manifest['started_at_utc']=datetime.now(timezone.utc).isoformat()
    _write(folder/'manifest.json',manifest)
    runs={}
    try:
        with SpendLedger(output_root/'spend-ledger.json') as ledger:
            provider=OpenAIProvider(key)
            for cid in cases:
                run=investigate(evidence_type(cid),provider,ledger=ledger,
                    before_dispatch=lambda metadata,cid=cid:_write(folder/(cid+'-preflight.json'),metadata))
                runs[cid]=run
                _write(folder/(cid+'.json'),run)
                # Stop a batch after provider/accounting failure; do not make repeated futile calls.
                if run['status'] in ('provider_failed','failed','budget_exhausted'): break
            manifest['campaign_accounted_micro_usd']=ledger.accounted_micro_usd
    except (BudgetExceeded,ProviderError,OSError,ValueError) as error:
        manifest['batch_error']=str(error)
    comparison={cid:dict(run_status=run['status'],baseline_flags=run['baseline']['findings'],
        model_result=run['result'],automated_errors=run['errors'],usage=run['usage'],latency_seconds=run['latency_seconds'],
        semantic_quality='pending_human_review') for cid,run in runs.items()}
    _write(folder/'comparison.json',comparison)
    _write(folder/'human-scorecard.json',_scorecard(runs))
    manifest['case_status']={cid:runs[cid]['status'] if cid in runs else 'not_run' for cid in cases}
    manifest['status']='complete' if all(s=='complete' for s in manifest['case_status'].values()) and not manifest.get('batch_error') else 'partial_or_failed'
    _write(folder/'batch-summary.json',manifest)
    print(json.dumps(dict(status=manifest['status'],run_directory=str(folder),case_status=manifest['case_status'],
                          campaign_accounted_micro_usd=manifest.get('campaign_accounted_micro_usd')),indent=2))
    return 0 if manifest['status']=='complete' else 1


if __name__=='__main__': raise SystemExit(main())
