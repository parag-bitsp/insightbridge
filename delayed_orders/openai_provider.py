"""Stdlib Responses transport. Credentials never enter model input or run artifacts."""
import json
import os
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from .analysis_models import ASTRA_MODEL


class ProviderError(RuntimeError):
    pass


def load_api_key(env_path):
    key=os.environ.get('OPENAI_API_KEY','').strip()
    if not key and env_path.is_file():
        for line in env_path.read_text(encoding='utf-8-sig').splitlines():
            name,sep,value=line.strip().partition('=')
            if sep and name.strip()=='OPENAI_API_KEY':
                key=value.strip().strip('\"\'')
                break
    if not key:
        raise ProviderError('OPENAI_API_KEY is empty; fill it in locally in .env or the environment.')
    if any(c.isspace() for c in key): raise ProviderError('OPENAI_API_KEY has invalid whitespace.')
    return key


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def _http(endpoint,payload,key):
    suffix='responses/input_tokens' if endpoint=='input_tokens' else 'responses'
    request=Request('https://api.openai.com/v1/'+suffix,data=json.dumps(payload).encode('utf-8'),
                    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with build_opener(_NoRedirect).open(request,timeout=120 if payload.get('model')==ASTRA_MODEL else 45) as response:
            data=response.read(1_000_001)
        if len(data)>1_000_000: raise ProviderError('Provider response exceeds the size limit.')
        return json.loads(data)
    except HTTPError as error:
        raise ProviderError('OpenAI HTTP '+str(error.code)+'; no automatic retry was made.') from None
    except (URLError,TimeoutError,OSError,ValueError):
        raise ProviderError('OpenAI transport or JSON failure; no automatic retry was made.') from None


class OpenAIProvider:
    def __init__(self,key,transport=None):
        self._key=key
        self._transport=transport or _http

    def count_input(self,payload):
        allowed=('model','input','instructions','tools','text','tool_choice','truncation')
        counted=self._transport('input_tokens',{k:v for k,v in payload.items() if k in allowed},self._key)
        if not isinstance(counted,dict): raise ProviderError('Invalid provider token-count envelope.')
        value=counted.get('input_tokens')
        if type(value) is not int or value<0: raise ProviderError('Provider input-token count is missing or invalid.')
        return value

    def respond(self,payload):
        return self._transport('responses',payload,self._key)
