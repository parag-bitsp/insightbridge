"""Local review app with a bounded policy-reader action; evidence stays read-only."""
import argparse
import copy
import json
import os
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .baseline import analyze
from .evidence import AccessDenied, DEVELOPMENT_CASES, Evidence, SOURCES
from .model_contract import RESULT_SCHEMA, ContractError, validate_shape, validate_result
from .investigation_tools import InvestigationTools
from .gurgaon import GURGAON_CASES, GurgaonEvidence
from .policy_reviews import PolicyReviews,ReviewError

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / 'investigation-runs'
ASSET_ROOT = ROOT / 'delayed_orders/web'
RUN_ID = re.compile(r'\d{8}T\d{6}Z-[a-f0-9]{8}')
REVIEW_CASES = DEVELOPMENT_CASES + GURGAON_CASES
CANCELLATION_LIBRARY_CASES = ('CC-01','CC-02','CC-03')
BASELINE_FIELDS = ('metrics','calculations','definitions','findings','coverage',
                   'stage_coverage','source_gaps','limitations','provenance')
LEGACY_SCHEMA = copy.deepcopy(RESULT_SCHEMA)
for _field in ('remaining_question','human_work_reason','required_sources','expertise_or_access_needed','gap_refs'):
    _recommendation = LEGACY_SCHEMA['properties']['recommendations']['items']
    _recommendation['properties'].pop(_field)
    _recommendation['required'].remove(_field)


def _read(root, expected, *parts):
    # Roots are host constants. Callers supply only validated symbols.
    if root != expected or root.resolve() != expected:
        raise AccessDenied('Redirected content root')
    path = root
    for part in parts:
        path = path / part
        if path.resolve() != path: raise AccessDenied('Redirected content path')
    if not path.is_file(): raise FileNotFoundError('Artifact unavailable')
    if path.stat().st_nlink != 1 or path.stat().st_size > 2_000_000:
        raise AccessDenied('Unsupported review artifact')
    return path.read_bytes()


def _result_shape(value, legacy=False):
    try:
        validate_shape(value, LEGACY_SCHEMA if legacy else RESULT_SCHEMA)
        return value
    except (ContractError, TypeError, KeyError): return None


def present_run(run_id, run):
    """Expose a curated view, never provider requests, instructions or file access."""
    status = run['status']
    meta = run.get('metadata',{})
    legacy = meta.get('workflow_version') in ('investigation-1','investigation-1.1')
    result = _result_shape(run.get('result'),legacy) if status == 'complete' else None
    state = 'structurally_valid' if result else 'no_result'
    if status == 'invalid_output':
        for step in reversed(run.get('model_trace', [])):
            texts = [c.get('text','') for item in step.get('response',{}).get('output',[])
                     for c in item.get('content',[]) if c.get('type') == 'output_text']
            if texts:
                try: result = _result_shape(json.loads(''.join(texts)),legacy)
                except (ValueError, TypeError): result = None
                break
        if result: state = 'blocked_draft'
    return dict(run_id=run_id, status=status, display_state=state, display_result=result,
        historical_contract=legacy,
        errors=run.get('errors',[]), usage=run.get('usage',{}), latency_seconds=run.get('latency_seconds'),
        quality_status='pending_human_review',
        metadata={k:meta.get(k) for k in ('workflow_version','prompt_version','model','provider',
                  'fixture','limits','prompt_sha256','schema_sha256','tools_sha256')},
        model_steps=[dict(phase=s.get('phase','investigation'), counted_input_tokens=s.get('counted_input_tokens'),
                         status=s.get('response',{}).get('status'), usage=s.get('response',{}).get('usage',{}))
                     for s in run.get('model_trace',[])],
        tool_steps=[{k:s.get(k) for k in ('name','arguments','origin','cached','result')}
                    for s in run.get('tool_trace',[])])


