# -*- coding: utf-8 -*-
"""Merge translations/chunk_*.ru.jsonl into the translation memory."""
import os
import sys
import json
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_chunks import load_tm, save_tm  # noqa

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    tm = load_tm()
    n_new = 0
    for p in sorted(glob.glob(os.path.join(BASE, 'chunks', 'chunk_*.jsonl'))):
        name = os.path.basename(p)
        ru_path = os.path.join(BASE, 'translations', name.replace('.jsonl', '.ru.jsonl'))
        if not os.path.exists(ru_path):
            continue
        en_rows = {}
        for line in open(p, encoding='utf-8'):
            r = json.loads(line)
            en_rows[r['key']] = r['en']
        for line in open(ru_path, encoding='utf-8'):
            r = json.loads(line)
            k = r['key']
            if k not in tm and k in en_rows:
                tm[k] = {'en': en_rows[k], 'ru': r['ru']}
                n_new += 1
    save_tm(tm)
    print('TM size: %d (+%d new)' % (len(tm), n_new))


if __name__ == '__main__':
    main()
