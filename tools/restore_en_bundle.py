# -*- coding: utf-8 -*-
"""Restore an English-source bundle from the RU-patched one using the
reverse TM (ru->en). Needed when the game folder already has the RU bundle
installed: the result serves as the build source for build_ru_bundle.py.

Usage: python restore_en_bundle.py <current_bundle(RU)> <out_dir>
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import UnityPy
from soc_crypto import full_decrypt, xor_decrypt, luaz_read_decrypt
from luasoc import parse_chunk
from chunkpatch import patch_chunk
from make_chunks import load_tm
from build_ru_bundle import find_value_const_indices, full_encrypt

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    src_bundle, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    tm = load_tm()
    ru2en = {}
    for v in tm.values():
        ru2en.setdefault(v['ru'], v['en'])
    print('reverse TM entries: %d' % len(ru2en))

    env = UnityPy.load(src_bundle)
    n_ru = n_keep = 0
    for o in env.objects:
        if o.type.name != 'TextAsset':
            continue
        d = o.read()
        raw = d.m_Script.encode('utf-8', 'surrogateescape')
        try:
            dec = full_decrypt(raw)
            proto, end = parse_chunk(dec)
            if end != len(dec):
                continue
            value_idx, _ = find_value_const_indices(proto)
            repl = {}
            for ci in sorted(value_idx):
                c = proto.consts[ci]
                if isinstance(c, str) and c in ru2en:
                    repl[ci] = ru2en[c]
                    n_ru += 1
                else:
                    n_keep += 1
            if repl:
                patched = patch_chunk(dec, repl)
                d.m_Script = full_encrypt(patched).decode('utf-8', 'surrogateescape')
                d.save()
        except Exception as e:
            print('SKIP %s: %s' % (d.m_Name, e))
    env.save(pack='lz4', out_path=out_dir)
    print('restored->en consts: %d, kept as-is: %d' % (n_ru, n_keep))
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
