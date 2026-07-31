# -*- coding: utf-8 -*-
"""Build one flat JSONL with every translatable string for a language pack.

Each line: {"table":..., "n":<entry#>, "id":..., "field":..., "text":...}
Only the text element of [id, field, text] triplets is exported
(wider entries from zh-source tables are exported element-wise).
"""
import sys
import os
import json
import glob

NON_TEXT_FIELDS = {'performance', 'actions'}


def main():
    src_dir, out_file = sys.argv[1], sys.argv[2]
    n = 0
    with open(out_file, 'w', encoding='utf-8') as out:
        for path in sorted(glob.glob(os.path.join(src_dir, '*.json'))):
            table = os.path.basename(path)[:-5]
            entries = json.load(open(path, encoding='utf-8'))
            for i, e in enumerate(entries):
                if len(e) == 3 and isinstance(e[1], str) and isinstance(e[2], str) and e[2]:
                    # [id, field, text]
                    if e[1] in NON_TEXT_FIELDS:
                        continue
                    rec = {'table': table, 'n': i, 'id': e[0], 'field': e[1], 'text': e[2]}
                    out.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    n += 1
                elif len(e) > 3:
                    # wide entries (e.g. zh source): export each non-empty string
                    for j, v in enumerate(e):
                        if isinstance(v, str) and v and v not in NON_TEXT_FIELDS:
                            rec = {'table': table, 'n': i, 'id': e[0], 'col': j, 'text': v}
                            out.write(json.dumps(rec, ensure_ascii=False) + '\n')
                            n += 1
    print('exported strings:', n)


if __name__ == '__main__':
    main()
