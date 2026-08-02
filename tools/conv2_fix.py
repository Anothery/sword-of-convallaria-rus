# -*- coding: utf-8 -*-
"""Gender fix for story 'text' lines in performances WITHOUT a 'name' entry.

These are battle/story dialogue lines (e.g. Maitha's reunion scene):
the zh template has kind='text' rows, the performance payload
(lua_dbtemplateperformance/performance.json) carries a title like
"网游线：麦莎团聚感想-I005" and roles with zh names.

LLM gets per-performance: zh title, zh role names, and the ordered lines,
then fixes gender forms in RU:
  - if the speaker can be determined (title/roles/content) — match gender;
  - player lines or unclear speakers — gender-neutral phrasing.

Phases: queue | run | apply  (resumable, parallel workers).
"""
import json, os, re, sys, time, hashlib, urllib.request, collections, threading

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = os.environ.get('CONV_MODEL', 'deepinfra/deepseek-v4-flash-0731')
QUEUE = os.path.join(BASE, 'conv2_queue.jsonl')
DONE = os.path.join(BASE, 'conv2_done.jsonl')
TM_PATH = os.path.join(BASE, 'tm/tm_ru.json')
WORKERS = int(os.environ.get('CONV_WORKERS', '50'))
MAX_LINES_PER_BATCH = 45

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
    t = json.load(open(os.path.join(BASE, 'out/dbtemplate_translation_zh/translation.json'), encoding='utf-8'))
    tr = {int(e[0]): e[2] for e in json.load(open(os.path.join(BASE, 'out/dblang_en/translation.json'), encoding='utf-8'))}
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    spk_map = json.load(open(os.path.join(BASE, 'speaker_map.json'), encoding='utf-8'))
    perf_rows = json.load(open(os.path.join(BASE, 'out_probe/lua_dbtemplateperformance/performance.json'), encoding='utf-8'))

    titles = {}
    roles_zh = {}
    for r in perf_rows:
        pid = int(r[0])
        titles[pid] = r[2] if len(r) > 2 else ''
        try:
            payload = json.loads(r[5], strict=False)
            roles_zh[pid] = [x.get('name', '') for x in payload.get('roles', []) if x.get('name')]
        except Exception:
            pass

    perfs = collections.defaultdict(set)
    for e in t:
        if len(e) >= 6:
            perfs[int(e[4] // 1e10)].add(e[3])
    no_name = {p for p, ks in perfs.items() if 'text' in ks and 'name' not in ks}

    convs = collections.defaultdict(list)
    for e in t:
        if len(e) >= 6 and e[3] == 'text' and int(e[4] // 1e10) in no_name:
            en = tr.get(int(e[0]))
            if en and str(int(e[0])) not in spk_map:
                convs[int(e[4] // 1e10)].append((e[4], int(e[0]), en))

    n_conv = n_lines = 0
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for p in sorted(convs):
            lines = []
            flagged = False
            for pk, lid, en in sorted(convs[p]):
                tme = tm.get(key_of(en))
                if not tme:
                    continue
                if GENDERED_RE.search(tme['ru']):
                    flagged = True
                lines.append({'lid': lid, 'en': en, 'ru': tme['ru']})
            if not flagged or not lines:
                continue
            n_conv += 1
            n_lines += len(lines)
            f.write(json.dumps({'perf': p, 'title': titles.get(p, ''),
                                'roles': roles_zh.get(p, []), 'lines': lines},
                               ensure_ascii=False) + '\n')
    print('perfs:', n_conv, '| lines:', n_lines)


# ---------------------------------------------------------------- run
PROMPT = '''You are editing a Russian fan translation of the RPG "Sword of Convallaria".
Below are STORY DIALOGUE fragments (battle scenes, reunions, monologues).
For each you get: the scene title (Chinese, often contains the character's
name, e.g. 麦莎 = Maitha (f), 萨曼莎 = Samantha (f)) and zh role names.
Each line has "lid", "en" (source), "ru" (current translation).

TASK — fix gender agreement in "ru" (past-tense -л/-ла, short adjectives
рад/рада, готов/готова, должен/должна...):
1. Infer WHO speaks each line from the title, roles and content. If the
   speaker is a known character, use their gender (Sword of Convallaria
   cast: Rawiyah, Maitha, Inanna, Safiyyah, Samantha, Beryl, Col, Gloria,
   Layla, Nungal, Cocoa, Momo are female; Faycal, Miguel, Nergal, Dantalion,
   Lutfi, Xavier, Magnus are male).
2. Speaker-referring forms must match the speaker's gender.
   Forms addressing the player character ({玩家昵称}) must be gender-neutral.
3. If you CANNOT determine the speaker's gender with confidence, rewrite
   the form gender-NEUTRALLY (impersonal, plural, present/future tense).
   NEVER guess 50/50 — neutral is better than wrong.
4. Do NOT touch anything else: meaning, tone, length, markup.
   Preserve <...>, {0}, %s, \\n, [Keyword] EXACTLY, same order.
5. If a line needs no change, return it unchanged with "changed": false.

Reply with ONLY a JSON array covering ALL lines:
[{"lid": <id>, "who": "<speaker guess or '?'>", "ru": "<final>", "changed": true|false}, ...]

FRAGMENTS:
'''

_lock = threading.Lock()


def run(limit=0):
    convs = [json.loads(l) for l in open(QUEUE, encoding='utf-8')]
    done = set()
    if os.path.exists(DONE):
        for l in open(DONE, encoding='utf-8'):
            done.add(json.loads(l)['lid'])
    todo = []
    for c in convs:
        lines = [L for L in c['lines'] if L['lid'] not in done]
        if lines:
            todo.append({'perf': c['perf'], 'title': c['title'], 'roles': c['roles'], 'lines': lines})
    if limit:
        todo = todo[:limit]
    print('todo perfs:', len(todo), 'model:', MODEL, flush=True)

    batches, cur, n = [], [], 0
    for c in todo:
        if n + len(c['lines']) > MAX_LINES_PER_BATCH and cur:
            batches.append(cur)
            cur, n = [], 0
        cur.append(c)
        n += len(c['lines'])
    if cur:
        batches.append(cur)
    print('batches:', len(batches), flush=True)

    fout = open(DONE, 'a', encoding='utf-8')
    stats = {'batches': 0, 'failed': 0}

    def payload(batch):
        parts = []
        for c in batch:
            lines = '\n'.join(json.dumps(L, ensure_ascii=False) for L in c['lines'])
            parts.append('SCENE: %s | roles: %s\n%s' % (
                c['title'] or '?', ', '.join(c['roles']) or '?', lines))
        return PROMPT + '\n\n'.join(parts)

    def work(batch):
        body = json.dumps({'model': MODEL,
                           'messages': [{'role': 'user', 'content': payload(batch)}],
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
                print('batch FAILED (%d perfs)' % len(batch), flush=True)
                return
            by_lid = {}
            for x in res:
                if isinstance(x, dict) and 'lid' in x:
                    by_lid[int(x['lid'])] = x
            for c in batch:
                for L in c['lines']:
                    x = by_lid.get(L['lid'])
                    if not x or not isinstance(x.get('ru'), str):
                        x = {'lid': L['lid'], 'ru': L['ru'], 'changed': False, 'missing': True}
                    x['en'] = L['en']
                    x['ru_old'] = L['ru']
                    x['perf'] = c['perf']
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
