"""Deterministic calculations and observational rules, without model or reference access."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from .evidence import SOURCES, DataError

IST = timezone(timedelta(hours=5, minutes=30))


def _time(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp lacks timezone')
    return result.astimezone(IST)


def _minutes(start, end):
    return (end - start).total_seconds() / 60


def _all(evidence, name):
    response = evidence.query(name)
    metadata = {k: v for k, v in response.items() if k not in ('records', 'next_offset')}
    rows = response['records']
    while response['next_offset'] is not None:
        response = evidence.query(name, offset=response['next_offset'])
        rows.extend(response['records'])
        metadata['source_multiplicities'].update(response['source_multiplicities'])
    return rows, metadata


def _stages(order, events):
    times = {}
    gaps = []
    for event in events:
        kind = event['event_type']
        try:
            value = _time(event['occurred_at'])
        except (ValueError, TypeError):
            value = None
            gaps.append('invalid_timestamp:' + kind)
        if kind in times:
            times[kind] = None
            gaps.append('ambiguous_event:' + kind)
        else:
            times[kind] = value
    intervals = {}
    specs = (('packing_minutes', 'packing_started', 'packing_completed'),
             ('post_packing_assignment_wait_minutes', 'packing_completed', 'rider_assigned'),
             ('pickup_to_delivery_minutes', 'picked_up', 'delivered'))
    try:
        placed, delivered = _time(order['placed_at']), _time(order['delivered_at'])
    except (ValueError, TypeError):
        placed, delivered = None, None
    for kind, value in list(times.items()):
        if value and ((placed and value < placed) or (delivered and value > delivered)):
            times[kind] = None
            gaps.append('event_outside_order_timeline:' + kind)
    if (times.get('packing_started') and times.get('packing_completed') and
        times['packing_completed'] < times['packing_started']):
        # Neither timestamp is trustworthy enough for dependent wait calculations.
        times['packing_started'] = times['packing_completed'] = None
        gaps.append('negative_interval:packing_minutes')
    # Pickup must follow packing and assignment; assignment before packing is valid.
    pickup = times.get('picked_up')
    if pickup and any(times.get(k) and times[k] > pickup for k in ('packing_completed', 'rider_assigned')):
        times['picked_up'] = None
        gaps.append('invalid_pickup_chronology')
    for name, start, end in specs:
        a, b = times.get(start), times.get(end)
        if a is None or b is None:
            intervals[name] = None
            gaps.append('missing_or_invalid:' + name)
        elif name == 'post_packing_assignment_wait_minutes':
            intervals[name] = max(0, _minutes(a, b))
        elif b < a:
            intervals[name] = None
            gaps.append('negative_interval:' + name)
        else:
            intervals[name] = _minutes(a, b)
    return intervals, times, sorted(set(gaps))


def _operational(times, attempts, snapshots, max_age):
    """Match a snapshot to an attempt within the observed packing/assignment wait.

    Both the underlying snapshot and its check must precede the attempt and be
    at most max_age minutes old. Mere nearby presence never implies eligibility.
    """
    pairs, issues = [], []
    packed, assigned = times.get('packing_completed'), times.get('rider_assigned')
    for attempt in attempts:
        try:
            at, resolved = _time(attempt['attempted_at']), _time(attempt['resolved_at'])
            if not at or not resolved or resolved < at:
                raise ValueError('Invalid attempt chronology')
        except (ValueError, TypeError):
            issues.append('invalid_assignment_attempt:' + attempt['source_id'])
            continue
        if not packed or not assigned or not packed <= at <= resolved <= assigned:
            continue
        for snapshot in snapshots:
            try:
                checked, taken = _time(snapshot['checked_at']), _time(snapshot['snapshot_at'])
                valid = (checked is not None and taken is not None and
                         0 <= _minutes(taken, checked) <= max_age and
                         0 <= _minutes(taken, at) <= max_age and
                         packed <= checked <= at)
            except (ValueError, TypeError):
                valid = False
            if valid:
                pairs.append((attempt, snapshot))
    zero = any(s.get('eligible_nearby_riders') == 0 for a, s in pairs)
    expiry = any(a.get('outcome') == 'expired' and isinstance(s.get('eligible_nearby_riders'), int)
                 and s['eligible_nearby_riders'] > 0 for a, s in pairs)
    pattern = 'mixed' if zero and expiry else 'no_eligible_nearby_rider' if zero else (
        'expired_attempts_with_recorded_availability' if expiry else 'unclassified' if pairs else 'incomplete')
    return pattern, sorted({r['source_id'] for pair in pairs for r in pair}), issues


def analyze(evidence):
    request = evidence.request()
    scope, definitions = request['scope'], request['definitions']
    if scope['timezone'] not in ('Asia/Kolkata', 'Asia/Calcutta'):
        raise DataError('This baseline supports IST scope only')
    tables, coverage = {}, {}
    for name in SOURCES:
        tables[name], coverage[name] = _all(evidence, name)
    if coverage['orders']['status'] != 'available':
        raise DataError('Orders are required for a deterministic denominator')
    metrics, calculations = {}, {}

    def metric(key, value, rule, *inputs):
        metrics[key] = value
        calculations[key] = dict(rule=rule, inputs=['request.json'] + [n + '.jsonl' for n in inputs],
                                 observation_selector=key)

    scoped, unscoped, invalid_scope = [], [], []
    for order in tables['orders']:
        try:
            placed = _time(order['placed_at'])
            if placed is None:
                raise ValueError('Missing placement')
        except (ValueError, TypeError):
            invalid_scope.append(order['source_id'])
            continue
        if (order['store_id'] in scope['store_ids'] and
            scope['placement_date_start'] <= placed.date().isoformat() <= scope['placement_date_end_inclusive'] and
            scope['placement_time_start_inclusive'] <= placed.time().isoformat() < scope['placement_time_end_exclusive']):
            scoped.append(order)
        else:
            unscoped.append(order['source_id'])
    scoped_ids = {r['order_id'] for r in scoped}
    metric('raw_order_rows', coverage['orders']['raw_rows'], 'All imported order rows before exact-source deduplication/scope', 'orders')
    metric('duplicate_order_rows', coverage['orders']['duplicate_rows'], 'Exact repeated source imports', 'orders')
    metric('scoped_unique_orders', len(scoped), 'Distinct order IDs matching store and placement window in IST', 'orders')
    metric('unique_completed_orders', sum(o['status']=='completed' for o in scoped), 'Scoped unique completed-status orders, including exclusions', 'orders')
    metric('out_of_scope_orders', len(unscoped), 'Valid placement outside requested store/date/time', 'orders')
    metric('invalid_placement_orders', len(invalid_scope), 'Placement cannot be interpreted; scope unknown', 'orders')
    by_order = {}
    for name in SOURCES:
        grouped = defaultdict(list)
        for row in tables[name]:
            grouped[row.get('order_id')].append(row)
        by_order[name] = grouped
    exclusions = defaultdict(list)
    observations, eligible, late = [], set(), set()
    stage_sets = {name: set() for name in ('packing', 'assignment_wait', 'travel')}
    operational = defaultdict(set)
    for order in scoped:
        oid = order['order_id']
        reason = None
        promise, delivered = None, None
        if order['status'] != 'completed':
            reason = 'non_completed_orders'
        elif order['original_promised_latest_at'] is None and order['delivered_at'] is None:
            reason = 'missing_both_timestamps'
        elif order['original_promised_latest_at'] is None:
            reason = 'missing_original_promise'
        elif order['delivered_at'] is None:
            reason = 'missing_delivery_timestamp'
        else:
            try:
                promise, delivered = _time(order['original_promised_latest_at']), _time(order['delivered_at'])
                if min(promise, delivered) < _time(order['placed_at']):
                    raise ValueError('Promise/delivery before placement')
            except (ValueError, TypeError):
                reason = 'invalid_order_timestamps'
        is_late = None if reason else delivered > promise
        if reason:
            exclusions[reason].append(oid)
        else:
            eligible.add(oid)
            if is_late:
                late.add(oid)
        stages, times, gaps = _stages(order, by_order['order_events'][oid])
        for group, field, threshold in (
            ('packing','packing_minutes','long_packing_minutes_exclusive'),
            ('assignment_wait','post_packing_assignment_wait_minutes','long_post_packing_assignment_wait_minutes_exclusive'),
            ('travel','pickup_to_delivery_minutes','long_pickup_to_delivery_minutes_exclusive')):
            if oid in eligible and stages[field] is not None and stages[field] > definitions[threshold]:
                stage_sets[group].add(oid)
        pattern, matched_ids, op_issues = _operational(times, by_order['assignment_attempts'][oid],
            by_order['rider_availability'][oid], definitions['availability_max_snapshot_age_minutes'])
        if oid in late and oid in stage_sets['assignment_wait']:
            operational[pattern].add(oid)
        gaps.extend(op_issues)
        sources = {name: [r['source_id'] for r in by_order[name][oid]] for name in SOURCES if by_order[name][oid]}
        observations.append(dict(order_id=oid, eligible=reason is None, exclusion=reason, late=is_late,
            stages=stages, operational_pattern=pattern, operational_match_source_ids=matched_ids,
            gaps=sorted(set(gaps)), sources=sources))
    for reason in ('non_completed_orders','missing_both_timestamps','missing_original_promise',
                   'missing_delivery_timestamp','invalid_order_timestamps'):
        metric(reason,len(exclusions[reason]),'Disjoint eligibility exclusion; see exclusion_order_ids', 'orders')
    metric('excluded_unique_orders',len(scoped)-len(eligible),'Sum of disjoint eligibility exclusions', 'orders')
    metric('eligible_orders',len(eligible),'Scoped completed unique orders with valid original promise and delivery', 'orders')
    metric('late_orders',len(late),'Eligible orders delivered strictly after original checkout promise', 'orders')
    metric('late_rate',len(late)/len(eligible) if eligible else None,'late_orders / eligible_orders; null for empty denominator', 'orders')
    revised_late, latest_comparable = [], []
    for o in scoped:
        if o['order_id'] in eligible:
            try:
                latest = _time(o.get('latest_promised_latest_at'))
                if latest is not None and latest >= _time(o['placed_at']):
                    latest_comparable.append(o['order_id'])
                else:
                    continue
                if latest is not None and _time(o['delivered_at']) > latest:
                    revised_late.append(o['order_id'])
            except (ValueError, TypeError):
                pass
    metric('latest_promise_comparable_orders',len(latest_comparable),'Eligible orders with valid latest promise; denominator of separate ETA comparison', 'orders')
    metric('late_against_latest_promise',len(revised_late) if latest_comparable else None,
           'Separate latest-ETA comparison among latest_promise_comparable_orders; never replaces original lateness', 'orders')
    stage_coverage = {}
    for group, ids in stage_sets.items():
        field = {'packing':'packing_minutes','assignment_wait':'post_packing_assignment_wait_minutes',
                 'travel':'pickup_to_delivery_minutes'}[group]
        measured = {o['order_id'] for o in observations if o['stages'][field] is not None}
        stage_coverage[group] = dict(scoped_measured_orders=len(measured), scoped_missing_orders=len(scoped_ids-measured),
            eligible_measured_orders=len(measured & eligible), eligible_missing_orders=len(eligible-measured),
            late_measured_orders=len(measured & late), late_missing_orders=len(late-measured),
            units='minutes', source='order_events', denominator_scope='eligible orders unless marked scoped')
        # A missing stage source leaves this measure unknown, not zero.
        available = coverage['order_events']['status'] == 'available'
        for prefix, selected in (('late',ids & late),('on_time',ids & (eligible-late)),('all',ids)):
            denominator = measured & (late if prefix=='late' else eligible-late if prefix=='on_time' else eligible)
            metric(prefix+'_long_'+group,len(selected) if available and denominator else None,
                   'Eligible '+prefix+' orders above exclusive request threshold; unknown intervals do not qualify', 'orders','order_events')
    observed = set().union(*stage_sets.values())
    metric('late_other',len(late-observed),'Late orders without any observed above-threshold stage; not a causal explanation', 'orders','order_events')
    op_available = (all(coverage[n]['status']=='available' for n in
                       ('order_events','assignment_attempts','rider_availability')) and
                    metrics['late_long_assignment_wait'] is not None)
    for key in ('no_eligible_nearby_rider','expired_attempts_with_recorded_availability'):
        metric(key,len(operational[key]) if op_available else None,
               'Late long-wait orders with exclusive matched operational pattern; freshness/alignment required',
               'orders','order_events','assignment_attempts','rider_availability')
    complete = set().union(*(v for k,v in operational.items() if k!='incomplete'))
    for key, value in (('complete_operational_logs',len(complete)),
                       ('incomplete_operational_logs',len(operational['incomplete']))):
        metric(key,value if op_available else None,'Late long-wait orders with/without temporally matched attempt and availability evidence',
               'orders','order_events','assignment_attempts','rider_availability')

    feedback = tables['feedback']
    raw_feedback = coverage['feedback']['raw_rows']
    support = [r for r in feedback if r.get('channel','').startswith('support_') and r.get('order_id') in scoped_ids]
    anonymous = [r for r in feedback if r.get('order_id') is None and r.get('customer_id') is None]
    contacted = {r['order_id'] for r in support}
    # Distinct text is never a dedup key; preserve every distinct contact source ID.
    multiplicities = coverage['feedback']['source_multiplicities']
    duplicate_support = sum(multiplicities[r['source_id']]-1 for r in support)
    values = dict(raw_feedback_rows=raw_feedback, distinct_feedback_records=len(feedback),
        raw_support_rows=len(support)+duplicate_support, support_contacts=len(support),
        duplicate_support_rows=duplicate_support, contacted_unique_orders=len(contacted),
        contacted_late_orders=len(contacted & late), anonymous_reviews=len(anonymous),
        follow_up_contacts=sum(r.get('message_kind')=='follow_up' for r in support),
        contacts_per_contacted_order=len(support)/len(contacted) if contacted else None)
    for key,value in values.items():
        metric(key,value if coverage['feedback']['status']=='available' else None,
               'Source-ID deduplication; support contacts linked to scoped orders; anonymous rows stay unlinked; ratio uses distinct contacted orders', 'orders','feedback')

    for name in SOURCES:
        rows = tables[name]
        available = coverage[name]['status']=='available'
        coverage[name]['scoped_linked_orders'] = len({r['order_id'] for r in rows if r.get('order_id') in scoped_ids}) if available else None
        coverage[name]['eligible_linked_orders'] = len({r['order_id'] for r in rows if r.get('order_id') in eligible}) if available else None
        coverage[name]['late_linked_orders'] = len({r['order_id'] for r in rows if r.get('order_id') in late}) if available else None
        coverage[name].pop('source_multiplicities')
    snapshot_observations = []
    for snapshot in tables['rider_availability']:
        age = None
        try:
            checked, taken = _time(snapshot['checked_at']), _time(snapshot['snapshot_at'])
            age = _minutes(taken, checked)
            freshness = 'future_snapshot' if age < 0 else (
                'fresh' if age <= definitions['availability_max_snapshot_age_minutes'] else 'stale')
        except (ValueError, TypeError):
            freshness = 'invalid_timestamp'
        snapshot_observations.append(dict(source_id=snapshot['source_id'],order_id=snapshot.get('order_id'),
            age_minutes=age,freshness=freshness,
            qualification='Freshness at check alone does not establish relevance to an assignment attempt.'))
    findings = []

    def flag(kind, message, keys):
        findings.append(dict(kind=kind, message=message, calculation_refs=keys))

    for group in stage_sets:
        key = 'late_long_'+group
        if metrics[key]:
            flag('observed_pattern', 'Long '+group.replace('_',' ')+' intervals occur among late orders. Association does not establish cause or intervention benefit.',
                 [key,'on_time_long_'+group,'all_long_'+group,'late_orders'])
    for key in ('no_eligible_nearby_rider','expired_attempts_with_recorded_availability'):
        if metrics[key]:
            flag('observed_pattern',key.replace('_',' ')+'. Matched records do not establish fleet shortage, willingness to accept or a software defect.',[key,'complete_operational_logs'])
    if metrics['late_other']:
        flag('evidence_gap','Some late orders have no observed above-threshold stage. Their explanation remains unresolved.',['late_other'])
    if metrics['excluded_unique_orders']:
        flag('evidence_gap','Excluded orders are unclassified for lateness; the eligible rate applies only to measured orders.',
             ['excluded_unique_orders','eligible_orders','late_rate'])
    if metrics['incomplete_operational_logs']:
        flag('evidence_gap','Some late long-wait orders lack temporally matched operational records.',['incomplete_operational_logs'])
    if duplicate_support or len(support)>len(contacted):
        flag('observed_pattern','Repeated contacts and exact imports do not increase unique-order reach.',
             ['raw_support_rows','support_contacts','contacted_unique_orders','duplicate_support_rows'])
    gaps = [dict(source=name,status=c['status'],lookup_response=c['lookup_response'],
                 reference='source_catalog.json#sources/'+name)
            for name,c in coverage.items() if c['status']!='available']
    return dict(baseline_version='1',is_synthetic=True,case_id=evidence.case_id,scope=scope,definitions=definitions,
        metrics=metrics,calculations=calculations,coverage=coverage,stage_coverage=stage_coverage,
        snapshot_observations=snapshot_observations,findings=findings,source_gaps=gaps,
        exclusion_order_ids=dict(exclusions),out_of_scope_source_ids=unscoped,invalid_placement_source_ids=invalid_scope,
        latest_promise_late_order_ids=revised_late,order_observations=observations,provenance=evidence.provenance(),
        limitations=['Observational synthetic baseline; no causal diagnosis, staffing prescription or benefit forecast.',
                     'No model investigation, recommendation quality evaluation, UI or external writes.',
                     'Unavailable sources and missing intervals cannot establish an observed zero.'])
