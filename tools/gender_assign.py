# -*- coding: utf-8 -*-
"""Assign gender to speakers via LLM (sference/deepseek-v4-flash-0731).

Output: speakers_gender.json  {speaker: m|f|variable|unknown|neutral}
Hardcoded per user decisions: {玩家昵称}=neutral, {黑猫昵称}=m.
"""
import json, os, re, sys, time, urllib.request, collections

BASE = os.path.dirname(os.path.abspath(__file__))
API_URL = 'https://router.requesty.ai/v1/chat/completions'
API_KEY = os.environ.get('REQUESTY_API_KEY', '')
MODEL = 'tensorx/deepseek-v4-flash'

HARD = {'{玩家昵称}': 'neutral', '{黑猫昵称}': 'm', '???': 'unknown'}

speakers = json.load(open(os.path.join(BASE, 'speakers.json'), encoding='utf-8'))
spk_map = json.load(open(os.path.join(BASE, 'speaker_map.json'), encoding='utf-8'))
tr = json.load(open(os.path.join(BASE, 'out/dblang_en/translation.json'), encoding='utf-8'))
en_by_id = {str(int(e[0])): e[2] for e in tr}

# sample line per speaker
sample = {}
for lid, s in spk_map.items():
    if s not in sample and en_by_id.get(lid):
        sample[s] = en_by_id[lid][:120].replace('\n', ' ')

def call(batch, retries=5):
    prompt = (
        'You are localizing the tactical RPG "Sword of Convallaria" into Russian. '
        'For each dialogue SPEAKER below, decide the gender that Russian first-person '
        'verb/adjective forms in their lines must agree with.\n'
        'Rules:\n'
        '- "m" = masculine (male character), "f" = feminine (female character).\n'
        '- "variable" = generic role/crowd NPC that appears as different genders '
        '(e.g. "Mercenary", "Soldier", "Villager", "Bandit", "Merchant").\n'
        '- "unknown" = cannot determine (mysterious voice, creature, narrator).\n'
        '- Named characters: use your knowledge of the game; infer from the sample line if needed.\n'
        'Reply with ONLY a compact JSON object {"speaker": "m|f|variable|unknown", ...} '
        'with exactly the same speaker names as keys.\n\n'
        'SPEAKERS (name | lines | sample line):\n' +
        '\n'.join('%s | %d | %s' % (n, c, sample.get(n, '')) for n, c in batch))
    body = json.dumps({
        'model': MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.0, 'max_tokens': 8000,
    }).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={
                'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=300))
            txt = r['choices'][0]['message']['content']
            m = re.search(r'\{.*\}', txt, re.S)
            return json.loads(m.group(0))
        except Exception as e:
            print('retry %d: %s' % (i, str(e)[:120]))
            time.sleep(5 + 10 * i)
    return {}

todo = [(n, c) for n, c in speakers if n not in HARD]
out = dict(HARD)
B = 100
for i in range(0, len(todo), B):
    batch = todo[i:i + B]
    res = call(batch)
    miss = [n for n, _ in batch if n not in res]
    for n in miss:
        res[n] = 'unknown'
    out.update(res)
    print('batch %d-%d ok (%d missing)' % (i, i + len(batch), len(miss)))

json.dump(out, open(os.path.join(BASE, 'speakers_gender.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
g = collections.Counter(out.values())
print('TOTAL:', len(out), dict(g))
