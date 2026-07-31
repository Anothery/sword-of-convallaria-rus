# -*- coding: utf-8 -*-
"""Post-pass: find TM entries whose RU text lost/garbled tags vs the EN source,
re-translate them via API with a strict prompt, update TM.

Usage: python fix_tags.py [--apply]
  without --apply: only report count.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_chunks import load_tm, save_tm  # noqa
from translate_api import call_api, tags_of, _state  # noqa

BASE = os.path.dirname(os.path.abspath(__file__))

STRICT_PROMPT = (
    'You are a game localization translator EN->RU for a tactical fantasy RPG. '
    'Translate into literary Russian ("вы" form).\n'
    'CRITICAL: the following strings contain markup tags. Your previous translation '
    'broke them. Output must contain EXACTLY the same tags as the source, unchanged '
    'and in the same order: <style=...>, </style>, <sprite=...>, {0}, %s, \\n, [Buff]-like brackets.\n'
    'Translate ONLY the human-readable text around the tags.\n'
    'Input: JSON array of strings. Output: JSON array, same length/order. ONLY the JSON array.'
)


def main():
    apply = '--apply' in sys.argv
    tm = load_tm()
    bad = [(k, v['en'], v['ru']) for k, v in tm.items()
           if tags_of(v['en']) != tags_of(v['ru'])]
    print('entries with broken tags: %d / %d' % (len(bad), len(tm)))
    if not apply or not bad:
        return
    fixed = failed = 0
    B = 40
    for i in range(0, len(bad), B):
        group = bad[i:i + B]
        ens = [g[1] for g in group]
        # override system prompt via direct call
        import translate_api
        orig = translate_api.SYSTEM_PROMPT
        translate_api.SYSTEM_PROMPT = STRICT_PROMPT
        res, _ = call_api(ens)
        translate_api.SYSTEM_PROMPT = orig
        if res and len(res) == len(group):
            for (k, en, _), ru in zip(group, res):
                if tags_of(en) == tags_of(ru):
                    tm[k]['ru'] = ru
                    fixed += 1
                else:
                    failed += 1
        else:
            failed += len(group)
        if i % (B * 10) == 0:
            save_tm(tm)
            print('progress %d/%d fixed=%d failed=%d cost=$%.2f' % (
                i, len(bad), fixed, failed, _state['cost']), flush=True)
        time.sleep(0.2)
    save_tm(tm)
    print('DONE fixed=%d failed=%d cost=$%.2f' % (fixed, failed, _state['cost']))
    if failed:
        print('re-run to retry the failures')


if __name__ == '__main__':
    main()
