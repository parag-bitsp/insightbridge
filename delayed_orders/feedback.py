"""Local demo feedback and browser visit log. Never supplied to model calls."""
from datetime import datetime,timezone
import ipaddress
import json
from pathlib import Path
import re
import threading

from .evidence import AccessDenied

ROOT=Path(__file__).resolve().parents[1]/'feedback-data'
ID=re.compile(r'[a-f0-9]{32}')
SOURCES={'page','home','header','saved_analysis','run_mini','run_54','run_astra','recommendation','framework','customer_issues','run_trace','jira'}
MAX_LOG_BYTES=8_000_000


class FeedbackError(ValueError):pass


class FeedbackStore:
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else ROOT
        self.expected=self.root.absolute();self.lock=threading.RLock()

    def _path(self,name):
        path=self.root/name
        if self.root.resolve()!=self.expected or path.resolve()!=self.expected/name:raise AccessDenied('Redirected feedback storage')
        if path.exists() and path.stat().st_nlink!=1:raise AccessDenied('Linked feedback storage is not supported')
        return path

    def _initialize(self):
        self._path('events.jsonl');self.root.mkdir(parents=True,exist_ok=True)

    def _rows(self):
        path=self._path('events.jsonl')
        if not path.exists():return []
        if path.stat().st_size>MAX_LOG_BYTES:raise FeedbackError('Feedback log exceeds the demo size limit')
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def _validate(self,data,submission):
        common={'event_id','visitor_id','session_id','source'}
        required=common|({'rating','name','company','comment'} if submission else {'event'})
        if not isinstance(data,dict) or not required<=set(data) or set(data)-required-{'context'}:raise FeedbackError('Invalid feedback fields')
        for key in ('event_id','visitor_id','session_id'):
            if not isinstance(data[key],str) or not ID.fullmatch(data[key]):raise FeedbackError('Invalid feedback identity')
        if not isinstance(data['source'],str) or data['source'] not in SOURCES:raise FeedbackError('Invalid feedback source')
        result={key:data[key] for key in common}
        context=data.get('context',{})
        if not isinstance(context,dict) or set(context)-{'case_id','run_id','recommendation_id','choice'}:raise FeedbackError('Invalid feedback context')
        if any(not isinstance(value,str) or len(value)>120 or any(ord(c)<32 for c in value) for value in context.values()):raise FeedbackError('Invalid feedback context')
        result['context']=dict(context)
        if submission:
            if type(data['rating']) is not int or not 1<=data['rating']<=5:raise FeedbackError('Choose a rating from 1 to 5 stars.')
            for key,maximum in [('name',120),('company',160),('comment',3000)]:
                value=data[key]
                if not isinstance(value,str) or len(value)>maximum or '\x00' in value:raise FeedbackError('Feedback field exceeds its size limit')
                result[key]=value.strip()
            if not result['name']:raise FeedbackError('Enter your name.')
            result.update(event='feedback',rating=data['rating'])
        else:
            if data['event'] not in ('visit','reminder','click'):raise FeedbackError('Unsupported feedback event')
            result['event']=data['event']
        return result

    def _save(self,data,ip,submission):
        normalized=self._validate(data,submission)
        ip=str(ipaddress.ip_address(ip))
        with self.lock:
            self._initialize();rows=self._rows()
            previous=next((row for row in rows if row['event_id']==normalized['event_id']),None)
            if previous:
                if any(previous.get(key)!=value for key,value in normalized.items()):raise FeedbackError('This feedback identity has already been used.')
                return dict(status='saved',event_id=normalized['event_id'],duplicate=True)
            record=dict(normalized,schema_version=1,received_at=datetime.now(timezone.utc).isoformat(),ip_address=ip)
            encoded=json.dumps(record,ensure_ascii=False)+'\n'
            path=self._path('events.jsonl')
            if (path.stat().st_size if path.exists() else 0)+len(encoded.encode('utf-8'))>MAX_LOG_BYTES:raise FeedbackError('The local feedback log is full.')
            with path.open('a',encoding='utf-8') as stream:stream.write(encoded)
            return dict(status='saved',event_id=normalized['event_id'],duplicate=False)

    def event(self,data,ip):return self._save(data,ip,False)
    def submit(self,data,ip):return self._save(data,ip,True)

