from copy import deepcopy
from io import StringIO

from ruamel.yaml import YAML


MANUAL_KEYS = {
    'x-manual-analysis',
    'x-manual-analytics',
    'x-human-review',
    'x-manual',
}
MANUAL_COMMENT_MARKERS = ('# manual', '# ручная', '# human', '# reviewed')


def yaml_parser():
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_spec(text):
    y = yaml_parser()
    return y.load(text)


def dump_spec(data):
    y = yaml_parser()
    out = StringIO()
    y.dump(data, out)
    return out.getvalue()


def collect_manual_analytics(data):
    found = []

    def walk(node, path=''):
        if isinstance(node, dict):
            for key, value in node.items():
                current = f'{path}/{key}' if path else str(key)
                if str(key).lower() in MANUAL_KEYS:
                    found.append(f'{current}: {value}')
                walk(value, current)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f'{path}[{i}]')

    walk(data)

    try:
        for comment in (data.ca.comment or []):
            for token in (comment or []):
                if token and token.value:
                    text = str(token.value)
                    if any(m in text.lower() for m in MANUAL_COMMENT_MARKERS):
                        found.append(f'comment: {text.strip()}')
    except Exception:
        pass

    return found


def _check_manual_preserved(before_spec, after_spec):
    before = collect_manual_analytics(before_spec)
    after = collect_manual_analytics(after_spec)
    return [b for b in before if b not in after]


def _classify(source, missing):
    if missing:
        return (
            'ambiguous',
            'low',
            'ВНИМАНИЕ: часть ручной аналитики могла быть потеряна, требуется ручной разбор.',
        )
    if source == 'spec':
        return ('spec', 'high', '')
    if source == 'code':
        return ('code / live API', 'high', '')
    return ('ambiguous', 'low', 'Источник истины не определён однозначно.')


def generate_response_proposal(spec_text, path, method, status_code, description):
    spec = load_spec(spec_text)
    before = dump_spec(spec)

    manual = collect_manual_analytics(spec)
    paths = spec.get('paths', {})
    if path not in paths:
        raise ValueError(f'Endpoint {path} не найден в OpenAPI')
    operation = paths[path].get(method.lower())
    if operation is None:
        raise ValueError(f'Метод {method.upper()} для {path} не найден')

    after_spec = deepcopy(spec)
    operation_after = after_spec['paths'][path][method.lower()]
    responses = operation_after.setdefault('responses', {})
    code = str(status_code)
    if code in responses:
        raise ValueError(f'Response {code} уже существует')

    responses[code] = {'description': description or f'Ответ {code}'}
    after = dump_spec(after_spec)

    missing = _check_manual_preserved(spec, after_spec)
    source_of_truth, confidence, note = _classify('code', missing)

    reason = (
        f'В анализе обнаружено расхождение: фактический сервис использует '
        f'HTTP {code} для {method.upper()} {path}, но этот ответ отсутствует '
        f'в спецификации.'
    )
    if note:
        reason = f'{reason} {note}'
    if missing:
        reason += ' Потерянные блоки: ' + '; '.join(missing)

    return {
        'title': f'Добавить ответ {code} для {method.upper()} {path}',
        'path': path,
        'method': method.upper(),
        'proposal_type': 'add_response',
        'reason': reason,
        'source_of_truth': source_of_truth,
        'confidence': confidence,
        'before': before,
        'after': after,
        'manual_analytics': '\n'.join(manual),
        'requires_manual_review': bool(missing) or confidence == 'low',
    }
