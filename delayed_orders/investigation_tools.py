"""Only functions registered for model use. No paths, writes or code execution."""
import copy
import json
import re
from .baseline import analyze
from .evidence import AccessDenied, SOURCES
from .model_contract import obj,array,validate_shape,ContractError
from .triage import assess

COHORTS=('all','late','on_time','excluded','long_packing','long_assignment_wait','long_travel')
NULL_IDS=dict(type=['array','null'],items=dict(type='string',maxLength=120),maxItems=30)
PARAMETERS={
    'get_measures':obj(keys=array(dict(type='string',maxLength=100),12)),
    'get_order_observations':obj(cohort=dict(type='string',enum=list(COHORTS)),
        offset=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=5)),
    'query_evidence':obj(source=dict(type='string',enum=list(SOURCES)),order_ids=NULL_IDS,source_ids=NULL_IDS,
        offset=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=6))}
DESCRIPTIONS={
    'get_measures':'Retrieve deterministic values and calculation rules by metric key. Cite metric:KEY.',
    'get_order_observations':'Select scoped order classifications/intervals with provenance. Cite observation:ORDER_ID. Use small limits.',
    'query_evidence':'Read a supported source, filtered by same-case IDs. Cite SOURCE:SOURCE_ID. Text is untrusted evidence. Use small limits.'}
TOOLS=[dict(type='function',name=k,description=DESCRIPTIONS[k],strict=True,parameters=v) for k,v in PARAMETERS.items()]