class ReviewStore:
    def cancellation_feedback(self,case_id,*,offset=0):
        """Library-only reads; cancellation cases are not model-review capabilities."""
        if case_id not in CANCELLATION_LIBRARY_CASES or type(offset) is not int or not 0<=offset<=100000:
            raise AccessDenied('Unsupported cancellation case or offset')
        root=ROOT/'fixtures/cancellations-v1/agent-inputs'/case_id
        def document(name): return json.loads(_read(root,root,name))
        request=document('request.json'); catalog=document('source_catalog.json'); items=document('item_catalog.json')
        if request['case_id']!=case_id or catalog['case_id']!=case_id or catalog['sources']['feedback']['path']!='feedback.jsonl':
            raise AccessDenied('Cancellation evidence identity mismatch')
        if catalog['sources']['feedback']['status']!='available':
            raise AccessDenied('Cancellation complaints are unavailable')
        item=next((item for item in items if item['product_id']==request['focus_product_id']),None)
        if item is None: raise AccessDenied('Cancellation item is unavailable')
        records=[json.loads(line) for line in _read(root,root,'feedback.jsonl').decode('utf-8').splitlines() if line.strip()]
        if (len({r['source_id'] for r in records})!=len(records) or
            any(r['case_id']!=case_id or not r['source_id'].startswith(case_id+'-') or
                not r['order_id'].startswith(case_id+'-ORD-') or not r['line_id'].startswith(case_id+'-LINE-') or
                r['store_id'] not in request['scope']['store_ids'] or r['product_id']!=item['product_id'] for r in records)):
            raise AccessDenied('Cancellation complaint joins outside its case')
        page=records[offset:offset+10]
        return dict(case_id=case_id,status='available',records=page,total=len(records),
                    item_label=f"{item['product_name']} - {item['pack_size']}",
                    source_multiplicities={r['source_id']:1 for r in page},
                    next_offset=offset+10 if offset+10<len(records) else None)

    def _evidence(self, case_id):
        # The host selects fixed capabilities; HTTP callers cannot supply roots.
        return GurgaonEvidence(case_id) if case_id in GURGAON_CASES else Evidence(case_id)

    def _snapshot(self, case_id):
        evidence = self._evidence(case_id)
        return evidence, analyze(evidence)

    def _load_run(self, case_id, run_id):
        if case_id not in REVIEW_CASES or not RUN_ID.fullmatch(run_id):
            raise AccessDenied('Unsupported case or run')
        run = json.loads(_read(RUN_ROOT, ROOT/'investigation-runs', run_id, case_id+'.json'))
        if run.get('metadata',{}).get('fixture',{}).get('case_id') != case_id:
            raise AccessDenied('Run case does not match')
        return run

    def runs(self, case_id):
        if case_id not in REVIEW_CASES: raise AccessDenied('Unsupported case')
        if RUN_ROOT != ROOT/'investigation-runs' or RUN_ROOT.resolve() != RUN_ROOT:
            raise AccessDenied('Redirected run root')
        result = []
        for folder in sorted(RUN_ROOT.iterdir(), reverse=True) if RUN_ROOT.exists() else []:
            if not RUN_ID.fullmatch(folder.name): continue
            try:
                raw = self._load_run(case_id, folder.name)
                meta = raw.get('metadata',{})
                result.append(dict(run_id=folder.name, status=raw['status'],
                    workflow_version=meta.get('workflow_version'), prompt_version=meta.get('prompt_version')))
            except FileNotFoundError: continue
        return result

    def run(self, case_id, run_id):
        view = present_run(run_id, self._load_run(case_id, run_id))
        view['fixture_matches'] = view['metadata']['fixture'] == self._evidence(case_id).provenance()
        return view

    def inbox(self):
        issues = []
        for cid in DEVELOPMENT_CASES:
            evidence, baseline = self._snapshot(cid)
            runs = self.runs(cid)
            issues.append(dict(case_id=cid, scope=evidence.request()['scope'], findings=baseline['findings'],
                metrics={k:baseline['metrics'][k] for k in ('late_orders','eligible_orders','late_rate',
                    'excluded_unique_orders','support_contacts','contacted_unique_orders','contacted_late_orders')},
                latest_run=runs[0] if runs else None))
        return dict(is_synthetic=True, issues=issues)

    def lead_inbox(self, case_ids=GURGAON_CASES):
        """Latest current-contract successes only; replay checks, never repair outputs.

        No earlier successful run substitutes for a later failed case. Reference
        truth/held-out answers are never loaded, and this is not semantic scoring.
        """
        issues = []
        for cid in case_ids:
            runs = self.runs(cid)
            if not runs or runs[0]['status'] != 'complete': continue
            run_id = runs[0]['run_id']
            raw = self._load_run(cid, run_id)
            # Optional developer-review veto. It can exclude a known bad result,
            # never approve one, rewrite it, or bypass the automatic checks.
            try:
                review=json.loads(_read(RUN_ROOT,ROOT/'investigation-runs',run_id,cid+'-review.json'))
                if (review.get('case_id')!=cid or review.get('run_id')!=run_id or
                    review.get('status')!='blocked_by_developer_review' or not review.get('reason')):
                    raise AccessDenied('Invalid review record')
                continue
            except FileNotFoundError: pass
            evidence = self._evidence(cid)
            if raw['metadata'].get('fixture') != evidence.provenance(): continue
            tools = InvestigationTools(evidence)
            if tools.triage and raw['metadata'].get('triage_policy')!=tools.triage: continue
            try:
                validate_shape(raw.get('result'), RESULT_SCHEMA)
                for step in raw.get('tool_trace', []):
                    tools.execute(step.get('name'), step.get('arguments'))
                validate_result(raw['result'], tools)
            except (ContractError, ValueError, KeyError, TypeError):
                continue
            issues.append(dict(case_id=cid, run_id=run_id, scope=evidence.request()['scope'],
                metrics=tools.baseline['metrics'], definitions=tools.baseline['definitions'],
                stage_coverage=tools.baseline['stage_coverage'], coverage=tools.baseline['coverage'],
                result=raw['result'], validation=dict(status='passed',
                    checks=['current_output_contract','deterministic_figures','retrieved_citations','action_readiness'],
                    semantic_quality='not_scored'),triage_policy=tools.triage))
        return dict(issues=issues)

    def case(self, case_id):
        evidence, baseline = self._snapshot(case_id)
        return dict(case_id=case_id, is_synthetic=True, request=evidence.request(),
                    baseline={k:baseline[k] for k in BASELINE_FIELDS}, runs=self.runs(case_id))

    def evidence(self, case_id, source, *, offset=0, order_id=None):
        if type(offset) is not int or not 0 <= offset <= 100000:
            raise AccessDenied('Unsupported offset')
        if case_id in CANCELLATION_LIBRARY_CASES:
            from .cancellation_review import CancellationEvidence
            return CancellationEvidence(case_id).query(source,offset=offset,limit=10,order_ids=[order_id] if order_id else None)
        return self._evidence(case_id).query(source, offset=offset, limit=10,
                                      order_ids=[order_id] if order_id else None)

    def citation(self, case_id, ref):
        if case_id in CANCELLATION_LIBRARY_CASES:
            from .cancellation_review import CancellationEvidence
            resolved=CancellationEvidence(case_id).citation(ref)
            if ref.split(':',1)[0] not in ('metric','source_status'):
                resolved['data']={'records':[resolved['data']]}
            return resolved
        evidence, baseline = self._snapshot(case_id)
        if not isinstance(ref,str) or len(ref)>160 or ref.count(':')!=1:
            raise AccessDenied('Unsupported citation')
        kind, key = ref.split(':')
        if kind=='metric' and key in baseline['metrics']:
            data = dict(value=baseline['metrics'][key], calculation=baseline['calculations'][key],
                        scope=baseline['scope'], definitions=baseline['definitions'])
        elif kind=='source_status' and key in SOURCES: data = baseline['coverage'][key]
        elif kind=='observation':
            evidence._check_ids([key], 'order')
            data = next((r for r in baseline['order_observations'] if r['order_id']==key), None)
            if data is None: raise FileNotFoundError('Observation not found')
        elif kind in SOURCES:
            data = evidence.query(kind, source_ids=[key], limit=1)
            if not data['records']: raise FileNotFoundError('Citation not found')
        else: raise AccessDenied('Unsupported citation')
        return dict(ref=ref, case_id=case_id, data=data,
            note='Human lookup in permitted case evidence. A resolved citation does not establish that the model retrieved it or that its claim is supported.')


