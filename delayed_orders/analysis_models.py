"""Allowlisted demo analysis models and published standard text-token rates."""
import copy

COST_MODEL='gpt-5.4-mini-2026-03-17'
LATENCY_MODEL='gpt-5.4-2026-03-05'
ASTRA_MODEL='gpt-6-astra'
PROFILES={
    'cost':dict(mode='cost',label='Optimize for cost',model=COST_MODEL),
    'latency':dict(mode='latency',label='Optimize for latency',model=LATENCY_MODEL),
    'astra':dict(mode='astra',label='Astra comparison',model=ASTRA_MODEL),
}
PRICES={
    COST_MODEL:dict(model=COST_MODEL,input_per_million=.75,cached_input_per_million=.075,output_per_million=4.5,
                    source='https://developers.openai.com/api/docs/models/gpt-5.4-mini'),
    LATENCY_MODEL:dict(model=LATENCY_MODEL,input_per_million=2.5,cached_input_per_million=.25,output_per_million=15,
                       source='https://developers.openai.com/api/docs/models/gpt-5.4'),
    ASTRA_MODEL:dict(model=ASTRA_MODEL,input_per_million=10,cached_input_per_million=1,cache_write_per_million=12.5,
                     reservation_input_per_million=12.5,output_per_million=50,
                     source='https://developers.openai.com/api/docs/models/gpt-6-astra'),
}


def profile(mode='cost'):
    if not isinstance(mode,str) or mode not in PROFILES:raise ValueError('Choose cost, latency or astra analysis.')
    return copy.deepcopy(PROFILES[mode])


def model_pricing(model=COST_MODEL):
    if not isinstance(model,str) or model not in PRICES:raise ValueError('Unsupported analysis model')
    return dict(copy.deepcopy(PRICES[model]),currency='USD',verified_on='2026-10-22',service_tier='default')


def request_options(model):
    model_pricing(model)
    if model==ASTRA_MODEL:
        return dict(reasoning={'effort':'low'},prompt_cache_options={'mode':'explicit','ttl':'30m'})
    return dict(reasoning={'effort':'none'})


def mode_for_model(model):
    return next((mode for mode,selected in PROFILES.items() if selected['model']==model),'cost')