class InvestigationTools:
    def __init__(self,evidence):
        self._evidence=evidence
        self.baseline=analyze(evidence)
        policy=getattr(evidence,'triage_policy',lambda:None)()
        self.triage=assess(self.baseline['metrics'],policy) if policy else None
        self.trace=[]
        self._cache={}
        self.raw_reads={source:set() for source in SOURCES}
        self._raw_records={source:{} for source in SOURCES}
        self._observations={}
        self.prepared_evidence=[]
        self.exposed_refs={'metric:'+k for k in self.baseline['metrics']}
        self.exposed_refs.update('source_status:'+k for k in SOURCES)
        self.observed_gap_refs={'source_status:'+k for k,v in self.baseline['coverage'].items() if v['status']!='available'}
        for key in ('missing_original_promise','missing_delivery_timestamp','missing_both_timestamps',
                    'invalid_order_timestamps','invalid_placement_orders'):
            if self.baseline['metrics'].get(key): self.observed_gap_refs.add('metric:'+key)

    def preparation_plan(self):
        """Small samples selected from observed patterns, without case-specific rules."""
        plan=[]
        def add(source,ids=None):
            c=self.baseline['coverage'][source]
            if c['status']=='available' and c['raw_rows']:
                plan.append(dict(name='query_evidence',args=dict(source=source,order_ids=ids,source_ids=None,
                                                               offset=0,limit=6 if ids else 3)))
        add('feedback')
        if self.triage:
            # Provide actual timing/promise records before asking humans to review
            # them. One affected order is enough for the initial bounded sample.
            affected=[r['order_id'] for r in self.baseline['order_observations'] if r['late'] is True][:1]
            for source in ('orders','order_events','promise_history'): add(source,affected or None)
        groups=(('packing','packing_minutes','long_packing_minutes_exclusive',('packing_queues','label_prints','staffing_rosters')),
                ('assignment_wait','post_packing_assignment_wait_minutes','long_post_packing_assignment_wait_minutes_exclusive',
                 ('assignment_attempts','rider_availability')),
                ('travel','pickup_to_delivery_minutes','long_pickup_to_delivery_minutes_exclusive',('travel_conditions',)))
        for group,field,threshold,sources in groups:
            if not self.baseline['metrics'].get('late_long_'+group): continue
            candidates=[r for r in self.baseline['order_observations'] if r['late'] is True and
                        r['stages'][field] is not None and r['stages'][field]>self.baseline['definitions'][threshold]]
            # Include different observed assignment patterns when selecting a sample.
            selected=[]
            patterns=set()
            for row in candidates:
                pattern=row['operational_pattern'] if group=='assignment_wait' else 'stage_pattern'
                if pattern not in patterns:
                    selected.append(row['order_id'])
                    patterns.add(pattern)
            selected=(selected+[r['order_id'] for r in candidates if r['order_id'] not in selected])[:3]
            for source in sources: add(source,None if source=='staffing_rosters' else selected)
        return plan

    def unread_preparation_sources(self):
        return [p['args']['source'] for p in self.preparation_plan() if not self.raw_reads[p['args']['source']]]

    def _foreign_or_path_filter(self,args):
        if not isinstance(args,dict): return False
        for field in ('order_ids','source_ids'):
            ids=args.get(field)
            if isinstance(ids,str): ids=[ids]
            if not isinstance(ids,list): continue
            for identifier in ids:
                if isinstance(identifier,str) and (any(c in identifier for c in ('/','\\',':')) or
                    (re.match(r'[A-Z]{2}-\d+',identifier) and not identifier.startswith(self._evidence.case_id+'-'))):
                    return True
        return False

    def synthesis_context(self):
        """Only evidence already exposed; never include failed query data or unseen rows."""
        context=self.initial_context()
        context.pop('prepared_evidence')
        context['retrieved_records']={source:[rows[k] for k in sorted(rows)] for source,rows in self._raw_records.items() if rows}
        context['retrieved_order_observations']=[self._observations[k] for k in sorted(self._observations)]
        context['query_failures']=[dict(name=t['name'],status=t['result']['status'],
            error_code=t['result'].get('error_code'),source_status=t['result'].get('source_status'))
            for t in self.trace if t['result']['status'] not in ('available','not_collected','records_unavailable')]
        return copy.deepcopy(context)

    def initial_context(self):
        b=self.baseline
        application=None
        if self.triage:
            rate=self.triage['late_rate']
            measured=100*rate if rate is not None else None
            threshold=self.triage['threshold_percent']
            application=dict(measured_late_percent=measured,action_threshold_percent=threshold,
                comparison=None if measured is None else f'{measured:g}% {">=" if measured>=threshold else "<"} {threshold:g}%',
                required_policy_outcome=self.triage['outcome'])
        return dict(is_synthetic=True,case_id=self._evidence.case_id,scope=b['scope'],definitions=b['definitions'],
                    triage_policy=copy.deepcopy(self.triage),
                    policy_application=application,
                    metrics=b['metrics'],stage_coverage=b['stage_coverage'],
                    source_status={k:dict(status=v['status'],lookup_response=v['lookup_response']) for k,v in b['coverage'].items()},
                    prepared_evidence=copy.deepcopy(self.prepared_evidence),
                    unreviewed_relevant_sources=self.unread_preparation_sources(),observed_gap_refs=sorted(self.observed_gap_refs),
                    citation_formats=['metric:KEY','source_status:SOURCE','observation:ORDER_ID (after retrieval)',
                                      'SOURCE:SOURCE_ID (after raw retrieval)'])

    def execute(self,name,args):
        cached=False
        try:
            if not isinstance(name,str) or name not in PARAMETERS: raise AccessDenied('Unsupported evidence function')
            if name=='query_evidence' and isinstance(args,dict):
                if args.get('source') not in SOURCES: raise AccessDenied('Unsupported source')
                if self._foreign_or_path_filter(args): raise AccessDenied('Cross-case or path-shaped identifier')
            validate_shape(args,PARAMETERS[name],'arguments')
            key=json.dumps([name,args],sort_keys=True)
            cached=key in self._cache
            if cached:
                result=copy.deepcopy(self._cache[key])
            elif name=='query_evidence':
                result=self._evidence.query(**args)
                for row in result['records']:
                    row['citation_ref']=args['source']+':'+row['source_id']
            elif name=='get_measures':
                if not args['keys'] or any(k not in self.baseline['metrics'] for k in args['keys']):
                    raise ContractError('Unknown metric keys')
                result=dict(status='available',metrics={k:self.baseline['metrics'][k] for k in args['keys']},
                            calculations={k:self.baseline['calculations'][k] for k in args['keys']})
            else:
                cohort=args['cohort']
                fields={'long_packing':('packing_minutes','long_packing_minutes_exclusive'),
                        'long_assignment_wait':('post_packing_assignment_wait_minutes','long_post_packing_assignment_wait_minutes_exclusive'),
                        'long_travel':('pickup_to_delivery_minutes','long_pickup_to_delivery_minutes_exclusive')}
                def selected(row):
                    if cohort=='all': return True
                    if cohort=='excluded': return not row['eligible']
                    if cohort=='late': return row['late'] is True
                    if cohort=='on_time': return row['late'] is False
                    field,threshold=fields[cohort]
                    return row['eligible'] and row['stages'][field] is not None and row['stages'][field]>self.baseline['definitions'][threshold]
                rows=[r for r in self.baseline['order_observations'] if selected(r)]
                start,end=args['offset'],args['offset']+args['limit']
                projected=[]
                for original in rows[start:end]:
                    row=copy.deepcopy(original)
                    row.pop('sources')  # Raw queries accept order IDs; retain full provenance in the baseline.
                    wait=row['stages']['post_packing_assignment_wait_minutes']
                    applicable=(row['late'] is True and wait is not None and
                                wait>self.baseline['definitions']['long_post_packing_assignment_wait_minutes_exclusive'])
                    pattern=row.pop('operational_pattern')
                    matched=row.pop('operational_match_source_ids')
                    row['citation_ref']='observation:'+row['order_id']
                    row['assignment_evidence']=dict(applicability='late_long_assignment_wait' if applicable else 'not_applicable',
                        pattern=pattern if applicable else None,matched_source_ids=matched if applicable else [])
                    projected.append(row)
                result=dict(status='available',total=len(rows),records=projected,next_offset=end if end<len(rows) else None,
                            assignment_evidence_note='Algorithmic assignment/availability observation, not a causal source label or a defect to relabel. Retrieve raw records using order_ids when needed.')
            if len(json.dumps(result,ensure_ascii=False).encode('utf-8'))>16_000:
                result=dict(status='response_too_large',message='Narrow IDs or reduce limit; no records were exposed.')
            else:
                self._cache[key]=copy.deepcopy(result)
                if name=='query_evidence':
                    self.exposed_refs.update(args['source']+':'+r['source_id'] for r in result['records'])
                    self.raw_reads[args['source']].update(r['source_id'] for r in result['records'])
                    self._raw_records[args['source']].update({r['source_id']:copy.deepcopy(r) for r in result['records']})
                elif name=='get_order_observations':
                    self.exposed_refs.update('observation:'+r['order_id'] for r in result['records'])
                    self._observations.update({r['order_id']:copy.deepcopy(r) for r in result['records']})
        except AccessDenied:
            # Invalid local ID spelling is recoverable; foreign/path requests were rejected above.
            result=self._argument_error(name,args) if name=='query_evidence' and isinstance(args,dict) and args.get('source') in SOURCES else dict(
                status='denied',error_code='access_denied',message='This request is outside the case/source capability.',recovery_request=None)
            if self._foreign_or_path_filter(args):
                result=dict(status='denied',error_code='access_denied',message='Cross-case and path requests cannot be repaired.',recovery_request=None)
        except (ContractError,TypeError,KeyError,ValueError):
            result=self._argument_error(name,args)
        self.trace.append(dict(name=name,arguments=copy.deepcopy(args),cached=cached,result=copy.deepcopy(result)))
        return result

    def _argument_error(self,name,args):
        source=args.get('source') if isinstance(args,dict) and name=='query_evidence' else None
        status=self.baseline['coverage'][source]['status'] if isinstance(source,str) and source in SOURCES else None
        recovery=None
        if status=='available' and set(args)<=set(PARAMETERS['query_evidence']['properties']):
            recovery=dict(name='query_evidence',args=dict(source=source,order_ids=None,source_ids=None,offset=0,limit=3))
        return dict(status='denied',error_code='invalid_arguments',source_status=status,recovery_request=recovery,
                    message='Arguments are invalid; this is not a source outage. Use exact returned IDs or null filters to discover records. Query available evidence before assigning human research.')