def make_server(port=8765,policy_reader=None,review_service=None,feedback_store=None,*,allow_live_analysis=False,
                host='127.0.0.1',public_origin=None,trust_proxy=False):
    if public_origin and (urlsplit(public_origin).scheme!='https' or urlsplit(public_origin).path or
                          not urlsplit(public_origin).netloc):
        raise ValueError('Public origin must be an HTTPS origin')
    store = ReviewStore()
    reviews=review_service or PolicyReviews()
    from .run_trace import TraceStore
    traces=TraceStore(reviews.root,active_run=lambda:reviews.active)
    from .feedback import FeedbackStore,FeedbackError
    feedback=feedback_store or FeedbackStore()
    from .frozen_demo import FrozenDemo
    frozen=FrozenDemo()
    audit_path=ROOT/'demo-results/audit-manifest.json'
    selected_runs={row['run_id'] for row in json.loads(audit_path.read_text(encoding='utf-8'))['runs']} if audit_path.exists() else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def same_origin(self,require_origin=False):
            origins={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
            if public_origin:origins.add(public_origin)
            origin=self.headers.get('Origin')
            expected=next((item for item in origins if urlsplit(item).netloc==self.headers.get('Host')),None)
            return expected is not None and (origin==expected or origin is None and not require_origin)

        def visitor_ip(self):
            if trust_proxy:
                # Render's edge supplies the public client address. Local mode ignores proxy headers.
                candidate=self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For','').split(',')[-1].strip()
                try:return str(ipaddress.ip_address(candidate))
                except ValueError:pass
            return self.client_address[0]

        def send_data(self, code, data, mime='application/json; charset=utf-8'):
            body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError): pass

        def do_GET(self):
            if not self.same_origin():
                return self.send_data(403,{'error':'Same-origin access only'})
            try:
                url = urlsplit(self.path)
                path = unquote(url.path)
                query = parse_qs(url.query,keep_blank_values=True,strict_parsing=True)
                if any(len(v)!=1 for v in query.values()): raise AccessDenied('Duplicate parameter')
                query = {k:v[0] for k,v in query.items()}
                assets = {'/':('index.html','text/html; charset=utf-8'),
                          '/app.js':('app.js','text/javascript; charset=utf-8'),
                          '/run-trace.js':('run-trace.js','text/javascript; charset=utf-8'),
                          '/feedback.js':('feedback.js','text/javascript; charset=utf-8'),
                          '/style.css':('style.css','text/css; charset=utf-8')}
                if path in assets and not query:
                    name,mime = assets[path]
                    return self.send_data(200,_read(ASSET_ROOT,ROOT/'delayed_orders/web',name),mime)
                if path=='/favicon.ico' and not query: return self.send_data(204,b'')
                if path=='/api/cases' and not query: return self.send_data(200,store.inbox())
                if path=='/api/inbox' and set(query)<={'analysis_mode'}:
                    return self.send_data(200,store.lead_inbox() if allow_live_analysis else frozen.inbox(query.get('analysis_mode','latency')))
                if path=='/api/traces' and not query:
                    history=traces.history()
                    if selected_runs is not None and not allow_live_analysis:
                        history['runs']=[row for row in history['runs'] if row['run_id'] in selected_runs]
                        history.pop('pricing',None)
                    return self.send_data(200,history)
                trace_match=re.fullmatch(r'/api/traces/([a-f0-9]{32}|\d{8}T\d{6}Z-[a-f0-9]{8})',path)
                if trace_match and not query:
                    if selected_runs is not None and not allow_live_analysis and trace_match.group(1) not in selected_runs:raise FileNotFoundError()
                    return self.send_data(200,traces.detail(trace_match.group(1)))
                if path=='/api/rubric/default' and not query:
                    from .decision_rubric import default_rubric
                    return self.send_data(200,default_rubric())
                cancellation_library=re.fullmatch(r'/api/library/cancellations/(CC-\d{2})',path)
                if cancellation_library:
                    if set(query)-{'offset'}: raise AccessDenied('Unsupported library query parameters')
                    return self.send_data(200,store.cancellation_feedback(cancellation_library.group(1),offset=int(query.get('offset',0))))
                review_match=re.fullmatch(r'/api/policy/reviews/([a-f0-9]{32})(/inbox)?',path)
                if review_match and not query:
                    identifier,view=review_match.groups()
                    return self.send_data(200,reviews.inbox(identifier) if view else reviews.status(identifier))
                match = re.fullmatch(r'/api/cases/((?:DO|GG|CC)-\d{2})(?:/(runs|evidence|citation))?',path)
                if not match: raise FileNotFoundError()
                cid,action = match.groups()
                if cid.startswith('CC-') and action not in ('evidence','citation'):raise FileNotFoundError()
                if action is None and not query: value = store.case(cid)
                elif action=='runs' and set(query)=={'run'}: value = store.run(cid,query['run'])
                elif action=='evidence' and 'source' in query and set(query)<={'source','offset','order_id'}:
                    value = store.evidence(cid,query['source'],offset=int(query.get('offset',0)),order_id=query.get('order_id'))
                elif action=='citation' and set(query)=={'ref'}: value = store.citation(cid,query['ref'])
                else: raise AccessDenied('Unsupported query parameters')
                self.send_data(200,value)
            except AccessDenied as error: self.send_data(403,{'error':str(error)})
            except FileNotFoundError: self.send_data(404,{'error':'Review data or route not found'})
            except (ValueError,TypeError): self.send_data(400,{'error':'Invalid request or unreadable review data'})
            except (OSError,KeyError): self.send_data(500,{'error':'Review data could not be loaded'})

        def do_POST(self):
            if self.path in ('/api/feedback','/api/feedback/events'):return self.save_feedback()
            if not allow_live_analysis and self.path in ('/api/policy/interpret','/api/policy/review'):
                return self.send_data(409,{'error':'Live analysis is disabled. This demo uses frozen, previously validated results.'})
            cancel_match=re.fullmatch(r'/api/policy/reviews/([a-f0-9]{32})/cancel',self.path)
            if self.path not in ('/api/policy/interpret','/api/policy/review','/api/rubric/pdf') and not cancel_match:
                return self.send_data(405,{'error':'Only policy interpretation accepts requests; evidence is read-only'})
            hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            origin='http://'+self.headers.get('Host','')
            if (self.headers.get('Host') not in hosts or self.headers.get('Origin')!=origin
                or self.headers.get('X-ProductOps-Request')!='policy'):
                return self.send_data(403,{'error':'Local same-origin policy requests only'})
            if self.path=='/api/rubric/pdf':
                return self.import_rubric_pdf()
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                return self.send_data(415,{'error':'A JSON policy request is required'})
            from .policy_reader import read_policy, policy_text, PolicyError
            from .decision_rubric import RubricError
            from .openai_provider import ProviderError
            from .spend import BudgetExceeded
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=125000 or self.headers.get('Transfer-Encoding'):
                    return self.send_data(413,{'error':'Policy request exceeds the size limit'})
                self.connection.settimeout(10)
                data=json.loads(self.rfile.read(length))
                if self.path=='/api/policy/review':
                    if not isinstance(data,dict) or set(data)!={'interpretation_id','request_id'}:
                        return self.send_data(400,{'error':'Provide interpretation_id and request_id'})
                    return self.send_data(202,reviews.start(data['interpretation_id'],data['request_id']))
                if cancel_match:
                    if data!={}:return self.send_data(400,{'error':'Cancellation takes no extra fields'})
                    return self.send_data(200,reviews.cancel(cancel_match.group(1)))
                if not isinstance(data,dict) or 'policy_text' not in data or set(data)-{'policy_text','analysis_mode'}:
                    return self.send_data(400,{'error':'Provide policy_text and optionally analysis_mode'})
                from .analysis_models import profile
                selected=profile(data.get('analysis_mode','cost'))
                text=policy_text(data['policy_text'])
                reader=policy_reader or read_policy
                interpreted=reader(text) if selected['mode']=='cost' else reader(text,analysis_mode=selected['mode'])
                self.send_data(200,reviews.register(dict(interpreted,analysis_mode=selected['mode']),text))
            except (PolicyError,RubricError) as error: self.send_data(422,{'error':str(error)})
            except ReviewError as error: self.send_data(409,{'error':str(error)})
            except AccessDenied as error:self.send_data(403,{'error':str(error)})
            except BudgetExceeded as error: self.send_data(429,{'error':str(error)})
            except ProviderError as error: self.send_data(502,{'error':str(error)})
            except (ValueError,TypeError,UnicodeError): self.send_data(400,{'error':'Invalid policy request'})
            except (OSError,KeyError): self.send_data(500,{'error':'The policy could not be read; the current rule has not changed'})

        def save_feedback(self):
            if (not self.same_origin(require_origin=True)
                or self.headers.get('X-ProductOps-Request')!='feedback'):
                return self.send_data(403,{'error':'Same-origin feedback requests only'})
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':return self.send_data(415,{'error':'Feedback must be JSON'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000 or self.headers.get('Transfer-Encoding'):return self.send_data(413,{'error':'Feedback exceeds the size limit'})
                self.connection.settimeout(10)
                data=json.loads(self.rfile.read(size));ip=self.visitor_ip()
                result=feedback.submit(data,ip) if self.path=='/api/feedback' else feedback.event(data,ip)
                self.send_data(201,result)
            except AccessDenied as error:self.send_data(403,{'error':str(error)})
            except (ValueError,TypeError,UnicodeError) as error:self.send_data(400,{'error':str(error) if isinstance(error,FeedbackError) else 'Invalid feedback request'})
            except (OSError,KeyError):self.send_data(500,{'error':'Feedback could not be saved. Try again.'})

        def import_rubric_pdf(self):
            from .rubric_pdf import extract_rubric_pdf, RubricPDFError, MAX_PDF_BYTES
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/pdf':
                return self.send_data(415,{'error':'Choose a PDF file.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_PDF_BYTES or self.headers.get('Transfer-Encoding'):
                    return self.send_data(413,{'error':'Choose a PDF no larger than 5 MB.'})
                self.connection.settimeout(10)
                self.send_data(200,extract_rubric_pdf(self.rfile.read(length)))
            except RubricPDFError as error:
                self.send_data(422,{'error':str(error)})
            except (ValueError,OSError):
                self.send_data(400,{'error':'The PDF upload could not be read. Try again.'})

    return ThreadingHTTPServer((host,port),Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local InsightBridge review UI with opt-in policy interpretation')
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765')))
    parser.add_argument('--host',default='127.0.0.1')
    args=parser.parse_args(argv)
    hostname=os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    data_dir=os.environ.get('INSIGHTBRIDGE_DATA_DIR')
    from .feedback import FeedbackStore
    feedback=FeedbackStore(Path(data_dir)/'feedback') if data_dir else None
    server = make_server(args.port,host=args.host,feedback_store=feedback,
                         public_origin='https://'+hostname if hostname else None,
                         trust_proxy=bool(hostname and os.environ.get('RENDER')=='true'))
    print(f'InsightBridge listening on {args.host}:{server.server_port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
