"""Masked checkpoints for re-evaluating a historical QA response."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from redaction import mask_sensitive


def case_fingerprint(case):
    return hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_response(directory, page_id, cases, response):
    safe_response = mask_sensitive(response)
    if not safe_response.strip():
        raise ValueError('Нельзя сохранить пустой ответ')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'agent-response-{uuid4().hex}.json'
    payload = {
        'format': 'qa-response-v1',
        'saved_at': datetime.now(timezone.utc).isoformat(),
        'page_id': str(page_id),
        'case_hashes': {case['id']: case_fingerprint(case) for case in cases},
        'response': safe_response,
        'response_sha256': hashlib.sha256(safe_response.encode()).hexdigest(),
    }
    # Unique checkpoint: a later run cannot overwrite an earlier response.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return path


def load_response(path, cases):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('format') != 'qa-response-v1':
        raise ValueError('Неподдерживаемый формат сохранённого ответа')
    response = payload.get('response')
    if not isinstance(response, str) or not response.strip():
        raise ValueError('Сохранённый ответ пуст или повреждён')
    if hashlib.sha256(response.encode()).hexdigest() != payload.get('response_sha256'):
        raise ValueError('Хеш сохранённого ответа не совпадает')
    for case in cases:
        if str(case['input']['page_id']) != payload.get('page_id'):
            raise ValueError('Ответ относится к другой странице Confluence')
        if payload.get('case_hashes', {}).get(case['id']) != case_fingerprint(case):
            raise ValueError(f"Кейс {case['id']} отсутствует в снимке или изменён")
    return mask_sensitive(response)
