# -*- coding: utf-8 -*-
"""Style pass over the whole TM: make the Russian sound NATIVE.

User feedback: some lines are understandable but phrased unlike real
Russian speech. This pass rewrites ONLY genuinely awkward/calqued lines;
correct natural lines are returned unchanged.

Phases: queue | run | apply  (resumable, parallel workers).
Model: deepseek-v4-flash-0731 (deepinfra), reasoning_effort=low.
"""
import json, os, re, sys, time, hashlib, urllib.request, collections, threading

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = os.environ.get('REVIEW_MODEL', 'deepinfra/deepseek-v4-flash-0731')
QUEUE = os.path.join(BASE, 'style_queue.jsonl')
DONE = os.path.join(BASE, 'style_done.jsonl')
TM_PATH = os.path.join(BASE, 'tm/tm_ru.json')
CTX_PATH = os.path.join(BASE, 'review_context.txt')
WORKERS = int(os.environ.get('REVIEW_WORKERS', '100'))
BATCH = int(os.environ.get('REVIEW_BATCH', '50'))

TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n|\[\w+\]')


def key_of(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def tags_of(s):
    return TAG_RE.findall(s)


# ---------------------------------------------------------------- queue
def build_queue():
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for k, t in tm.items():
            f.write(json.dumps({'k': k, 'en': t['en'], 'ru': t['ru']},
                               ensure_ascii=False) + '\n')
    print('queued:', len(tm))


# ---------------------------------------------------------------- run
def load_prompt():
    ctx = ''
    if os.path.exists(CTX_PATH):
        ctx = open(CTX_PATH, encoding='utf-8').read()
    return '''You are a NATIVE Russian editor polishing a fan translation of
the tactical RPG "Sword of Convallaria" (EN -> RU). Each item: "en" =
source, "ru" = current translation.

Rewrite ONLY lines that sound translated/calqued or unnatural to a native
speaker: awkward word order, literal English constructions ("Я отправил
этих ребят" from a girl, "Это делает меня чувствовать..."), wrong
conjunctions/prepositions, bureaucratic tone where the game is lively,
broken idioms. Make the line sound like something a Russian person would
actually say/write — while keeping it game-appropriate (fantasy RPG).

STRICT rules:
- If the line already reads naturally — return it UNCHANGED
  ("changed": false). Most lines are fine; do not restyle for the sake
  of restyling.
- NEVER change meaning, facts, tone register, or length significantly.
- NEVER touch gender agreements: keep -л/-ла and adjective genders
  referring to speakers exactly as they are (they were curated).
- Keep ALL terminology and proper names EXACTLY as in the current
  translation and the glossary below (Вейверан, Люксит, Конваллария...).
- Preserve markup <...>, {0}, %s, \\n, [Keyword] EXACTLY, same order.
- Sound-effect markers like *ик*, *всхлип* stay as-is.

Reply with ONLY a JSON array, one object per input item, same order:
[{"k": "<key>", "ru": "<final russian>", "changed": true|false}, ...]

''' + ctx + '''
ITEMS:
'''


_lock = threading.Lock()


def run(limit=0):
    queue = [json.loads(l) for l in open(QUEUE, encoding='utf-8')]
    done = set()
    if os.path.exists(DONE):
        for l in open(DONE, encoding='utf-8'):
            done.add(json.loads(l)['k'])
    todo = [q for q in queue if q['k'] not in done]
    if limit:
        todo = todo[:limit]
    print('todo:', len(todo), 'done:', len(done), 'model:', MODEL, flush=True)
    prompt = load_prompt()
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    fout = open(DONE, 'a', encoding='utf-8')
    stats = {'batches': 0, 'failed': 0}

    def work(batch):
        items = '\n'.join(json.dumps(q, ensure_ascii=False) for q in batch)
        body = json.dumps({'model': MODEL,
                           'messages': [{'role': 'user', 'content': prompt + items}],
                           'temperature': 0.0, 'max_tokens': 16000,
                           'reasoning_effort': 'low'}).encode()
        res = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(API_URL, data=body, headers={
                    'Authorization': 'Bearer ' + API_KEY,
                    'Content-Type': 'application/json'})
                r = json.load(urllib.request.urlopen(req, timeout=600))
                txt = r['choices'][0]['message']['content']
                m = re.search(r'\[.*\]', txt, re.S)
                res = json.loads(m.group(0))
                break
            except Exception as e:
                print('retry %d: %s' % (attempt, str(e)[:150]), flush=True)
                time.sleep(5 + 10 * attempt)
        with _lock:
            if res is None:
                stats['failed'] += 1
                print('batch FAILED (%d items)' % len(batch), flush=True)
                return
            by_k = {x.get('k'): x for x in res if isinstance(x, dict)}
            for q in batch:
                x = by_k.get(q['k'])
                if not x or not isinstance(x.get('ru'), str):
                    x = {'k': q['k'], 'ru': q['ru'], 'changed': False, 'missing': True}
                x['en'] = q['en']
                x['ru_old'] = q['ru']
                fout.write(json.dumps(x, ensure_ascii=False) + '\n')
            fout.flush()
            stats['batches'] += 1
            if stats['batches'] % 20 == 0:
                print('batches done:', stats['batches'], '/', len(batches), flush=True)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, batches))
    fout.close()
    print('finished. batches:', stats['batches'], 'failed:', stats['failed'])


# ---------------------------------------------------------------- apply
def apply():
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    n_changed = n_tag_bad = n_stale = n_empty = 0
    seen = set()
    for l in open(DONE, encoding='utf-8'):
        x = json.loads(l)
        if not x.get('changed') or x['k'] in seen:
            continue
        seen.add(x['k'])
        k = x['k']
        if k not in tm or tm[k]['ru'] != x['ru_old']:
            n_stale += 1
            continue
        if not x['ru'].strip():
            n_empty += 1
            continue
        if tags_of(x['ru']) != tags_of(x['ru_old']):
            n_tag_bad += 1
            continue
        tm[k]['ru'] = x['ru']
        n_changed += 1
    json.dump(tm, open(TM_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('applied:', n_changed, '| tag-rejected:', n_tag_bad,
          '| stale:', n_stale, '| empty:', n_empty)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'queue':
        build_queue()
    elif cmd == 'run':
        run(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif cmd == 'apply':
        apply()
