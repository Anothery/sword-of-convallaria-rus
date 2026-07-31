# -*- coding: utf-8 -*-
"""Mass EN->RU translation worker via Requesty (OpenAI-compatible API).

Features: batching, resume via TM, tag-preservation validation, retries,
cost tracking with a hard budget cap.

Usage:
  python translate_api.py [--chunks 1-504] [--batch-size 250] [--max-cost 20.0]
"""
import os
import sys
import json
import time
import re
import argparse
import threading
import queue

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_chunks import load_tm, save_tm, TM_PATH, key_of  # noqa

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')  # export REQUESTY_API_KEY=...
MODEL = 'anthropic/claude-haiku-4-5'
LOG_PATH = os.path.join(BASE, 'translate_log.jsonl')
TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n|\[\w+\]')

import urllib.request


def load_glossary():
    g = json.load(open(os.path.join(BASE, 'glossary_ru.json'), encoding='utf-8'))
    return {k: v for k, v in g.items() if not k.startswith('_')}


GLOSSARY = load_glossary()
GLOSSARY_TEXT = '\n'.join('%s = %s' % (k, v) for k, v in GLOSSARY.items())

PROMPT_HEAD = (
    'You are a professional game localization translator (EN->RU) for "Sword of Convallaria", '
    'a tactical fantasy RPG. Translate into literary Russian, address the player as "вы".\n'
)
PROMPT_RULES = (
    'HARD RULES:\n'
    '1. Preserve ALL tags/placeholders EXACTLY and in place: <style=...>, </style>, <sprite=...>, '
    '<color=...>, </color>, {0}, {1}, %s, %d, \\n (escaped newline), [Buff]-style brackets.\n'
    '2. Do not translate inside tags/placeholders. Keep leading/trailing spaces.\n'
    '3. Keep UI strings SHORT (buttons). Numbers/percent formats unchanged.\n'
    '4. Transliterate proper nouns missing from the glossary consistently.\n'
    '5. Input: JSON array of strings. Output: JSON array of Russian translations, SAME length and order. '
    'Output ONLY the JSON array, no markdown, no comments.'
)
SYSTEM_PROMPT = PROMPT_HEAD + 'MANDATORY glossary (use exactly these translations):\n' + GLOSSARY_TEXT + '\n\n' + PROMPT_RULES

# glossary terms sorted longest-first for substring matching
_GLOSSARY_TERMS = sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0]))


def prompt_for_batch(batch):
    """System prompt with only the glossary terms present in this batch."""
    text = '\n'.join(batch).lower()
    used = [(k, v) for k, v in _GLOSSARY_TERMS if k.lower() in text]
    if len(used) >= len(_GLOSSARY_TERMS) * 0.7:
        return SYSTEM_PROMPT
    g = '\n'.join('%s = %s' % (k, v) for k, v in used)
    if g:
        return PROMPT_HEAD + 'MANDATORY glossary (use exactly these translations):\n' + g + '\n\n' + PROMPT_RULES
    return PROMPT_HEAD + PROMPT_RULES


_lock = threading.Lock()
_state = {'cost': 0.0, 'req': 0, 'errors': 0, 'stop': False}


