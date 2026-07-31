# -*- coding: utf-8 -*-
"""Build the Russian bundle: replace EN string constants in lua_dblang_en.unity3d
with translations from the TM, re-encrypt, repack.

Also produces the RU version of localization/en/db_text.unity3d (plain JSON).

Usage: python build_ru_bundle.py [dist_dir]
"""
import os
import sys
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import UnityPy
from soc_crypto import full_decrypt, full_encrypt
from luasoc import parse_chunk
from chunkpatch import patch_chunk
from make_chunks import load_tm

BASE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(BASE)
OP_STORE = 25

# schema table: contents are field-name identifiers, never translate
SKIP_TABLES = {'db_tables'}
# snake_case identifiers must stay English
import re
IDENT_RE = re.compile(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$')


def find_value_const_indices(proto):
    """Simulate the constructor; returns (value_const_indices, protected_const_indices).
    value = consts used as entry text (last element), protected = field keys/ids."""
    regs = {}
    value_idx = set()
    protected = set()
    for ins in proto.code:
        op = ins >> 26
        b0 = ins & 0xFF
        if op == 5:  # NEWTABLE
            regs[b0] = None
        elif op == 6:  # LOADK
            bx = (ins >> 8) & 0x3FFFF
            regs[b0] = bx
        elif op == 25 and b0 > 0:
            n = ((ins >> 16) & 0xFF) // 2
            elems = [regs.get(b0 + 1 + i) for i in range(n)]
            for j, ci in enumerate(elems):
                if ci is None:
                    continue
                if n == 3 and j == 2:
                    value_idx.add(ci)
                elif n == 3 and j == 1:
                    protected.add(ci)
                elif n > 3:
                    # wide entries (zh-style): protect short key-like strings,
                    # translate only long text elements
                    c = proto.consts[ci]
                    if isinstance(c, str) and len(c) > 0:
                        if len(c) <= 24 and ' ' not in c:
                            protected.add(ci)
                        else:
                            value_idx.add(ci)
    return value_idx - protected, protected


def main():
    dist = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'dist')
    os.makedirs(dist, exist_ok=True)
    tm = load_tm()
    tm_ru = {v['en']: v['ru'] for v in tm.values()}
    print('TM entries: %d' % len(tm_ru))

    src_bundle = os.path.join(BASE, 'orig_en', 'lua_dblang_en.unity3d')
    if not os.path.exists(src_bundle):
        src_bundle = os.path.join(GAME, 'assets', 'lua', 'lua_dblang_en.unity3d')
    env = UnityPy.load(src_bundle)
    stats = {'tables': 0, 'consts_ru': 0, 'consts_left_en': 0}
    for o in env.objects:
        if o.type.name != 'TextAsset':
            continue
        d = o.read()
        raw = d.m_Script.encode('utf-8', 'surrogateescape')
        try:
            dec = full_decrypt(raw)
            proto, end = parse_chunk(dec)
            if end != len(dec):
                raise ValueError('trailing bytes')
            value_idx, protected = find_value_const_indices(proto)
            repl = {}
            if d.m_Name not in SKIP_TABLES:
                for ci in sorted(value_idx):
                    c = proto.consts[ci]
                    if isinstance(c, str) and c in tm_ru and not IDENT_RE.match(c):
                        repl[ci] = tm_ru[c]
                        stats['consts_ru'] += 1
                    elif isinstance(c, str) and c.strip():
                        stats['consts_left_en'] += 1
            if repl:
                patched = patch_chunk(dec, repl)
                d.m_Script = full_encrypt(patched).decode('utf-8', 'surrogateescape')
                d.save()
            stats['tables'] += 1
        except Exception as e:
            print('SKIP %s: %s' % (d.m_Name, e))
    out_bundle = os.path.join(dist, 'lua_dblang_en.unity3d')
    env.save(pack='lz4', out_path=dist)
    print('bundle saved ->', out_bundle)

    # plain-JSON system strings
    src_db = os.path.join(BASE, 'orig_en', 'db_text.unity3d')
    if not os.path.exists(src_db):
        src_db = os.path.join(GAME, 'assets', 'localization', 'en', 'db_text.unity3d')
    data = json.load(open(src_db, encoding='utf-8-sig'))
    n = 0
    for k, v in data.items():
        if isinstance(v, dict) and v.get('text') in tm_ru:
            v['text'] = tm_ru[v['text']]
            n += 1
    out_db = os.path.join(dist, 'db_text.unity3d')
    json.dump(data, open(out_db, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('db_text saved -> %s (%d strings translated)' % (out_db, n))
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
