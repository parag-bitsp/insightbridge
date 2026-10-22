"""Select category rules from the editable rubric; never interpret thresholds."""
import hashlib
import os
from pathlib import Path
import re
import stat

from .rubric_pdf import MAX_PDF_BYTES, MAX_RUBRIC_CHARACTERS, RubricPDFError, extract_rubric_pdf

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'decision-rubric-1'
SECTIONS = (
    ('Decision rules', None),
    ('Delayed deliveries', 'delivery_rules'),
    ('Post-payment item cancellations', 'cancellation_rules'),
    ('1. Context isolation', 'context_isolation'),
    ('2. Evaluation', 'evaluation'),
    ('3. Success criteria', 'success_criteria'),
    ('Flexibility versus reliability', 'flexibility'),
)
NUMBERED_SECTIONS = (
    ('1. Decision rules', None),
    ('1.1 Delayed deliveries', 'delivery_rules'),
    ('1.2 Post-payment item cancellations', 'cancellation_rules'),
    ('2. Context isolation', 'context_isolation'),
    ('3. Evaluation', 'evaluation'),
    ('4. Success criteria', 'success_criteria'),
    ('5. Model behaviour guidelines', 'success_criteria'),
    ('6. Roles and responsibilities', 'success_criteria'),
    ('7. Flexibility versus reliability', 'flexibility'),
)
COMMON = ('context_isolation', 'evaluation', 'success_criteria', 'flexibility')


class RubricError(ValueError):
    pass


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _heading(title):
    words = re.split(r'\s+', title)
    return re.compile(r'^[ \t]*' + r'\s+'.join(re.escape(word) for word in words) + r'[ \t]*:?[ \t]*$', re.I | re.M)


def parse_rubric(text):
    """Hash exact source text, then validate and select known document sections."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_RUBRIC_CHARACTERS:
        raise RubricError('Enter a decision rubric of 1 to 20,000 characters.')
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ')
    bundle = dict(version=VERSION, sha256=_hash(text), structured=False,
                  delivery_rules=text, cancellation_rules='', **dict.fromkeys(COMMON, ''))
    rich = (any(_heading(title).search(normalized) for title, _ in SECTIONS)
            or re.search(r'^[ \t]*(?:decision\s+rules?\b|decision\s+rubric\b|owner\s+decision\b|\d+\.\s+\w|(?:delayed\s+deliver\w*|post[-\s]payment[^\n]*|context\s+isolation|success\s+criteria|flexibility[^\n]*|evaluation)\s*:?[ \t]*$)', normalized, re.I | re.M))
    if not rich:
        return bundle
    sections = NUMBERED_SECTIONS if _heading('1. Decision rules').search(normalized) else SECTIONS
    matches = []
    for title, key in sections:
        found = list(_heading(title).finditer(normalized))
        if len(found) != 1:
            problem = 'missing or malformed' if not found else 'duplicated'
            raise RubricError(f'The rubric section "{title}" is {problem}.')
        matches.append((found[0], key))
    if [match.start() for match, _ in matches] != sorted(match.start() for match, _ in matches):
        raise RubricError('Rubric sections must follow the decision-rubric order.')
    if normalized[matches[0][0].end():matches[1][0].start()].strip():
        raise RubricError('Place decision rules inside their delivery or cancellation section.')
    footer = re.search(r'^\s*Owner\s+decision\s*:', normalized, re.I | re.M)
    end = footer.start() if footer else len(normalized)
    if end < matches[-1][0].end():
        raise RubricError('The owner-decision footer must follow all rubric sections.')
    for index, (match, key) in enumerate(matches):
        if key is None:
            continue
        stop = matches[index + 1][0].start() if index + 1 < len(matches) else end
        body = normalized[match.end():stop].strip()
        if not body:
            raise RubricError(f'The rubric section "{sections[index][0]}" is empty.')
        if re.search(r'^\s*(?:\d+\.\s+\w|#{1,6}\s+\w|(?:expected\s+(?:answers|findings)|evaluator\s+notes)\s*:?)', body, re.I | re.M):
            raise RubricError('The rubric contains an unrecognized or evaluator-only section.')
        bundle[key] = ' '.join(part for part in (bundle[key] if key != 'delivery_rules' else '', re.sub(r'\s+', ' ', body)) if part)
    bundle['structured'] = True
    return bundle


def for_category(bundle, category):
    """Expose only selected decision rules plus shared investigation guidance."""
    if category not in ('delivery', 'cancellation'):
        raise RubricError('Choose the delivery or cancellation rubric category.')
    rules = bundle.get(category + '_rules')
    if not isinstance(rules, str) or not rules.strip():
        raise RubricError(f'The rubric has no {category} decision rules.')
    return dict(version=bundle['version'], sha256=bundle['sha256'], category=category,
                decision_rules=rules, **{key: bundle.get(key, '') for key in COMMON})


def default_rubric():
    """Read only the fixed local PDF, refusing redirects and shared file links."""
    path = ROOT / 'InsightBridge-decision-rubric.pdf'
    try:
        if ROOT.resolve() != ROOT or path.resolve() != path:
            raise RubricError('The default rubric cannot use a redirected path.')
        with path.open('rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RubricError('The default rubric must be a regular file with no hardlinks.')
            if not 0 < info.st_size <= MAX_PDF_BYTES:
                raise RubricError('The default rubric PDF must be no larger than 5 MB.')
            content = source.read(MAX_PDF_BYTES + 1)
        if path.resolve() != path:
            raise RubricError('The default rubric cannot use a redirected path.')
        result = extract_rubric_pdf(content)
        return dict(result, sha256=_hash(result['text']))
    except (OSError, RubricPDFError) as exc:
        raise RubricError(f'The default rubric could not be loaded: {exc}') from None
