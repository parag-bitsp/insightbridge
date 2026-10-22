"""Small explicit JSON contract shared by provider schema and local validation."""
import math
from .evidence import SOURCES


def obj(**properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def array(items, maximum=20):
    return dict(type='array',items=items,maxItems=maximum)


TEXT = dict(type='string',minLength=1,maxLength=2000)
REFS = array(dict(type='string',minLength=1,maxLength=120))
STRINGS = array(TEXT,10)
RESULT_SCHEMA = obj(
    issue_summary=TEXT,
    impact=obj(rating=dict(type='string',enum=['Low','Medium','High','Needs review']),rationale=TEXT,evidence_refs=REFS),
    metric_claims=array(obj(key=dict(type='string'),value=dict(type=['number','null'])),60),
    findings=array(obj(id=TEXT,kind=dict(type='string',enum=['report','observation','hypothesis']),text=TEXT,evidence_refs=REFS),12),
    alternatives=array(obj(explanation=TEXT,support_refs=REFS,counter_refs=REFS,gaps=STRINGS),5),
    gaps=STRINGS,
    decision=dict(type='string',enum=['recommend_actions','withhold_intervention']),
    withholding_reason=dict(type=['string','null']),
    recommendations=array(obj(id=TEXT,action_type=dict(type='string',enum=['diagnostic','pilot_preparation','source_quality']),
        action=TEXT,scope=TEXT,owner=TEXT,execution_priority=dict(type='string',enum=['Urgent','High','Moderate','Low']),
        priority_reason=TEXT,rationale=TEXT,finding_ids=array(TEXT,12),expected_outcome=TEXT,
        evaluation_measures=STRINGS,guardrails=STRINGS,uncertainties=STRINGS,authorization_boundary=TEXT,
        remaining_question=TEXT,human_work_reason=dict(type='string',enum=['unavailable_evidence','external_expertise','intervention_design']),
        required_sources=array(dict(type='string',enum=list(SOURCES)),12),expertise_or_access_needed=TEXT,gap_refs=REFS),4))
RESULT_SCHEMA['properties']['decision']['description']='Withhold only when proposing no human work. Any diagnostic or other action uses recommend_actions.'
RESULT_SCHEMA['properties']['recommendations']['description']='Empty when decision is withhold_intervention. Otherwise only justified independent human work.'


class ContractError(ValueError):
    pass


def validate_shape(value,schema,path='output'):
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:
                validate_shape(value,option,path)
                return
            except ContractError:pass
        raise ContractError(path+': no allowed schema matched')
    types=schema['type'] if isinstance(schema['type'],list) else [schema['type']]
    actual=('null' if value is None else 'boolean' if type(value) is bool else
            'integer' if type(value) is int else 'number' if type(value) is float else
            'string' if isinstance(value,str) else 'array' if isinstance(value,list) else
            'object' if isinstance(value,dict) else 'unsupported')
    if actual not in types and not (actual=='integer' and 'number' in types):
        raise ContractError(path+': invalid type')
    if actual=='null': return
    if actual=='number' and not math.isfinite(value): raise ContractError(path+': non-finite number')
    if 'enum' in schema and value not in schema['enum']: raise ContractError(path+': unsupported value')
    if actual in ('integer','number'):
        if value<schema.get('minimum',value) or value>schema.get('maximum',value):
            raise ContractError(path+': outside permitted range')
    if actual=='string' and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',len(value)):
        raise ContractError(path+': invalid length')
    if actual=='object':
        if set(value)!=set(schema['required']): raise ContractError(path+': missing or extra fields')
        for key,child in value.items(): validate_shape(child,schema['properties'][key],path+'.'+key)
    if actual=='array':
        if len(value)>schema.get('maxItems',len(value)): raise ContractError(path+': too many items')
        for index,child in enumerate(value): validate_shape(child,schema['items'],path+f'[{index}]')


def validate_result(value,tools):
    validate_shape(value,RESULT_SCHEMA)
    triage=getattr(tools,'triage',None)
    if triage:
        if triage['outcome']=='action_required' and value['decision']!='recommend_actions':
            raise ContractError('Output contradicts the approved triage policy: action required')
        if (triage['outcome']=='below_threshold' and value['impact']['rating'] in ('Low','Medium') and
            value['decision']!='withhold_intervention'):
            raise ContractError('Output contradicts the approved triage policy: close routine review below threshold')
        if (triage['outcome']=='below_threshold' and value['impact']['rating'] in ('High','Needs review') and
            value['decision']=='withhold_intervention'):
            raise ContractError('Output contradicts the approved triage policy: serious or unknown consequences need separate review')
        if triage['outcome']=='needs_review' and value['decision']=='withhold_intervention':
            raise ContractError('Output contradicts the approved triage policy: denominator needs review')
    claims=set()
    for claim in value['metric_claims']:
        key=claim['key']
        if key in claims or key not in tools.baseline['metrics'] or claim['value']!=tools.baseline['metrics'][key]:
            raise ContractError('Metric claim does not match deterministic measures')
        claims.add(key)
    if not claims or not value['findings']: raise ContractError('Measures and findings are required')
    findings={f['id'] for f in value['findings']}
    if len(findings)!=len(value['findings']): raise ContractError('Duplicate finding IDs')
    rec_ids=[r['id'] for r in value['recommendations']]
    if len(rec_ids)!=len(set(rec_ids)): raise ContractError('Duplicate recommendation IDs')
    work_units=set()
    for rec in value['recommendations']:
        if not rec['finding_ids'] or not set(rec['finding_ids'])<=findings:
            raise ContractError('Recommendation must reference existing findings')
        if not rec['evaluation_measures'] or not rec['guardrails']:
            raise ContractError('Recommendation requires measures and guardrails')
        if tools.unread_preparation_sources():
            raise ContractError('Relevant available evidence remains unread; finish permitted research first')
        if not rec['required_sources']: raise ContractError('Recommendation must name its required sources')
        unavailable=[source for source in rec['required_sources'] if tools.baseline['coverage'][source]['status']!='available']
        for source in rec['required_sources']:
            c=tools.baseline['coverage'][source]
            if c['status']=='available' and c['raw_rows'] and not tools.raw_reads[source]:
                raise ContractError('Recommendation leaves available required evidence unread: '+source)
        if rec['human_work_reason']=='unavailable_evidence' and not unavailable:
            raise ContractError('Recommendation '+rec['id']+': required evidence is available; unavailable_evidence is invalid. Tools can inspect those records. Human work must require distinct expertise, physical review or intervention design.')
        if (rec['action_type']=='pilot_preparation')!=(rec['human_work_reason']=='intervention_design'):
            raise ContractError('Intervention design applies only to pilot preparation')
        if not set(rec['gap_refs'])<=tools.observed_gap_refs:
            raise ContractError('Recommendation cites an unobserved gap')
        if rec['action_type']=='source_quality' and not rec['gap_refs']:
            raise ContractError('Source-quality work needs an observed gap, not a generic validation task')
        unit=(rec['action_type'],rec['owner'].casefold(), ' '.join(rec['remaining_question'].casefold().split()),
              tuple(sorted(rec['required_sources'])))
        if unit in work_units: raise ContractError('Duplicate recommendation work unit')
        work_units.add(unit)
    if value['decision']=='recommend_actions':
        if not value['recommendations'] or value['withholding_reason'] is not None:
            raise ContractError('Action decision must contain recommendations')
    elif value['recommendations'] or not value['withholding_reason']:
        raise ContractError('Withholding needs a reason and no proposed intervention')
    def walk(node):
        if isinstance(node,dict):
            for key,child in node.items():
                if key in ('evidence_refs','support_refs','counter_refs','gap_refs'):
                    if any(ref not in tools.exposed_refs for ref in child):
                        raise ContractError('Citation was not exposed through permitted evidence')
                else: walk(child)
        elif isinstance(node,list):
            for child in node: walk(child)
    walk(value)
    if not value['impact']['evidence_refs'] or any(not f['evidence_refs'] for f in value['findings']):
        raise ContractError('Impact and findings require evidence references')
