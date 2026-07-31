# -*- coding: utf-8 -*-
"""Gender agreement fix pipeline for dialogue lines.

Phases:
  queue  — build gender_queue.jsonl (lines with gendered RU forms + speaker gender)
  run    — LLM fixes (sference/deepseek-v4-flash-0731) -> gender_done.jsonl (resumable)
  apply  — validate tags, update TM in place (tm/tm_ru.json)

Speaker genders: speakers_gender.json (m/f/variable/unknown/neutral).
  m/f      -> RU forms referring to the speaker must match that gender.
  neutral  -> rewrite avoiding gendered speaker-referring forms (player lines).
  variable -> crowd NPC (gender varies per instance) -> neutralize too.
  unknown  -> skip.
"""
import json, os, re, sys, time, hashlib, urllib.request, collections

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = 'tensorx/deepseek-v4-flash'
QUEUE = os.path.join(BASE, 'gender_queue.jsonl')
DONE = os.path.join(BASE, 'gender_done.jsonl')
TM_PATH = os.path.join(BASE, 'tm/tm_ru.json')

TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n|\[\w+\]')
# gendered RU forms: past-sg verbs (-л/-ла/-ло) and common short adjectives
GENDERED_RE = re.compile(
    r'\b(?:\w{2,}(?:л|ла|ло)|рад[а]?|готов[а]?|должн[ао]?|должна|счастлив[а]?|'
    r'уверен[а]?|сам[а]?|один|одна|виноват[а]?|способн[а]?|горд[а]?|'
    r'благодарн[а]?|согласн[а]?|голодн[а]?|занят[а]?|свободн[а]?|'
    r'рад[аы]?|молод[а]?|стар[а]?|богат[а]?|бедн[а]?|глуп[а]?|сил[её]н|'
    r'сильн[а]?|слаб[а]?|жив[а]?|мертв|м[её]ртв[аы]?)\b', re.U)


def key_of(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def tags_of(s):
    return TAG_RE.findall(s)


# ---------------------------------------------------------------- queue
def build_queue():
    spk_map = json.load(open(os.path.join(BASE, 'speaker_map.json'), encoding='utf-8'))
    genders = json.load(open(os.path.join(BASE, 'speakers_gender.json'), encoding='utf-8'))
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    tr = json.load(open(os.path.join(BASE, 'out/dblang_en/translation.json'), encoding='utf-8'))
    en_by_id = {str(int(e[0])): e[2] for e in tr}
    n = 0
    stats = collections.Counter()
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for lid, speaker in spk_map.items():
            g = genders.get(speaker, 'unknown')
            if g == 'unknown':
                stats['skip_unknown'] += 1
                continue
            en = en_by_id.get(lid)
            if not en:
                continue
            t = tm.get(key_of(en))
            if not t:
                stats['no_tm'] += 1
                continue
            ru = t['ru']
            if not GENDERED_RE.search(ru):
                stats['plain'] += 1
                continue
            f.write(json.dumps({'lid': lid, 'en': en, 'ru': ru,
                                'speaker': speaker, 'g': g},
                               ensure_ascii=False) + '\n')
            n += 1
            stats['queued_' + g] += 1
    print('queued:', n, dict(stats))


# ---------------------------------------------------------------- run
PROMPT = '''You are editing a Russian fan translation of the RPG "Sword of Convallaria".
Each item below is one dialogue line: EN source, current RU translation, the SPEAKER
and the required gender agreement for forms that refer to the SPEAKER:
- "m": speaker is male — speaker-referring forms must be masculine.
- "f": speaker is female — speaker-referring forms must be feminine.
- "neutral": rewrite to AVOID gendered speaker-referring forms entirely
  (use "мне удалось", "я вижу", "нужно…", plural/impersonal constructions, etc.).
Gendered forms = past-tense singular verbs (-л/-ла), short adjectives
(рад/рада, готов/готова, должен/должна, сам/сама, один/одна, …).

Rules:
- Fix ONLY gender agreement of speaker-referring forms. Do NOT touch forms
  referring to other people ("он пришёл", "она сказала" about someone else).
- If the line is already correct or has no speaker-referring gendered form,
  return it unchanged with "changed": false.
- Keep meaning, tone and roughly the same length. NEVER add or drop content.
- Preserve markup EXACTLY and in the same order: <...>, {0}, %s, \\n, [Keyword].
- Keep the natural literary Russian style of the original translation.

Reply with ONLY a JSON array, one object per input item, same order:
[{"lid": <id>, "ru": "<final russian text>", "changed": true|false}, ...]

ITEMS:
'''


def run():
    queue = [json.loads(l) for l in open(QUEUE, encoding='utf-8')]
    done = set()
    if os.path.exists(DONE):
        for l in open(DONE, encoding='utf-8'):
            done.add(json.loads(l)['lid'])
    todo = [q for q in queue if q['lid'] not in done]
    print('todo:', len(todo), 'done:', len(done))
    B = 50
    fout = open(DONE, 'a', encoding='utf-8')
    for i in range(0, len(todo), B):
        batch = todo[i:i + B]
        items = '\n'.join(json.dumps({'lid': q['lid'], 'en': q['en'], 'ru': q['ru'],
                                      'speaker': q['speaker'], 'g': q['g']},
                                     ensure_ascii=False) for q in batch)
        body = json.dumps({'model': MODEL,
                           'messages': [{'role': 'user', 'content': PROMPT + items}],
                           'temperature': 0.0, 'max_tokens': 16000}).encode()
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
                print('batch %d retry %d: %s' % (i, attempt, str(e)[:150]))
                time.sleep(5 + 10 * attempt)
        if res is None:
            print('batch %d FAILED, skipped' % i)
            continue
        by_lid = {str(x['lid']): x for x in res}
        for q in batch:
            x = by_lid.get(str(q['lid']))
            if not x:
                x = {'lid': q['lid'], 'ru': q['ru'], 'changed': False, 'missing': True}
            x['en'] = q['en']
            x['ru_old'] = q['ru']
            fout.write(json.dumps(x, ensure_ascii=False) + '\n')
        fout.flush()
        print('batch %d-%d done' % (i, i + len(batch)))
    fout.close()


# ---------------------------------------------------------------- apply
def apply():
    tm = json.load(open(TM_PATH, encoding='utf-8'))
    n_ok = n_tag_bad = n_changed = 0
    for l in open(DONE, encoding='utf-8'):
        x = json.loads(l)
        if not x.get('changed'):
            continue
        k = key_of(x['en'])
        if k not in tm or tm[k]['ru'] != x['ru_old']:
            continue  # TM moved on or duplicate line content mismatch
        if tags_of(x['ru']) != tags_of(x['ru_old']):
            n_tag_bad += 1
            continue
        tm[k]['ru'] = x['ru']
        n_changed += 1
        n_ok += 1
    json.dump(tm, open(TM_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('applied:', n_changed, 'tag-rejected:', n_tag_bad)


if __name__ == '__main__':
    {'queue': build_queue, 'run': run, 'apply': apply}[sys.argv[1]]()
