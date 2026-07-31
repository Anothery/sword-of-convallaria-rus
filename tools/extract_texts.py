# -*- coding: utf-8 -*-
"""Extract all language texts from Sword of Convallaria asset bundles.

Usage:
    python extract_texts.py <bundle.unity3d> <out_dir>

Every TextAsset in a dblang bundle is a custom Lua 5.1 chunk that builds
an array of [id, field, text] triplets. We decrypt, parse and simulate the
tiny opcode subset used by these data chunks, then dump JSON:
    out_dir/<table>.json  ->  [[id, field, text], ...]
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import UnityPy
from soc_crypto import full_decrypt
from luasoc import parse_chunk

OP_NEWTABLE = 5
OP_LOADK = 6
OP_STORE = 25


def extract_triplets(proto):
    """Simulate the data-table constructor; returns list of entry lists.

    Each entry is built by NEWTABLE + n x LOADK into consecutive registers,
    finished by OP_STORE (op25) whose b2 hint = 2*n. Entries are arrays:
    typically [id, field, text] or wider (zh source: 7 elements).
    """
    regs = {}
    entries = []
    other_ops = {}
    for ins in proto.code:
        op = ins >> 26
        b0 = ins & 0xFF
        if op == OP_NEWTABLE:
            regs[b0] = ('table',)
        elif op == OP_LOADK:
            bx = (ins >> 8) & 0x3FFFF
            regs[b0] = proto.consts[bx] if bx < len(proto.consts) else None
        elif op == OP_STORE:
            if b0 == 0:
                continue  # batch flush into main table
            n = ((ins >> 16) & 0xFF) // 2
            entries.append([regs.get(b0 + 1 + i) for i in range(n)])
        elif op == 17:
            pass  # RETURN
        elif op == 0:
            pass  # register window reset
        else:
            other_ops[op] = other_ops.get(op, 0) + 1
    return entries, other_ops


def get_asset_bytes(obj):
    d = obj.read()
    s = d.m_Script
    raw = s.encode('utf-8', 'surrogateescape') if isinstance(s, str) else s
    return d.m_Name, raw


def main():
    bundle, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    n_ok = n_fail = 0
    all_ops = {}
    total_strings = 0
    for o in env.objects:
        if o.type.name != 'TextAsset':
            continue
        name, raw = get_asset_bytes(o)
        try:
            dec = full_decrypt(raw)
            proto, end = parse_chunk(dec)
            if end != len(dec):
                raise ValueError('trailing bytes: %d/%d' % (end, len(dec)))
            entries, other_ops = extract_triplets(proto)
            for k, v in other_ops.items():
                all_ops[k] = all_ops.get(k, 0) + v
            total_strings += sum(1 for e in entries for v in e if isinstance(v, str) and v)
            with open(os.path.join(out_dir, name + '.json'), 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=0)
            n_ok += 1
        except Exception as e:
            n_fail += 1
            print('FAIL %s: %s' % (name, e))
    print('tables ok: %d, failed: %d, text strings: %d' % (n_ok, n_fail, total_strings))
    if all_ops:
        print('WARNING: unhandled opcodes:', all_ops)


if __name__ == '__main__':
    main()
