# -*- coding: utf-8 -*-
"""Build line_id -> EN speaker name map from the zh performance template
(lua_dbtemplatetranslation) + EN dblang translation table.

Template structure (all entries len 7):
  [action_id, scope, group, kind, perf_key, zh_value, note]
perf_key = performance_id * 1e10 + seq. Kinds:
  'specker_name' (sic) and 'dialogue_content' share perf_key -> join.
EN text for action_id lives in dblang_en/translation.json (same id space).
"""
import json, collections, os

BASE = os.path.dirname(os.path.abspath(__file__))
t = json.load(open(os.path.join(BASE, 'out/dbtemplate_translation_zh/translation.json'), encoding='utf-8'))
tr = json.load(open(os.path.join(BASE, 'out/dblang_en/translation.json'), encoding='utf-8'))
en = {e[0]: e[2] for e in tr}

spk = {}   # perf_key -> (speaker_en, speaker_zh, spk_action_id)
lines = {} # perf_key -> (line_id, en_text)
for e in t:
    if len(e) < 6:
        continue
    if e[3] == 'specker_name':
        spk[e[4]] = (en.get(e[0]), e[5], e[0])
    elif e[3] == 'dialogue_content':
        lines[e[4]] = (e[0], en.get(e[0]))

out = {}
stats = collections.Counter()
for k, (lid, en_text) in lines.items():
    if en_text is None:
        stats['line_no_en'] += 1
        continue
    s = spk.get(k)
    if not s or not s[0]:
        stats['no_speaker_en'] += 1
        continue
    out[str(int(lid))] = s[0]
    stats['ok'] += 1

json.dump(out, open(os.path.join(BASE, 'speaker_map.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
print(stats.most_common(), '-> speaker_map.json:', len(out))

cnt = collections.Counter(out.values())
json.dump(cnt.most_common(), open(os.path.join(BASE, 'speakers.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0)
print('unique speakers:', len(cnt))
for name, n in cnt.most_common(40):
    print('%6d  %s' % (n, name))
