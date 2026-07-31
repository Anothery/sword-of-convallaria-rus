# -*- coding: utf-8 -*-
"""Normalize [bracketed] keyword terms in RU translations.

Game skill texts use [Keyword] markup linking to the keyword tables
(skill_keyword etc.). Translators variously left them EN or translated ad-hoc.
This pass aligns brackets positionally EN<->RU and rewrites every RU bracket
to the canonical translation of the corresponding EN keyword:
  canonical = TM translation of the standalone keyword string, else glossary,
              else most-frequent observed RU form, else keep EN.
Entries where bracket counts differ (or html-tags differ) are exported to
retags_queue.jsonl for an API re-translation pass.

Usage: python bracket_fix.py
"""
import os
import sys
import re
import json
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_chunks import load_tm, save_tm  # noqa

BASE = os.path.dirname(os.path.abspath(__file__))
BRACKET_RE = re.compile(r'\[[^\[\]]{1,40}\]')
HTMLTAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n')


def main():
    tm = load_tm()
    glossary = json.load(open(os.path.join(BASE, 'glossary_ru.json'), encoding='utf-8'))
    glossary = {k: v for k, v in glossary.items() if not k.startswith('_')}

    # 1) collect all EN bracket tokens
    token_freq = Counter()
    for v in tm.values():
        for t in BRACKET_RE.findall(v['en']):
            token_freq[t] += 1

    # 2) canonical RU for each token: strip [] and look up
    def canon(token):
        inner = token[1:-1]
        for cand in (inner, inner.capitalize()):
            for v in tm.values():
                if v['en'] == cand:
                    return '[' + v['ru'] + ']'
        if inner in glossary:
            return '[' + glossary[inner] + ']'
        if inner.capitalize() in glossary:
            return '[' + glossary[inner.capitalize()] + ']'
        return None

    # faster: build en->ru map once
    en2ru = {}
    for v in tm.values():
        en2ru.setdefault(v['en'], v['ru'])

    FRAME_RE = re.compile(r'^\[((?:<[^>]+>)*)(.*?)((?:</[^>]+>)*)\]$')

    STATIC_INNER = {
        'front or side': 'спереди или сбоку',
        'side or behind': 'сбоку или сзади',
        'Empty Tile': 'Пустая клетка',
        'Empty Tiles': 'Пустые клетки',
        'behind': 'сзади',
        'front': 'спереди',
        'side': 'сбоку',
    }
    STAT_RE = re.compile(
        r'^(P\.ATK|M\.ATK|P\.DEF|M\.DEF|ATK|DEF|HP|Move|Jump|SPD|NRG|DMG|Crit)( (I|II|III|IV|V))?$')
    STAT_RU = {'P.ATK': 'ФИЗ.АТК', 'M.ATK': 'МАГ.АТК', 'P.DEF': 'ФИЗ.ЗАЩ',
               'M.DEF': 'МАГ.ЗАЩ', 'ATK': 'АТК', 'DEF': 'ЗАЩ', 'HP': 'HP',
               'Move': 'Перемещение', 'Jump': 'Прыжок', 'SPD': 'СКР', 'NRG': 'ЭНР',
               'DMG': 'УРОН', 'Crit': 'Крит'}

    def lookup(text):
        if '{' in text:
            return text  # template placeholder: keep unchanged
        m = STAT_RE.match(text)
        if m:
            ru = STAT_RU[m.group(1)]
            return ru + (m.group(2) or '')
        if re.match(r'^Level (\d+) Effect$', text):
            n = re.match(r'^Level (\d+) Effect$', text).group(1)
            return 'Эффект %s ур.' % n
        if text in STATIC_INNER:
            return STATIC_INNER[text]
        cands = [text,
                 text[0].upper() + text[1:] if text else text,
                 text.lower(),
                 text.title()]
        # singular fallback
        for c in list(cands):
            if c.endswith('s') and len(c) > 3:
                cands.append(c[:-1])
        for cand in cands:
            if cand in en2ru:
                return en2ru[cand]
            if cand in glossary:
                return glossary[cand]
        return None

    def canon2(token):
        inner = token[1:-1]
        m = FRAME_RE.match(token)
        if m and (m.group(1) or m.group(3)):
            ru_inner = lookup(m.group(2))
            if ru_inner:
                return '[' + m.group(1) + ru_inner + m.group(3) + ']'
            return None
        r = lookup(inner)
        return '[' + r + ']' if r else None

    canonical = {}
    missing = []
    for t in token_freq:
        c = canon2(t)
        if c:
            canonical[t] = c
        else:
            missing.append((t, token_freq[t]))
    print('bracket tokens: %d, canonical resolved: %d, unresolved: %d' % (
        len(token_freq), len(canonical), len(missing)))
    if missing:
        print('top unresolved:', sorted(missing, key=lambda x: -x[1])[:15])

    # 3) rewrite RU brackets positionally
    fixed = 0
    queue = []
    for k, v in tm.items():
        en, ru = v['en'], v['ru']
        en_t = BRACKET_RE.findall(en)
        ru_t = BRACKET_RE.findall(ru)
        if not en_t and not ru_t:
            continue
        if len(en_t) != len(ru_t) or HTMLTAG_RE.findall(en) != HTMLTAG_RE.findall(ru):
            queue.append({'key': k, 'en': en, 'ru': ru})
            continue
        changed = False
        out = ru
        # replace brackets one by one left-to-right
        parts = BRACKET_RE.split(out)
        toks = BRACKET_RE.findall(out)
        rebuilt = []
        for i, part in enumerate(parts):
            rebuilt.append(part)
            if i < len(toks):
                want = canonical.get(en_t[i])
                if want and toks[i] != want:
                    rebuilt.append(want)
                    changed = True
                else:
                    rebuilt.append(toks[i])
        if changed:
            v['ru'] = ''.join(rebuilt)
            fixed += 1
    save_tm(tm)
    with open(os.path.join(BASE, 'retags_queue.jsonl'), 'w', encoding='utf-8') as f:
        for r in queue:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('RU texts with brackets normalized: %d' % fixed)
    print('queued for API re-translation (count/html mismatch): %d' % len(queue))


if __name__ == '__main__':
    main()
