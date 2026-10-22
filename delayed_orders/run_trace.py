"""Read-only demo observability from saved, allowlisted run artifacts."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from .evidence import AccessDenied
from .analysis_models import model_pricing,COST_MODEL,LATENCY_MODEL,profile,mode_for_model

ROOT=Path(__file__).resolve().parents[1]
CASES=('GG-01','GG-02','GG-03','GG-04','CC-01','CC-02','CC-03')
REVIEW_ID=re.compile(r'[a-f0-9]{32}')
ARCHIVE_ID=re.compile(r'\d{8}T\d{6}Z-[a-f0-9]{8}')
PRICING=model_pricing(COST_MODEL)
REQUEST_KEYS=('model','service_tier','instructions','input','tools','tool_choice','text','reasoning','prompt_cache_options','store','max_output_tokens')
RESPONSE_KEYS=('id','model','service_tier','status','usage','output','incomplete_details','error')


def record_interpretation_failure(audits,error,root=None):
    """Preserve dispatched interpretation failures before a review batch exists."""
    root=Path(root) if root is not None else ROOT/'policy-review-runs'
    if root.resolve()!=root.absolute():raise AccessDenied('Redirected trace root')
    root.mkdir(exist_ok=True)
    identifier=uuid.uuid4().hex;folder=root/identifier;folder.mkdir()
    job=dict(run_id=identifier,kind='Rubric interpretation',status='failed',case_ids=[],total_cases=0,completed_cases=0,
             policy={'model_trace':audits,'analysis_mode':mode_for_model(audits[0].get('request',{}).get('model'))},error=error,started_at=audits[0].get('started_at'),
             finished_at=datetime.now(timezone.utc).isoformat())
    temporary=folder/'status.tmp'
    with temporary.open('x',encoding='utf-8') as stream:json.dump(job,stream,ensure_ascii=False,allow_nan=False)
    temporary.rename(folder/'status.json')
    return identifier


def tokens(value):
    return value if type(value) is int and value>=0 else None


def call_summary(audit):
    request=audit.get('request') or {};response=audit.get('response') or {}
    if not isinstance(response,dict):response={}
    usage=response.get('usage') or {}
    if not isinstance(usage,dict):usage={}
    inputs,outputs=tokens(usage.get('input_tokens')),tokens(usage.get('output_tokens'))
    details=usage.get('input_tokens_details') or {}
    cached=tokens(details.get('cached_tokens')) if isinstance(details,dict) else None
    writes=tokens(details.get('cache_write_tokens',0)) if isinstance(details,dict) else 0
    if cached is not None and inputs is not None and cached>inputs:cached=None
    if writes is None or inputs is not None and writes+(cached or 0)>inputs:writes=0
    model=response.get('model') or request.get('model')
    try:pricing=model_pricing(model)
    except ValueError:pricing=None
    cost=None
    if inputs is not None and outputs is not None and pricing is not None:
        cached_for_cost=cached or 0
        cost=((inputs-cached_for_cost-writes)*pricing['input_per_million']+writes*pricing.get('cache_write_per_million',pricing['input_per_million'])+
              cached_for_cost*pricing['cached_input_per_million']+outputs*pricing['output_per_million'])/1_000_000
    return dict(model=model,status=audit.get('status') or response.get('status') or 'usage_unavailable',
                phase=audit.get('phase','investigation'),duration_seconds=audit.get('duration_seconds'),
                input_tokens=inputs,cached_input_tokens=cached,cache_write_tokens=writes,output_tokens=outputs,
                total_tokens=inputs+outputs if inputs is not None and outputs is not None else None,
                estimated_cost_usd=cost,pricing=pricing,validation_error=audit.get('validation_error'),
                request={k:copy.deepcopy(request[k]) for k in REQUEST_KEYS if k in request},
                response={k:copy.deepcopy(response[k]) for k in RESPONSE_KEYS if k in response})


def summarize_calls(audits):
    calls=[call_summary(audit) for audit in audits]
    missing=sum(call['total_tokens'] is None for call in calls)
    unknown_cost=sum(call['estimated_cost_usd'] is None for call in calls)
    return dict(calls=len(calls),input_tokens=sum(call['input_tokens'] or 0 for call in calls),
                cached_input_tokens=sum(call['cached_input_tokens'] or 0 for call in calls),
                output_tokens=sum(call['output_tokens'] or 0 for call in calls),
                total_tokens=sum((call['input_tokens'] or 0)+(call['output_tokens'] or 0) for call in calls),missing_usage_calls=missing,
                unknown_cache_calls=sum(call['total_tokens'] is not None and call['cached_input_tokens'] is None for call in calls),
                unpriced_calls=unknown_cost,
                estimated_cost_usd=sum(call['estimated_cost_usd'] or 0 for call in calls) if calls and unknown_cost<len(calls) else None)


class TraceStore:
    def __init__(self,reviews=None,archives=None,active_run=None):
        self.reviews=Path(reviews) if reviews is not None else ROOT/'policy-review-runs'
        self.archives=Path(archives) if archives is not None else ROOT/'investigation-runs'
        self.expected=(self.reviews.absolute(),self.archives.absolute())
        self.active_run=active_run

    def _folder(self,identifier):
        if not isinstance(identifier,str):raise AccessDenied('Unsupported trace identity')
        if REVIEW_ID.fullmatch(identifier):root,expected=self.reviews,self.expected[0]
        elif ARCHIVE_ID.fullmatch(identifier):root,expected=self.archives,self.expected[1]
        else:raise AccessDenied('Unsupported trace identity')
        folder=root/identifier
        if root.resolve()!=expected or folder.resolve()!=expected/identifier:raise AccessDenied('Redirected trace path')
        if not folder.is_dir():raise FileNotFoundError('Trace not found')
        return folder

    def _read(self,folder,name):
        path=folder/name
        if path.resolve()!=path.absolute():raise AccessDenied('Redirected trace artifact')
        if not path.is_file():raise FileNotFoundError('Trace artifact not found')
        if path.stat().st_nlink!=1 or path.stat().st_size>2_000_000:raise AccessDenied('Unsupported trace artifact')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict):raise ValueError('Invalid trace artifact')
        return value

    def _job(self,folder):
        job=self._read(folder,'status.json')
        if job.get('status')=='running' and self.active_run is not None and self.active_run()!=folder.name:
            job=dict(job,status='interrupted',error='This run was interrupted; recorded usage may be incomplete.')
        return job

    def history(self):
        candidates=[]
        for root,expected,pattern in ((self.reviews,self.expected[0],REVIEW_ID),(self.archives,self.expected[1],ARCHIVE_ID)):
            if root.resolve()!=expected:raise AccessDenied('Redirected trace root')
            if not root.exists():continue
            for path in root.iterdir():
                if not pattern.fullmatch(path.name):continue
                folder=self._folder(path.name)
                status=folder/'status.json'
                stamps=[file.stat().st_mtime for file in [status,*[folder/(cid+'.json') for cid in CASES]] if file.is_file()]
                if not stamps:continue
                candidates.append((max(stamps),path.name))
        rows=[]
        for stamp,identifier in sorted(candidates,reverse=True)[:30]:
            folder=self._folder(identifier)
            try:job=self._job(folder) if REVIEW_ID.fullmatch(identifier) else {}
            except (OSError,ValueError):continue
            rows.append(dict(run_id=identifier,status=job.get('status','archived'),
                             saved_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                             started_at=job.get('started_at'),kind=job.get('kind','Rubric review') if job else 'Archived investigation'))
        return dict(runs=rows,pricing=copy.deepcopy(PRICING))

    def detail(self,identifier):
        folder=self._folder(identifier);is_review=bool(REVIEW_ID.fullmatch(identifier))
        job=self._job(folder) if is_review else {}
        interpretation=(job.get('policy') or {}).get('model_trace',[])
        selected=profile((job.get('policy') or {}).get('analysis_mode','cost'))
        all_audits=list(interpretation);cases=[]
        ids=job.get('case_ids',list(CASES))
        if not isinstance(ids,list) or any(cid not in CASES for cid in ids) or len(set(ids))!=len(ids):raise AccessDenied('Unsupported trace cases')
        for index,cid in enumerate(ids):
            try:run=self._read(folder,cid+'.json')
            except FileNotFoundError:
                if not is_review:continue
                run={'status':'running' if job.get('status')=='running' and index==job.get('completed_cases',0) else 'not_started'}
            audits=run.get('model_trace',[]);all_audits.extend(audits)
            metadata=run.get('metadata') or {};fixture=metadata.get('fixture') or {}
            cases.append(dict(case_id=cid,category='Item cancellation' if cid.startswith('CC-') else 'Delayed delivery',
                              status=run.get('status','unknown'),duration_seconds=run.get('latency_seconds'),
                              evidence_files=sorted((fixture.get('sha256') or {}).keys()),
                              rubric_sha256=metadata.get('rubric_sha256'),calls=[call_summary(audit) for audit in audits],
                              totals=summarize_calls(audits),reserved_micro_usd=run.get('usage',{}).get('reserved_micro_usd',0),
                              validation='passed' if run.get('status')=='complete' else 'not passed',
                              result=run.get('result'),errors=run.get('errors',[])))
        return dict(run_id=identifier,kind=job.get('kind','Rubric review') if is_review else 'Archived investigation',
                    status=job.get('status','archived'),started_at=job.get('started_at'),finished_at=job.get('finished_at'),
                    completed_cases=job.get('completed_cases'),total_cases=job.get('total_cases'),
                    published=is_review and job.get('status')=='complete',error=job.get('error'),
                    interpretation=[call_summary(audit) for audit in interpretation],
                    interpretation_recorded=bool(interpretation),cases=cases,totals=summarize_calls(all_audits),
                    interpretation_reserved_micro_usd=sum(audit.get('reserved_micro_usd',0) for audit in interpretation),
                    analysis_mode=selected['mode'],analysis_model=selected['model'],pricing=model_pricing(selected['model']))
