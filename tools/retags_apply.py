# -*- coding: utf-8 -*-
"""Re-translate entries from retags_queue.jsonl (broken html tags / count mismatch)
via API with a strict tag-preservation prompt; update TM.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_chunks import load_tm, save_tm  # noqa
import translate_api
from translate_api import call_api, _state  # noqa

BASE = os.path.dirname(os.path.abspath(__file__))
HTMLTAG_RE = translate_api.TAG_RE  # includes brackets but we compare only non-bracket tags below

import re
STRICT_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n')

STRICT_PROMPT = (
    'You are a game localization translator EN->RU for "Sword of Convallaria", a tactical fantasy RPG. '
    'Literary Russian, "вы" form.\n'
    'CRITICAL: the source strings contain markup. Your output MUST contain EXACTLY the same set of '
    'markup tokens, unchanged, in the same order: <style=...>, </style>, <sprite=...>, {0}, %s, \\n. '
    'Translate ONLY the human-readable text. Bracketed keywords [Like This] translate into Russian.\n'
    'Input: JSON array of strings. Output: JSON array, same length/order. Output ONLY the JSON array.'
)


def main():
    queue = [json.loads(l) for l in open(os.path.join(BASE, 'retags_queue.jsonl'), encoding='utf-8')]
    tm = load_tm()
    print('queue:', len(queue))
    fixed = failed = 0
    B = 40
    orig_prompt = translate_api.SYSTEM_PROMPT
    for i in range(0, len(queue), B):
        group = queue[i:i + B]
        ens = [g['en'] for g in group]
        # patch prompt_for_batch to strict prompt
        translate_api.SYSTEM_PROMPT = STRICT_PROMPT
        orig_pfb = translate_api.prompt_for_batch
        translate_api.prompt_for_batch = lambda b: STRICT_PROMPT
        res, _ = call_api(ens)
        translate_api.prompt_for_batch = orig_pfb
        translate_api.SYSTEM_PROMPT = orig_prompt
        if res and len(res) == len(group):
            for g, ru in zip(group, res):
                if STRICT_RE.findall(g['en']) == STRICT_RE.findall(ru):
                    tm[g['key']]['ru'] = ru
                    fixed += 1
                else:
                    failed += 1
        else:
            failed += len(group)
        save_tm(tm)
        print('%d/%d fixed=%d failed=%d cost=$%.2f' % (i + len(group), len(queue), fixed, failed, _state['cost']), flush=True)
        if _state.get('stop'):
            print('BALANCE EMPTY — stopping')
            break
        time.sleep(0.3)
    save_tm(tm)
    print('DONE fixed=%d failed=%d cost=$%.2f' % (fixed, failed, _state['cost']))


if __name__ == '__main__':
    main()
