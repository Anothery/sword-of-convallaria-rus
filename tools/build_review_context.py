# -*- coding: utf-8 -*-
"""Build review_context.txt: glossary + named character genders + lore notes.

Inputs:
  glossary_ru.json          — EN -> RU terminology (~420 terms)
  speakers_gender.json      — speaker -> m/f/variable/unknown/neutral
  research/game_lore.md     — web-researched lore (optional, truncated)
  research/characters_web.md — web-researched character notes (optional)
Output: review_context.txt (embedded into the review prompt).
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))

parts = []

# 1. Glossary
gl = json.load(open(os.path.join(BASE, 'glossary_ru.json'), encoding='utf-8'))
items = ['%s = %s' % (k, v) for k, v in sorted(gl.items())]
parts.append('GLOSSARY (EN term = fixed RU term, use exactly):\n' + '; '.join(items))

# 2. Named character genders (skip generic NPC roles)
GENERIC_HINTS = ('guard', 'soldier', 'villager', 'knight', 'bandit', 'merchant',
                 'noble', 'servant', 'maid', 'worker', 'citizen', 'farmer',
                 'adventurer', 'mercenary', 'refugee', 'child', 'boy', 'girl',
                 'man', 'woman', 'elder', 'agent', 'spy', 'assassin', 'monk',
                 'priest', 'nun', 'student', 'teacher', 'doctor', 'chef',
                 'hunter', 'thief', 'pirate', 'sailor', 'officer', 'captain',
                 'voice', '???', 'crowd', 'all', 'both', 'everyone')
g = json.load(open(os.path.join(BASE, 'speakers_gender.json'), encoding='utf-8'))
named = {}
for name, gender in g.items():
    n = name.strip().lower()
    if gender not in ('m', 'f'):
        continue
    if any(h in n for h in GENERIC_HINTS):
        continue
    named[name.strip()] = gender
lines = ['%s — %s' % (n, 'мужчина' if v == 'm' else 'женщина')
         for n, v in sorted(named.items())]
parts.append('CHARACTER GENDERS (verified; m = мужчина, f = женщина):\n' + '\n'.join(lines))

# 3. Hard rules learned from manual review
parts.append('''HARD RULES (from manual QA):
- The player character ({玩家昵称} / PlayerName) has NO gender: never use
  gendered forms referring to them; rephrase impersonally if needed.
- The black cat pet ({黑猫昵称}) is male ("он").
- "Mysterious Cat" is male.
- Protagonist-addressing lines must not assume player gender.''')

# 4. Lore / web notes (truncated to keep prompt small)
for path, title, limit in [
    ('research/game_lore.md', 'GAME LORE (web research)', 3000),
    ('research/characters_web.md', 'CHARACTER NOTES (web research)', 6000),
]:
    p = os.path.join(BASE, path)
    if os.path.exists(p):
        txt = open(p, encoding='utf-8').read()
        parts.append('%s:\n%s' % (title, txt[:limit]))

out = '\n\n'.join(parts) + '\n'
open(os.path.join(BASE, 'review_context.txt'), 'w', encoding='utf-8').write(out)
print('review_context.txt written, chars:', len(out), '| named chars:', len(named))