def log_rec(rec):
    with _lock:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def call_api(batch, max_tokens=16000, retries=6):
    """batch: list of EN strings -> list of RU strings (same length) or None."""
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': prompt_for_batch(batch)},
            {'role': 'user', 'content': json.dumps(batch, ensure_ascii=False)},
        ],
        'max_tokens': max_tokens,
        'temperature': 0.3,
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    delay = 5.0
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=body, headers={
            'Authorization': 'Bearer ' + API_KEY,
            'Content-Type': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
            d = json.loads(raw.decode('utf-8'))
            cost = d.get('usage', {}).get('cost', 0) or 0
            with _lock:
                _state['cost'] += cost
                _state['req'] += 1
            content = d['choices'][0]['message']['content']
            arr = extract_json_array(content)
            if arr is not None and len(arr) == len(batch):
                return arr, cost
            log_rec({'type': 'bad_length', 'got': None if arr is None else len(arr),
                     'want': len(batch)})
        except urllib.error.HTTPError as e:
            with _lock:
                _state['errors'] += 1
            code = e.code
            log_rec({'type': 'http_error', 'code': code, 'attempt': attempt})
            if code == 429:
                ra = e.headers.get('Retry-After')
                time.sleep(float(ra) if ra else delay)
            elif code == 402:
                log_rec({'type': 'balance_empty'})
                _state['stop'] = True
                return None, 0
            elif code >= 500:
                time.sleep(delay)
            else:
                return None, 0  # 4xx other than 429: don't retry
        except Exception as e:
            with _lock:
                _state['errors'] += 1
            log_rec({'type': 'error', 'err': str(e)[:200], 'attempt': attempt})
            time.sleep(delay)
        delay = min(delay * 2, 120)
    return None, 0


def extract_json_array(content):
    s = content.strip()
    if s.startswith('```'):
        s = re.sub(r'^```\w*\n?', '', s)
        s = re.sub(r'\n?```$', '', s)
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [str(x) for x in v]
    except Exception:
        pass
    # try to locate first [ ... last ]
    i, j = s.find('['), s.rfind(']')
    if i >= 0 and j > i:
        try:
            v = json.loads(s[i:j + 1])
            if isinstance(v, list):
                return [str(x) for x in v]
        except Exception:
            return None
    return None


def tags_of(t):
    return sorted(TAG_RE.findall(t))


def translate_batch(batch, budget):
    """Returns list of RU strings (same length) or None. Retries/splits internally."""
    if _state.get('stop'):
        return None
    res, cost = call_api(batch)
    if res is None:
        if len(batch) == 1:
            return None
        mid = len(batch) // 2
        a = translate_batch(batch[:mid], budget)
        b = translate_batch(batch[mid:], budget)
        if a is None or b is None:
            return None
        return a + b
    # tag validation: retry individual failures once
    fixed = list(res)
    for i, (en, ru) in enumerate(zip(batch, fixed)):
        if tags_of(en) != tags_of(ru):
            single, _ = call_api([en])
            if single and tags_of(en) == tags_of(single[0]):
                fixed[i] = single[0]
            else:
                log_rec({'type': 'tag_mismatch', 'en': en[:100], 'ru': ru[:100]})
    return fixed


def chunk_range(spec):
    a, b = spec.split('-')
    return range(int(a), int(b) + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunks', default='1-504')
    ap.add_argument('--batch-size', type=int, default=250)
    ap.add_argument('--max-cost', type=float, default=20.0)
    ap.add_argument('--workers', type=int, default=3)
    args = ap.parse_args()

    tm = load_tm()
    tasks = []  # (chunk_no, [rows to translate])
    for n in chunk_range(args.chunks):
        p = os.path.join(BASE, 'chunks', 'chunk_%04d.jsonl' % n)
        out = os.path.join(BASE, 'translations', 'chunk_%04d.ru.jsonl' % n)
        if not os.path.exists(p) or os.path.exists(out):
            continue
        rows = [json.loads(l) for l in open(p, encoding='utf-8')]
        todo = [r for r in rows if r['key'] not in tm]
        if todo:
            tasks.append((n, rows, todo))

    total_str = sum(len(t[2]) for t in tasks)
    print('chunks todo: %d, strings todo: %d, already in TM: %d' % (len(tasks), total_str, len(tm)))

    q = queue.Queue()
    for t in tasks:
        q.put(t)

    def worker():
        while True:
            try:
                n, rows, todo = q.get_nowait()
            except queue.Empty:
                return
            if _state['cost'] >= args.max_cost or _state.get('stop'):
                print('STOP: cost=$%.2f stop=%s' % (_state['cost'], _state.get('stop')))
                return
            results = {}
            for i in range(0, len(todo), args.batch_size):
                batch_rows = todo[i:i + args.batch_size]
                batch = [r['en'] for r in batch_rows]
                ru = translate_batch(batch, args.max_cost)
                if ru is None:
                    log_rec({'type': 'batch_failed', 'chunk': n, 'i': i})
                    continue
                for r, t in zip(batch_rows, ru):
                    results[r['key']] = t
                    tm[r['key']] = {'en': r['en'], 'ru': t}
                with _lock:
                    save_tm(tm)
                print('chunk %04d: %d/%d (cost $%.3f, err %d)' % (
                    n, min(i + args.batch_size, len(todo)), len(todo),
                    _state['cost'], _state['errors']), flush=True)
            # write chunk output if fully done
            missing = [r for r in rows if r['key'] not in tm]
            if not missing:
                with open(os.path.join(BASE, 'translations', 'chunk_%04d.ru.jsonl' % n),
                          'w', encoding='utf-8') as f:
                    for r in rows:
                        f.write(json.dumps({'key': r['key'], 'ru': tm[r['key']]['ru']},
                                           ensure_ascii=False) + '\n')
                print('chunk %04d DONE' % n, flush=True)
            else:
                print('chunk %04d partial, missing %d' % (n, len(missing)), flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    save_tm(tm)
    print('FINISHED. total cost: $%.3f, requests: %d, errors: %d, TM size: %d' % (
        _state['cost'], _state['req'], _state['errors'], len(tm)))


if __name__ == '__main__':
    main()
