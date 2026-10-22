"""Host-side fresh investigations. Archived runs are never runtime evidence."""
import copy
import json
import math
from pathlib import Path
import re
import threading
import uuid
from datetime import datetime, timezone

from .evidence import AccessDenied
from .gurgaon import GurgaonEvidence,GURGAON_CASES
from .triage import POLICY
from .investigation import investigate
from .investigation_tools import InvestigationTools
from .model_contract import validate_result,ContractError
from .openai_provider import OpenAIProvider,load_api_key
from .spend import SpendLedger,BudgetExceeded,GenerationCancelled
from .decision_rubric import parse_rubric,for_category
from .analysis_models import profile

ROOT=Path(__file__).resolve().parents[1]
RUN_ROOT=ROOT/'policy-review-runs'
IDENTITY=re.compile(r'[a-f0-9]{32}')
CANCELLATION_CASES=('CC-01','CC-02','CC-03')


def review_case_ids(policy):
    bundle=policy.get('rubric')
    return GURGAON_CASES+CANCELLATION_CASES if bundle and bundle.get('structured') and bundle.get('cancellation_rules') else GURGAON_CASES


class ReviewError(ValueError): pass


class PolicyEvidence(GurgaonEvidence):
    def __init__(self,case_id,threshold):
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=100:
            raise ValueError('Invalid policy percentage')
        self._policy=dict(POLICY,threshold_percent=threshold,version=f'delayed-delivery-configured-{threshold:g}-v1')
        super().__init__(case_id)
    def triage_policy(self): return copy.deepcopy(self._policy)


def verified_issue(case_id,run_id,run,threshold,*,rubric=None,expected_model=None):
    if expected_model is not None and run.get('metadata',{}).get('model')!=expected_model:
        raise ReviewError('The investigation does not match the selected analysis model.')
    if case_id in CANCELLATION_CASES:
        from .cancellation_review import cancellation_issue
        return cancellation_issue(case_id,run_id,run,rubric=rubric)
    evidence=PolicyEvidence(case_id,threshold);tools=InvestigationTools(evidence)
    if (run.get('status')!='complete' or run.get('metadata',{}).get('fixture')!=evidence.provenance()
        or run['metadata'].get('triage_policy')!=tools.triage):
        raise ReviewError('The investigation did not produce a complete matching-policy result.')
    if rubric is not None and run.get('metadata',{}).get('rubric_sha256')!=rubric['sha256']:
        raise ReviewError('The investigation does not match the applied rubric.')
    for step in run.get('tool_trace',[]):tools.execute(step.get('name'),step.get('arguments'))
    validate_result(run['result'],tools)
    return dict(case_id=case_id,run_id=run_id,scope=evidence.request()['scope'],
                metrics=tools.baseline['metrics'],definitions=tools.baseline['definitions'],
                stage_coverage=tools.baseline['stage_coverage'],coverage=tools.baseline['coverage'],
                result=run['result'],triage_policy=tools.triage,rubric_sha256=run.get('metadata',{}).get('rubric_sha256'),
                validation=dict(status='passed',checks=['current_output_contract','deterministic_figures','retrieved_citations','action_readiness','applied_policy'],semantic_quality='not_scored'))


def _write(path,value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)
    if path.exists():raise FileExistsError('Review artifact already exists')
    temporary.rename(path)


