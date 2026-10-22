"""Fixed Gurgaon development capability and host-side record integrity validation."""
import json
from pathlib import Path
from .evidence import Evidence, AccessDenied, SOURCES, DataError
from .baseline import analyze, _time
from .triage import POLICY
import copy

ROOT=Path(__file__).resolve().parents[1]
GURGAON_CASES=('GG-01','GG-02','GG-03','GG-04')
FIXTURE_VERSION='gurgaon-v2'
INPUT_ROOT=ROOT/'fixtures'/FIXTURE_VERSION/'agent-inputs'


class GurgaonEvidence(Evidence):
    def triage_policy(self):
        return copy.deepcopy(POLICY)

    def __init__(self,case_id):
        if case_id not in GURGAON_CASES:
            raise AccessDenied('Only the four Gurgaon development cases are enabled')
        if INPUT_ROOT.resolve()!=ROOT/'fixtures'/FIXTURE_VERSION/'agent-inputs':
            raise AccessDenied('Redirected Gurgaon input root')
        self._load_case(case_id,INPUT_ROOT,FIXTURE_VERSION)


def validate_pack():
    """Host command only. Runtime loading never reads this freeze manifest."""
    manifest=json.loads((INPUT_ROOT.parent/'freeze-manifest.json').read_text(encoding='utf-8'))
    hashes={}; orders=0
    for cid in GURGAON_CASES:
        ev=GurgaonEvidence(cid); b=analyze(ev)
        for filename,digest in ev.provenance()['sha256'].items(): hashes[cid+'/'+filename]=digest
        observations={r['order_id']:r for r in b['order_observations']}
        records=ev.query('orders')['records']; orders+=len(records)
        for row in records:
            oid=row['order_id']; placed=_time(row['placed_at']); delivered=_time(row['delivered_at'])
            promise=_time(row['original_promised_latest_at'])
            events=ev.query('order_events',order_ids=[oid])['records']
            times={r['event_type']:_time(r['occurred_at']) for r in events}
            if not (len(events)==6 and times['order_placed']==placed and times['delivered']==delivered and
                    placed<=times['packing_started']<=times['packing_completed']<=times['rider_assigned']<=times['picked_up']<=delivered):
                raise DataError('Order/event chronology mismatch')
            history=ev.query('promise_history',order_ids=[oid])['records']
            if len(history)!=1 or history[0]['kind']!='checkout' or _time(history[0]['promised_latest_at'])!=promise:
                raise DataError('Checkout promise mismatch')
            if observations[oid]['gaps']: raise DataError('Unexpected stage/log gap')
        if b['metrics']['excluded_unique_orders'] or b['metrics']['out_of_scope_orders']:
            raise DataError('Unexpected exclusion or scope error')
    if hashes!=manifest['sha256']: raise DataError('Gurgaon frozen hashes changed')
    return dict(status='PASS',protected_files=len(hashes),orders=orders,case_count=4)


if __name__=='__main__': print(json.dumps(validate_pack(),indent=2))
