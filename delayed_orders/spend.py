"""Persistent conservative token-cost accounting across the authorized development campaign."""
import json
from pathlib import Path
import uuid
import time
from .analysis_models import COST_MODEL, model_pricing

CAP_MICRO_USD=2_000_000


class BudgetExceeded(RuntimeError):
    pass


class GenerationCancelled(BudgetExceeded):
    """Generation was cancelled before dispatch; its reservation is safe to settle at zero."""
    pass


def token_cost(input_tokens,output_tokens,*,model=COST_MODEL):
    # Conservative full-input rates; round up to micro-USD, retaining the campaign cap.
    rates=model_pricing(model)
    return (input_tokens*round(rates.get('reservation_input_per_million',rates['input_per_million'])*100)+output_tokens*round(rates['output_per_million']*100)+99)//100


class SpendLedger:
    def __init__(self,path,cap_micro_usd=CAP_MICRO_USD):
        if type(cap_micro_usd) is not int or not 0<cap_micro_usd<=CAP_MICRO_USD:
            raise BudgetExceeded('Invalid campaign ceiling')
        self.path=Path(path)
        self.cap=cap_micro_usd
        self.entries={}
        self._lock=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock_path=self.path.with_suffix('.lock')
        try: self._lock=self.lock_path.open('x')
        except FileExistsError: raise BudgetExceeded('Campaign ledger is locked; reconcile an interrupted run before retrying.') from None
        try:
            if self.path.exists():
                saved=json.loads(self.path.read_text())
                if (type(saved.get('cap_micro_usd')) is not int or not 0<saved['cap_micro_usd']<=CAP_MICRO_USD
                    or not isinstance(saved.get('entries'),dict)):
                    raise BudgetExceeded('Invalid campaign ledger; reconcile before retrying.')
                for entry in saved['entries'].values():
                    if (not isinstance(entry,dict) or entry.get('status') not in ('reserved','settled')
                        or type(entry.get('accounted_micro_usd')) is not int or entry['accounted_micro_usd']<0):
                        raise BudgetExceeded('Invalid campaign ledger; reconcile before retrying.')
                self.cap=min(self.cap,saved['cap_micro_usd'])
                self.entries=saved['entries']
            self._save()
            return self
        except Exception:
            self.__exit__(None,None,None)
            raise

    def __exit__(self,*args):
        if self._lock:
            self._lock.close()
            self.lock_path.unlink()
            self._lock=None

    @property
    def accounted_micro_usd(self):
        return sum(e['accounted_micro_usd'] for e in self.entries.values())

    @property
    def is_open(self):
        return self._lock is not None and not self._lock.closed

    def _require_open(self):
        if not self.is_open: raise BudgetExceeded('Campaign ledger must be opened under its exclusive lock.')

    def _save(self):
        self._require_open()
        temporary=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(dict(campaign='development-v1',cap_micro_usd=self.cap,entries=self.entries),indent=2)+'\n')
        # Windows scanners can briefly hold the previous ledger open. Retry
        # only the atomic local replacement, never a provider/model request.
        for attempt in range(4):
            try:
                temporary.replace(self.path)
                break
            except PermissionError:
                if attempt==3:raise
                time.sleep(.02*(2**attempt))

    def reserve(self,amount):
        self._require_open()
        if type(amount) is not int or amount<0 or self.accounted_micro_usd+amount>self.cap:
            raise BudgetExceeded('Authorized development token-cost ceiling would be exceeded.')
        ticket=uuid.uuid4().hex
        self.entries[ticket]=dict(status='reserved',accounted_micro_usd=amount)
        self._save()
        return ticket

    def settle(self,ticket,actual):
        self._require_open()
        if (ticket not in self.entries or self.entries[ticket]['status']!='reserved'
            or type(actual) is not int or actual<0):
            raise BudgetExceeded('Invalid reservation settlement.')
        self.entries[ticket]=dict(status='settled',accounted_micro_usd=actual)
        self._save()
