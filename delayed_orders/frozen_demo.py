"""Pinned, validated model outputs for the offline demo. No provider calls."""
from datetime import datetime,timezone
import hashlib
import json
import copy
from pathlib import Path

from .decision_rubric import for_category,parse_rubric
from .evidence import AccessDenied
from .policy_reviews import verified_issue

ROOT=Path(__file__).resolve().parents[1]
CASES=('GG-01','GG-02','GG-03','GG-04','CC-01','CC-02','CC-03')


class FrozenDemo:
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else ROOT/'demo-results'
        self._cache={}

    def _read(self,name):
        path=self.root/name
        if self.root.resolve()!=self.root.absolute() or path.resolve()!=self.root.absolute()/name:
            raise AccessDenied('Redirected saved demo path')
        if path.stat().st_nlink!=1 or path.stat().st_size>2_000_000:raise AccessDenied('Invalid saved demo artifact')
        return path.read_bytes()

    def inbox(self,analysis_mode=None):
        if analysis_mode not in (None,'cost','latency','astra'):raise AccessDenied('Choose a supported cached analysis')
        if analysis_mode in self._cache:return copy.deepcopy(self._cache[analysis_mode])
        prefix=analysis_mode+'-' if analysis_mode else ''
        manifest=json.loads(self._read(prefix+'manifest.json'))
        raw=self._read(prefix+'inbox.json')
        if hashlib.sha256(raw).hexdigest()!=manifest['inbox_sha256']:raise ValueError('The frozen result checksum does not match')
        data=json.loads(raw)
        if [item['case_id'] for item in data['issues']]!=list(CASES):raise ValueError('The frozen demo requires all seven cases')
        if analysis_mode:
            from .analysis_models import profile
            model=profile(analysis_mode)['model']
            if data.get('cache_mode')!=analysis_mode or any(source['model']!=model for source in data['sources']):raise ValueError('Cached results do not match the selected model')
        self._cache[analysis_mode]=data
        return copy.deepcopy(data)


def freeze(delivery_run,cancellation_run,root=None):
    """Explicit host operation, invoked once after real outputs pass validation."""
    from .policy_reviews import PolicyReviews
    reviews=PolicyReviews()
    delivery=reviews.status(delivery_run);cancellation=reviews.status(cancellation_run)
    policy=delivery['policy']
    if cancellation['status']!='complete':raise ValueError('Cancellation analysis must complete before freezing')
    if parse_rubric(policy['raw_text'])!=policy['rubric'] or cancellation['policy']['rubric']!=policy['rubric']:
        raise ValueError('Saved analyses must use the same rubric')
    issues=[];sources=[]
    for cid in CASES:
        identifier=delivery_run if cid.startswith('GG-') else cancellation_run
        category='delivery' if cid.startswith('GG-') else 'cancellation'
        run=reviews._read(identifier,cid+'.json')
        selected_policy=delivery['policy'] if category=='delivery' else cancellation['policy']
        issue=verified_issue(cid,identifier,run,policy['threshold_percent'],
                             rubric=for_category(policy['rubric'],category),expected_model=selected_policy['analysis_model'])
        issues.append(issue)
        sources.append(dict(case_id=cid,run_id=identifier,model=run['metadata']['model'],
                            source_batch_status=delivery['status'] if category=='delivery' else cancellation['status'],
                            artifact_sha256=hashlib.sha256((reviews.root/identifier/(cid+'.json')).read_bytes()).hexdigest()))
    frozen_at=datetime.now(timezone.utc).isoformat()
    data=dict(mode='frozen',frozen_at=frozen_at,policy={k:policy[k] for k in ('threshold_percent','raw_text','rubric','analysis_model')},
              issues=issues,sources=sources,trace_runs=list(dict.fromkeys(source['run_id'] for source in sources)))
    folder=Path(root) if root is not None else ROOT/'demo-results'
    folder.mkdir(exist_ok=True)
    if (folder/'manifest.json').exists():raise FileExistsError('Frozen results already exist; never overwrite them implicitly')
    raw=json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    (folder/'inbox.json').write_bytes(raw)
    (folder/'manifest.json').write_text(json.dumps(dict(frozen_at=frozen_at,inbox_sha256=hashlib.sha256(raw).hexdigest(),sources=sources),indent=2),encoding='utf-8')
    return data


def build_model_cache(analysis_mode,case_runs):
    """Pin verified same-model cases from explicitly selected source runs."""
    from .analysis_models import profile
    from .policy_reviews import PolicyReviews
    selected=profile(analysis_mode)
    if analysis_mode not in ('cost','latency','astra') or set(case_runs)!=set(CASES):raise ValueError('Each model cache requires all seven cases')
    reviews=PolicyReviews();policy=None;issues=[];sources=[]
    for cid in CASES:
        identifier=case_runs[cid];job=reviews.status(identifier);current=job['policy']
        if parse_rubric(current['raw_text'])!=current['rubric']:raise ValueError('Source rubric mismatch')
        if policy is None:policy=current
        if current['rubric']!=policy['rubric'] or current['threshold_percent']!=policy['threshold_percent']:raise ValueError('Model caches require one consistent rubric')
        run=reviews._read(identifier,cid+'.json');category='delivery' if cid.startswith('GG-') else 'cancellation'
        issues.append(verified_issue(cid,identifier,run,policy['threshold_percent'],rubric=for_category(policy['rubric'],category),expected_model=selected['model']))
        sources.append(dict(case_id=cid,run_id=identifier,model=selected['model'],source_batch_status=job['status'],
                            artifact_sha256=hashlib.sha256((reviews.root/identifier/(cid+'.json')).read_bytes()).hexdigest()))
    data=dict(mode='frozen',cache_mode=analysis_mode,frozen_at=datetime.now(timezone.utc).isoformat(),
              policy=dict(threshold_percent=policy['threshold_percent'],raw_text=policy['raw_text'],rubric=policy['rubric'],analysis_model=selected['model']),
              issues=issues,sources=sources,trace_runs=list(dict.fromkeys(source['run_id'] for source in sources)))
    folder=ROOT/'demo-results';manifest=folder/(analysis_mode+'-manifest.json')
    if manifest.exists():raise FileExistsError('Model cache already exists; no implicit overwrite')
    raw=json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    (folder/(analysis_mode+'-inbox.json')).write_bytes(raw)
    manifest.write_text(json.dumps(dict(cache_mode=analysis_mode,inbox_sha256=hashlib.sha256(raw).hexdigest(),sources=sources),indent=2),encoding='utf-8')
    return data
