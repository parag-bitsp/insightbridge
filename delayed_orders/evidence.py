"""Case-scoped, read-only evidence capability. Public operations accept symbols, not paths."""
import copy
import hashlib
import json
from pathlib import Path
import re
from collections import Counter

DEVELOPMENT_CASES = ('DO-01', 'DO-03', 'DO-07', 'DO-11')
SOURCES = ('orders', 'order_events', 'promise_history', 'feedback', 'assignment_attempts',
           'rider_availability', 'label_prints', 'packing_queues', 'staffing_rosters',
           'travel_conditions', 'safety_reports', 'supervisor_messages')
_INPUT_ROOT = Path(__file__).resolve().parents[1] / 'fixtures/v1/agent-inputs'


class AccessDenied(ValueError):
    """Requested operation is outside the evidence capability."""


class DataError(ValueError):
    """Source is inconsistent; no guessed repair is applied."""


def _read_file(root, case, filename):
    path = case / filename
    # Reject junctions/symlinks in the case or file path and hard-link aliases.
    # The fixed root is configured by host code, never supplied by a tool caller.
    if case.resolve() != root.resolve() / case.name or path.resolve() != case.resolve() / filename:
        raise AccessDenied('Linked or redirected evidence path')
    if path.stat().st_nlink != 1:
        raise AccessDenied('Hard-linked evidence file')
    return path.read_bytes()


class Evidence:
    """Loaded snapshot of one development case. No write or generic filesystem method.

    Return values are copies. Conflicting source/order IDs fail closed. Unknown,
    cross-case and path-shaped identifiers are rejected rather than queried.
    """
    def __init__(self, case_id):
        if case_id not in DEVELOPMENT_CASES:
            raise AccessDenied('Only the four authorized development cases are enabled')
        self._load_case(case_id, _INPUT_ROOT, 'v1')

    def _load_case(self, case_id, root, version):
        """Host-only helper. Runtime tools never receive a root or this method."""
        self.case_id = case_id
        self._version = version
        case = root / case_id
        self._hashes = {}

        def read(filename):
            data = _read_file(root, case, filename)
            self._hashes[filename] = hashlib.sha256(data).hexdigest()
            return data.decode('utf-8-sig')

        self._request = json.loads(read('request.json'))
        catalog = json.loads(read('source_catalog.json'))
        if catalog.get('access') != 'read_only' or set(catalog.get('sources', {})) != set(SOURCES):
            raise AccessDenied('Unsupported source catalogue')
        self._catalog = catalog['sources']
        # Validate the complete catalogue before reading any referenced source.
        for name, entry in self._catalog.items():
            if entry.get('path') != name + '.jsonl':
                raise AccessDenied('Catalogue paths must match fixed source filenames')
            if entry.get('status') not in ('available', 'not_collected', 'records_unavailable'):
                raise DataError('Unknown availability status')
        self._tables = {}
        self._raw = {}
        self._duplicates = {}
        self._multiplicities = {}
        global_ids = set()
        for name in SOURCES:
            rows = [json.loads(line) for line in read(name + '.jsonl').splitlines() if line.strip()]
            if self._catalog[name]['status'] != 'available' and rows:
                raise DataError('Unavailable source contains records')
            self._raw[name] = len(rows)
            self._multiplicities[name] = dict(Counter(r.get('source_id') for r in rows))
            distinct = {}
            for row in rows:
                sid = row.get('source_id')
                self._check_ids([sid], 'source')
                if row.get('order_id') is not None:
                    self._check_ids([row['order_id']], 'order')
                if sid in distinct and row != distinct[sid]:
                    raise DataError('Conflicting duplicate source ID: ' + sid)
                if sid in global_ids:
                    raise DataError('Source ID reused across tables: ' + sid)
                distinct[sid] = row
            global_ids.update(distinct)
            self._tables[name] = sorted(distinct.values(), key=lambda r: r['source_id'])
            self._duplicates[name] = len(rows) - len(distinct)
        orders = {}
        for row in self._tables['orders']:
            oid = row['order_id']
            if oid in orders:
                raise DataError('Multiple distinct snapshots for order: ' + oid)
            orders[oid] = row
        for name, rows in self._tables.items():
            for row in rows:
                if row.get('order_id') is not None and row['order_id'] not in orders:
                    raise DataError('Unknown order link in ' + name)

    def _check_ids(self, ids, kind):
        if not isinstance(ids, (list, tuple)) or len(ids) > 500:
            raise AccessDenied('IDs must be a list of at most 500 identifiers')
        suffix = r'-ORD-\d+' if kind == 'order' else r'-[A-Z]+-\d+'
        for identifier in ids:
            if not isinstance(identifier, str) or not re.fullmatch(re.escape(self.case_id) + suffix, identifier):
                raise AccessDenied('Invalid or cross-case ' + kind + ' ID')

    def request(self):
        return copy.deepcopy(self._request)

    def provenance(self):
        return {'case_id': self.case_id, 'fixture_version': self._version, 'sha256': dict(self._hashes)}

    def query(self, source, *, order_ids=None, source_ids=None, offset=0, limit=500):
        if not isinstance(source, str) or source not in SOURCES:
            raise AccessDenied('Unsupported source symbol')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise AccessDenied('Invalid pagination')
        for ids, kind in ((order_ids, 'order'), (source_ids, 'source')):
            if ids is not None:
                self._check_ids(ids, kind)
        entry = self._catalog[source]
        rows = self._tables[source]
        if order_ids is not None:
            rows = [r for r in rows if r.get('order_id') in order_ids]
        if source_ids is not None:
            rows = [r for r in rows if r['source_id'] in source_ids]
        available = entry['status'] == 'available'
        return copy.deepcopy(dict(source=source, status=entry['status'], lookup_response=entry.get('lookup_response'),
            total=len(rows) if available else None, raw_rows=self._raw[source] if available else None,
            duplicate_rows=self._duplicates[source] if available else None, records=rows[offset:offset+limit],
            source_multiplicities={r['source_id']: self._multiplicities[source][r['source_id']]
                                   for r in rows[offset:offset+limit]} if available else {},
            next_offset=offset+limit if offset+limit < len(rows) else None))
