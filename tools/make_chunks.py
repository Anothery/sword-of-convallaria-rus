# -*- coding: utf-8 -*-
"""Build translation chunks in priority order + manage translation memory.

TM (tm/tm_ru.json): {key: {"en":..., "ru":...}} where key = sha1(en)[:16].
Chunks (chunks/chunk_NNNN.jsonl): {"key", "table", "field", "en"} — only
strings NOT yet present in TM (so re-runs after game updates only emit
new/changed strings).
"""
import sys
import os
import json
import hashlib

BASE = os.path.dirname(os.path.abspath(__file__))
TM_PATH = os.path.join(BASE, 'tm', 'tm_ru.json')

# translation priority: lower = earlier
PRIORITY = [
    'db_text',            # system strings
    'text',               # UI strings
    'translation',        # main story dialogue
    'scenario_text',
    'briefing', 'briefing_page', 'briefing_option',
    'online_pattern_dialogue', 'unit_voice_collection', 'scenario',
    'skill', 'skill_keyword', 'buff', 'buff_tag', 'speciality', 'special_effect',
    'mission_buff_pool', 'blessing',
    'unit', 'unit_npc', 'profession', 'unit_personality', 'character_title',
    'region', 'capital_npc',
    'online_quest', 'online_main_quest_template',
]
CHARS_PER_CHUNK = 20000


def key_of(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]


def load_tm():
    if os.path.exists(TM_PATH):
        return json.load(open(TM_PATH, encoding='utf-8'))
    return {}


def save_tm(tm):
    os.makedirs(os.path.dirname(TM_PATH), exist_ok=True)
    json.dump(tm, open(TM_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


def iter_all_strings():
    """Yields (table, field, text) for every translatable string."""
    path = os.path.join(BASE, 'out', 'all_texts_en.jsonl')
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        yield r['table'], r.get('field', 'col%d' % r.get('col', 0)), r['text']
    # system strings
    sys_path = os.path.join(BASE, 'out', 'db_text_en.json')
    if os.path.exists(sys_path):
        data = json.load(open(sys_path, encoding='utf-8'))
        for k, v in data.items():
            if isinstance(v, dict) and v.get('text'):
                yield 'db_text', v.get('type', 'system'), v['text']


def main():
    tm = load_tm()
    seen = {}
    for table, field, text in iter_all_strings():
        if not text or not text.strip():
            continue
        k = key_of(text)
        if k in seen or k in tm:
            continue
        seen[k] = (table, field, text)

    def prio(item):
        t = item[1][0]
        return PRIORITY.index(t) if t in PRIORITY else len(PRIORITY)

    items = sorted(seen.items(), key=lambda kv: (prio(kv), kv[1][0]))
    os.makedirs(os.path.join(BASE, 'chunks'), exist_ok=True)
    # clean stale chunks
    for f in os.listdir(os.path.join(BASE, 'chunks')):
        os.remove(os.path.join(BASE, 'chunks', f))

    n = 0
    cur = []
    cur_chars = 0
    total = 0
    for k, (table, field, text) in items:
        cur.append({'key': k, 'table': table, 'field': field, 'en': text})
        cur_chars += len(text)
        total += 1
        if cur_chars >= CHARS_PER_CHUNK:
            n += 1
            _write_chunk(n, cur)
            cur, cur_chars = [], 0
    if cur:
        n += 1
        _write_chunk(n, cur)
    print('strings to translate: %d, chunks: %d' % (total, n))


def _write_chunk(n, rows):
    p = os.path.join(BASE, 'chunks', 'chunk_%04d.jsonl' % n)
    with open(p, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
