# -*- coding: utf-8 -*-
"""Gender fix for scenario_text lines (VN-style scenario dialogues).

scenario_text.json holds 23,765 lines in script order (ids sequential
within a scene) but the speaker linkage lives in nested scenario tables
we can't extract cheaply. Instead we give the LLM consecutive-line
windows: dialogue flow + character knowledge reveals the speaker.

Rules: fix speaker-referring gender forms when the speaker is inferable;
player lines / unclear speakers -> gender-neutral. Natural Russian.

Phases: queue | run | apply  (resumable, parallel workers).
"""
import json, os, re, sys, time, hashlib, urllib.request, collections, threading

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = os.environ.get('CONV_MODEL', 'deepinfra/deepseek-v4-flash-0731')
QUEUE = os.path.join(BASE, 'scen_queue.jsonl')
DONE = os.path.join(BASE, 'scen_done.jsonl')
TM_PATH = os.path.join(BASE, 'tm/tm_ru.json')
WORKERS = int(os.environ.get('CONV_WORKERS', '50'))
MAX_LINES_PER_BATCH = 45
CTX = 3  # строк контекста до/после

TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n|\[\w+\]')
GENDERED_RE = re.compile(
    r'\b(?:\w{2,}(?:л|ла|ло)|рад[а]?|готов[аы]?|должн[ао]?|должна|счастлив[а]?|'
    r'уверен[а]?|сам[а]?|один|одна|виноват[а]?|способн[а]?|горд[а]?|'
    r'благодарн[а]?|согласн[а]?|занят[а]?|свободн[а]?|строг[а]?)\b', re.U)


def key_of(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def tags_of(s):
    return TAG_RE.findall(s)


# ---------------------------------------------------------------- queue
def build_queue():
    d = json.load(open(os.path.join(BASE, 'out/dblang_en/scenario_text.json'), encoding='utf-8'))
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    rows = sorted((int(r[0]), r[2]) for r in d if len(r) >= 3 and isinstance(r[2], str))
    idx = {rid: i for i, (rid, _) in enumerate(rows)}
    items = []
    for rid, en in rows:
        tme = tm.get(key_of(en))
        if not tme or not GENDERED_RE.search(tme['ru']):
            continue
        items.append((rid, en, tme['ru']))

    # окна: непрерывные прогоны id (разрыв > 3 — новое окно), с контекстом
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for rid, en, ru in items:
            i = idx[rid]
            ctx_before = [{'lid': rows[j][0], 'en': rows[j][1]}
                          for j in range(max(0, i - CTX), i) if 0 <= rows[j][0] - rows[max(0, i - CTX)][0]]
            ctx_after = [{'lid': rows[j][0], 'en': rows[j][1]}
                         for j in range(i + 1, min(len(rows), i + 1 + CTX))]
            f.write(json.dumps({'lid': rid, 'en': en, 'ru': ru,
                                'before': ctx_before, 'after': ctx_after},
                               ensure_ascii=False) + '\n')
    print('queued gendered lines:', len(items))


# ---------------------------------------------------------------- run
PROMPT = '''You are editing a Russian fan translation of the RPG "Sword of Convallaria".
Each item is one DIALOGUE LINE from a story scene ("en" = source, "ru" =
current translation) plus neighboring lines for context ("before"/"after").
The original translation was machine-made with a MASCULINE BIAS: female
characters often got masculine verb forms. Your job is surgical repair.

You may change a line ONLY in these cases:
A) "ru" has a MASCULINE self-referring form (-л, рад, готов, должен, сам...)
   and the context CLEARLY shows the speaker is FEMALE (she is named in
   the line or its context, e.g. "Maitha", "— сказала она", or she
   obviously continues a named female speaker's turn) -> make it feminine.
   Known females: Rawiyah, Maitha, Beryl, Inanna, Safiyyah, Samantha,
   Col, Gloria, Nungal, Layla, Cocoa, Momo, Edda, Agata, Simona, Kiya.
B) "ru" has a FEMININE self-referring form and the speaker is CLEARLY male
   (same evidence standard) -> make it masculine. This is rare.
C) The line is spoken by the player character ({玩家昵称}) or TO the
   player and contains a gendered form about the player -> rewrite
   gender-NEUTRAL (impersonal, plural, present/future).
D) The speaker cannot be determined AND the gendered form can be
   neutralized NATURALLY with a tiny edit (e.g. "Я не знал" -> "Понятия
   не имел(а)"-style avoided; prefer "не знали", "трудно сказать",
   present/future tense) -> neutralize. If neutralization needs
   restructuring, LEAVE THE LINE UNCHANGED.

HARD RULES:
- NEVER flip feminine -> masculine except case B with explicit evidence.
- NEVER guess genders; when in doubt, leave unchanged.
- Do NOT change anything besides gender agreement: keep meaning, tone,
  length, word choice. Preserve markup <...>, {0}, %s, \\n, [Keyword]
  EXACTLY, same order.
- If no change is needed, return the line unchanged ("changed": false).

Reply with ONLY a JSON array, one object per item, same order:
[{"lid": <id>, "ru": "<final russian>", "changed": true|false}, ...]

ITEMS:
'''

_lock = threading.Lock()


def run(limit=0):
    queue = [json.loads(l) for l in open(QUEUE, encoding='utf-8')]
    done = set()
    if os.path.exists(DONE):
        for l in open(DONE, encoding='utf-8'):
            done.add(json.loads(l)['lid'])
    todo = [q for q in queue if q['lid'] not in done]
    if limit:
        todo = todo[:limit]
    print('todo:', len(todo), 'done:', len(done), 'model:', MODEL, flush=True)
    batches = [todo[i:i + MAX_LINES_PER_BATCH] for i in range(0, len(todo), MAX_LINES_PER_BATCH)]
    fout = open(DONE, 'a', encoding='utf-8')
    stats = {'batches': 0, 'failed': 0}

    def work(batch):
        items_txt = []
        for q in batch:
            parts = []
            if q['before']:
                parts.append('context before: ' + ' | '.join(x['en'][:80] for x in q['before']))
            parts.append(json.dumps({'lid': q['lid'], 'en': q['en'], 'ru': q['ru']}, ensure_ascii=False))
            if q['after']:
                parts.append('context after: ' + ' | '.join(x['en'][:80] for x in q['after']))
            items_txt.append('\n'.join(parts))
        body = json.dumps({'model': MODEL,
                           'messages': [{'role': 'user', 'content': PROMPT + '\n---\n'.join(items_txt)}],
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
            by_lid = {}
            for x in res:
                if isinstance(x, dict) and 'lid' in x:
                    by_lid[int(x['lid'])] = x
            for q in batch:
                x = by_lid.get(q['lid'])
                if not x or not isinstance(x.get('ru'), str):
                    x = {'lid': q['lid'], 'ru': q['ru'], 'changed': False, 'missing': True}
                x['en'] = q['en']
                x['ru_old'] = q['ru']
                fout.write(json.dumps(x, ensure_ascii=False) + '\n')
            fout.flush()
            stats['batches'] += 1
            if stats['batches'] % 10 == 0:
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
        if not x.get('changed') or x['lid'] in seen:
            continue
        seen.add(x['lid'])
        k = key_of(x['en'])
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