def run_review(policy,folder,progress,cancelled):
    model=profile(policy.get('analysis_mode','cost'))['model']
    class CancellableProvider(OpenAIProvider):
        def count_input(self,payload):
            if cancelled.is_set():raise BudgetExceeded('Review cancelled')
            count=super().count_input(payload)
            if cancelled.is_set():raise BudgetExceeded('Review cancelled during token counting')
            return count
        def respond(self,payload):
            if cancelled.is_set():raise GenerationCancelled('Review cancelled before generation dispatch')
            return super().respond(payload)
    ledger_path=ROOT/'investigation-runs'/'spend-ledger.json'
    if ledger_path.resolve()!=ledger_path:raise AccessDenied('Redirected spending ledger')
    provider=CancellableProvider(load_api_key(ROOT/'.env'))
    with SpendLedger(ledger_path) as ledger:
        for index,case_id in enumerate(review_case_ids(policy)):
            if cancelled.is_set():return
            category='cancellation' if case_id in CANCELLATION_CASES else 'delivery'
            rubric=for_category(policy['rubric'],category) if policy.get('rubric') else None
            if category=='cancellation':
                from .cancellation_review import CancellationEvidence,investigate_cancellation
                evidence=CancellationEvidence(case_id)
                progress(index,f"{evidence.request()['scope']['store_ids'][0]} · Item cancellations")
                run=investigate_cancellation(case_id,provider,ledger=ledger,rubric=rubric,model=model)
            else:
                evidence=PolicyEvidence(case_id,policy['threshold_percent'])
                progress(index,f"{evidence.request()['scope']['store_ids'][0]} · Delayed deliveries")
                run=investigate(evidence,provider,ledger=ledger,synthesis_after_calls=0,compact_output=True,prepare_observations=True,rubric=rubric,model=model)
            _write(folder/(case_id+'.json'),run)
            if cancelled.is_set():return
            try:verified_issue(case_id,folder.name,run,policy['threshold_percent'],rubric=rubric,expected_model=model)
            except (ReviewError,ContractError,ValueError,KeyError,TypeError):
                raise ReviewError(f'{evidence.request()["scope"]["store_ids"][0]} could not produce a validated review ({run["status"]}). Previous results have not changed.') from None
            progress(index+1,None)


