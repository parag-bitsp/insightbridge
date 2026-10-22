"""Approved product rule, independent of case identities and evaluator answers."""
import math
POLICY=dict(version='delayed-delivery-15pct-v1',threshold_percent=15,
    failure_definition='Delivery after the original checkout promise',
    rate_scope='Distinct eligible orders within the selected store and placement period',
    action_rule='At or above the threshold, propose justified remedial preparation or diagnostic work.',
    closure_rule='Below threshold with completed deliveries and ordinary inconvenience, close the review with no human work.',
    exceptions='Credible serious harm or an important blocked goal requires separate review regardless of rate. Unknown consequence evidence must not be assumed harmless.',
    missingness_rule='An unknown denominator or exclusions that prevent a reliable below-threshold conclusion require review.')


def assess(metrics,policy=None):
    policy=POLICY if policy is None else policy
    threshold=policy['threshold_percent']
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=100:
        raise ValueError('Invalid policy percentage')
    eligible=metrics.get('eligible_orders');late=metrics.get('late_orders')
    exclusions=metrics.get('excluded_unique_orders')
    valid=(type(eligible) is int and type(late) is int and 0<=late<=eligible and eligible>0)
    outcome=('needs_review' if not valid else
             'action_required' if late*100>=eligible*threshold else
             'needs_review' if exclusions!=0 else 'below_threshold')
    return dict(policy,outcome=outcome,late_orders=late,eligible_orders=eligible,
                late_rate=late/eligible if valid else None)
