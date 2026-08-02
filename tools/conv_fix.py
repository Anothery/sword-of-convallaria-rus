# -*- coding: utf-8 -*-
"""Gender fix for name+text performances (hero trust conversations).

The zh template has a second dialogue convention:
  kind='name' -> the NPC of the conversation; kind='text' -> alternating
  lines of the NPC and the player. These lines were NOT covered by
  speaker_map (which only handled specker_name/dialogue_content), so both
  passes missed their gender forms.

LLM labels each line (npc/player/other) and fixes:
  - npc lines: speaker-referring forms -> npc gender; addressee(player)-
    referring forms -> genderless.
  - player lines: self-referring forms -> genderless (player has no
    gender); addressee(npc)-referring forms -> npc gender.

Phases: queue | run | apply  (resumable, parallel workers).
"""
import json, os, re, sys, time, hashlib, urllib.request, collections, threading

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = os.environ.get('CONV_MODEL', 'tensorx/deepseek-v4-flash')
QUEUE = os.path.join(BASE, 'conv_queue.jsonl')
DONE = os.path.join(BASE, 'conv_done.jsonl')
TM_PATH = os.path.join(BASE, 'tm/tm_ru.json')
WORKERS = int(os.environ.get('CONV_WORKERS', '30'))
MAX_LINES_PER_BATCH = 40

TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n|\[\w+\]')
GENDERED_RE = re.compile(
    r'\b(?:\w{2,}(?:л|ла|ло)|рад[а]?|готов[аы]?|должн[ао]?|должна|счастлив[а]?|'
    r'уверен[а]?|сам[а]?|один|одна|виноват[а]?|способн[а]?|горд[а]?|'
    r'благодарн[а]?|согласн[а]?|голодн[а]?|занят[а]?|свободн[а]?|'
    r'строг[а]?|молод[а]?|богат[а]?|бедн[а]?|глуп[а]?|сильн[а]?|'
    r'слаб[а]?|жив[а]?|м[её]ртв[аы]?|прав[а]?|виновен|виновна)\b', re.U)


def key_of(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def tags_of(s):
    return TAG_RE.findall(s)


# ---------------------------------------------------------------- queue
def build_queue():
    t = json.load(open(os.path.join(BASE, 'out/dbtemplate_translation_zh/translation.json'), encoding='utf-8'))
    tr = {int(e[0]): e[2] for e in json.load(open(os.path.join(BASE, 'out/dblang_en/translation.json'), encoding='utf-8'))}
    genders = json.load(open(os.path.join(BASE, 'speakers_gender.json'), encoding='utf-8'))
    tm = json.load(open(TM_PATH, encoding='utf-8'))

    zh2en = {}
    for e in t:
        if len(e) >= 6 and e[3] == 'specker_name':
            en = tr.get(int(e[0]))
            if en and e[5]:
                zh2en[e[5]] = en
    # ручное добивание частых неразрешённых имён
    zh2en.update({'二王子': 'Lutfi', '阿莱克斯': 'Alexei', '鲁特菲殿下': 'Prince Lutfi'})

    perfs = collections.defaultdict(set)
    for e in t:
        if len(e) >= 6:
            perfs[int(e[4] // 1e10)].add(e[3])
    nt = {p for p, ks in perfs.items() if 'name' in ks and 'text' in ks}

    convs = collections.defaultdict(lambda: {'names': [], 'lines': []})
    for e in t:
        if len(e) < 6:
            continue
        p = int(e[4] // 1e10)
        if p not in nt:
            continue
        if e[3] == 'name':
            nm = tr.get(int(e[0])) or zh2en.get(e[5]) or e[5]
            convs[p]['names'].append(nm)
        elif e[3] == 'text':
            en = tr.get(int(e[0]))
            if en:
                convs[p]['lines'].append({'lid': int(e[0]), 'pk': e[4], 'en': en})

    n_conv = n_lines = n_flag = 0
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for p in sorted(convs):
            c = convs[p]
            if not c['names'] or not c['lines']:
                continue
            npc = c['names'][0].strip()
            g = genders.get(npc, genders.get(c['names'][0], 'unknown'))
            lines = []
            flagged = False
            for L in sorted(c['lines'], key=lambda x: x['pk']):
                tme = tm.get(key_of(L['en']))
                if not tme:
                    continue
                ru = tme['ru']
                if GENDERED_RE.search(ru):
                    flagged = True
                lines.append({'lid': L['lid'], 'en': L['en'], 'ru': ru})
            if not flagged or len(lines) < 2:
                continue
            n_conv += 1
            n_lines += len(lines)
            n_flag += sum(1 for L in lines if GENDERED_RE.search(L['ru']))
            f.write(json.dumps({'perf': p, 'npc': npc, 'g': g, 'lines': lines},
                               ensure_ascii=False) + '\n')
    print('conversations:', n_conv, '| lines:', n_lines, '| with gendered forms:', n_flag)


# ---------------------------------------------------------------- run
PROMPT = '''You are editing a Russian fan translation of the RPG "Sword of Convallaria".
Below are CONVERSATIONS between an NPC and the player character.
For each conversation you get: the NPC name and gender (m/f/unknown).
Each line has "lid", "en" (source), "ru" (current translation).

TASKS for every line:
1. Decide who speaks it: "npc", "player" or "other" (narrator/system).
2. Fix gender agreement in "ru" (Russian past-tense -л/-ла and short
   adjectives рад/рада, готов/готова, должен/должна, строг/строга...):
   - npc line: forms about the NPC must match the NPC gender; forms
     addressing the PLAYER must be gender-neutral (player has no gender —
     use plural, impersonal or "ты" + forms avoiding gender).
   - player line: forms about the player must be gender-neutral; forms
     addressing the NPC (e.g. "не будь так к себе строг/строга") must
     match the NPC gender.
   - if NPC gender is "unknown", infer the most likely gender from the
     NPC name and context (e.g. "Sorrowful Maiden" = f, "Gloomy Priest"
     = m); if genuinely impossible, only make player self-forms neutral
     and leave the rest.
3. Do NOT touch anything else: meaning, tone, length, markup.
   Preserve <...>, {0}, %s, \\n, [Keyword] EXACTLY, same order.
4. If a line needs no change, return it unchanged with "changed": false.

Reply with ONLY a JSON array covering ALL lines of ALL conversations:
[{"lid": <id>, "who": "npc"|"player"|"other", "ru": "<final>", "changed": true|false}, ...]

CONVERSATIONS:
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
            todo.append({'perf': c['perf'], 'npc': c['npc'], 'g': c['g'], 'lines': lines})
    if limit:
        todo = todo[:limit]
    print('todo convs:', len(todo), 'model:', MODEL, flush=True)

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
            parts.append('NPC: %s | gender: %s\n%s' % (c['npc'], c['g'], lines))
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
                print('batch FAILED (%d convs)' % len(batch), flush=True)
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
                    x['npc'] = c['npc']
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
    who_stat = collections.Counter()
    for l in open(DONE, encoding='utf-8'):
        x = json.loads(l)
        who_stat[x.get('who', '?')] += 1
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
          '| stale:', n_stale, '| empty:', n_empty, '| who:', who_stat.most_common())


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'queue':
        build_queue()
    elif cmd == 'run':
        run(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif cmd == 'apply':
        apply()