class PolicyReviews:
    def __init__(self,*,root=None,runner=None):
        self.root=Path(root) if root is not None else RUN_ROOT
        self.expected=self.root.absolute();self.runner=runner or run_review
        self.lock=threading.RLock();self.policies={};self.jobs={};self.active=None;self.cancelled=set()

    def _path(self,*parts):
        if self.root.resolve()!=self.expected:raise AccessDenied('Redirected policy-review root')
        path=self.root
        for part in parts:
            path=path/part
            if path.resolve()!=path:raise AccessDenied('Redirected policy-review path')
        return path

    def _read(self,*parts):
        path=self._path(*parts)
        if not path.is_file():raise FileNotFoundError('Review not found')
        if path.stat().st_nlink!=1 or path.stat().st_size>2_000_000:raise AccessDenied('Unsupported review artifact')
        return json.loads(path.read_text(encoding='utf-8'))

    def register(self,interpretation,text):
        selected=profile(interpretation.get('analysis_mode','cost'))
        if interpretation.get('status')!='supported':raise ReviewError('A supported interpreted policy is required')
        PolicyEvidence(GURGAON_CASES[0],interpretation['threshold_percent'])
        rubric=parse_rubric(text)
        if interpretation.get('rubric') is not None and interpretation['rubric']!=rubric:
            raise ReviewError('The interpreted rubric does not match the entered document')
        interpretation=dict(interpretation,rubric=rubric,case_ids=list(review_case_ids({'rubric':rubric})),analysis_mode=selected['mode'],analysis_model=selected['model'])
        interpretation['total_cases']=len(interpretation['case_ids'])
        with self.lock:
            if len(self.policies)>=100:self.policies.pop(next(iter(self.policies)))
            identifier=uuid.uuid4().hex
            self.policies[identifier]=dict(interpretation,raw_text=text)
        return dict(interpretation,interpretation_id=identifier)

    def _identity(self,value):
        if not isinstance(value,str) or not IDENTITY.fullmatch(value):raise AccessDenied('Unsupported review identity')

    def _save(self,job):
        path=self._path(job['run_id'],'status.json');temp=self._path(job['run_id'],'status.tmp')
        temp.write_text(json.dumps(job,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)

    def start(self,interpretation_id,request_id):
        self._identity(request_id)
        with self.lock:
            if request_id in self.jobs:return self.status(request_id)
            if request_id in self.cancelled:raise ReviewError('Review was cancelled')
            if interpretation_id not in self.policies:raise AccessDenied('Interpret the policy before reviewing tickets')
            if self.active:raise ReviewError('A review is still finishing. Wait briefly before running again.')
            policy=copy.deepcopy(self.policies[interpretation_id]);self.root.mkdir(exist_ok=True)
            folder=self._path(request_id);folder.mkdir()
            case_ids=list(review_case_ids(policy))
            job=dict(run_id=request_id,status='running',completed_cases=0,current_store=None,error=None,policy=policy,case_ids=case_ids,total_cases=len(case_ids),started_at=datetime.now(timezone.utc).isoformat())
            self._save(job);self.jobs[request_id]=job;self.active=request_id
            threading.Thread(target=self._work,args=(request_id,),daemon=True).start()
            return self.status(request_id)

    def _work(self,identifier):
        event=threading.Event()
        with self.lock:self.jobs[identifier+'_event']=event
        def progress(completed,store):
            with self.lock:
                job=self.jobs[identifier];job.update(completed_cases=completed,current_store=store);self._save(job)
        try:
            with self.lock:
                if identifier in self.cancelled:event.set()
                policy=copy.deepcopy(self.jobs[identifier]['policy'])
            self.runner(policy,self._path(identifier),progress,event)
            if not event.is_set():
                for cid in review_case_ids(policy):
                    category='cancellation' if cid in CANCELLATION_CASES else 'delivery'
                    rubric=for_category(policy['rubric'],category) if policy.get('rubric') else None
                    verified_issue(cid,identifier,self._read(identifier,cid+'.json'),policy['threshold_percent'],rubric=rubric,expected_model=policy.get('analysis_model'))
            with self.lock:self.jobs[identifier]['status']='cancelled' if event.is_set() else 'complete'
        except Exception as error:
            with self.lock:
                job=self.jobs[identifier];job['status']='cancelled' if event.is_set() else 'failed'
                job['error']=str(error) if isinstance(error,(ReviewError,BudgetExceeded)) else 'The review could not complete. Previous results have not changed.'
        finally:
            with self.lock:
                job=self.jobs[identifier];job['current_store']=None;job['finished_at']=datetime.now(timezone.utc).isoformat();self.active=None;self._save(job)

    def status(self,identifier):
        self._identity(identifier)
        with self.lock:
            job=self.jobs.get(identifier) or self._read(identifier,'status.json')
            if identifier not in self.jobs and job['status']=='running':
                job=dict(job,status='failed',error='The review was interrupted. Run again to start a new review.')
            return copy.deepcopy(job)

    def cancel(self,identifier):
        self._identity(identifier)
        with self.lock:
            self.cancelled.add(identifier)
            event=self.jobs.get(identifier+'_event')
            if event:event.set()
            return dict(run_id=identifier,status='cancelling')

    def inbox(self,identifier):
        job=self.status(identifier)
        if job['status']!='complete':raise ReviewError('This review has not completed successfully')
        policy=job['policy']
        if policy.get('rubric'):
            try:matches=parse_rubric(policy['raw_text'])==policy['rubric']
            except (ValueError,KeyError):matches=False
            if not matches:raise ReviewError('The archived rubric does not match its source document')
        case_ids=review_case_ids(policy)
        if job.get('case_ids',list(case_ids))!=list(case_ids):raise ReviewError('The archived case selection does not match the rubric')
        issues=[]
        for cid in case_ids:
            category='cancellation' if cid in CANCELLATION_CASES else 'delivery'
            rubric=for_category(policy['rubric'],category) if policy.get('rubric') else None
            issues.append(verified_issue(cid,identifier,self._read(identifier,cid+'.json'),policy['threshold_percent'],rubric=rubric,expected_model=policy.get('analysis_model')))
        return dict(run_id=identifier,policy=job['policy'],issues=issues)
