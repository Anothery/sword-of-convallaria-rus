# -*- coding: utf-8 -*-
"""Patch string constants inside a decrypted SoC Lua 5.1 data chunk.

Data chunks (dblang tables) have a single proto (no nested protos).
Only the constants section is rebuilt; everything else is copied verbatim.
Unchanged string constants are copied BYTE-EXACT from the source (lossless);
only replaced strings are re-encoded (length+10 rule).
replacements: {const_index: new_text} — count/order of constants must not change.
"""
import struct


def _read_str_at(d, p):
    n = struct.unpack_from('<Q', d, p)[0]
    real = n - 10
    s = d[p + 8:p + 8 + real - 1]
    return s.decode('utf-8', 'replace'), p + 8 + real


def patch_chunk(data: bytes, replacements: dict) -> bytes:
    if not replacements:
        return data
    p = 12
    # source string
    _, p = _read_str_at(data, p)
    p += 8  # linedefined, lastlinedefined
    p += 4  # flags
    ncode = struct.unpack_from('<I', data, p)[0]
    p += 4 + 4 * ncode
    const_section_start = p
    nconst = struct.unpack_from('<I', data, p)[0]
    p += 4
    # walk consts, remember spans for verbatim copy
    spans = []  # (start, end, kind, value)
    for _ in range(nconst):
        start = p
        t = data[p]; p += 1
        if t == 0:
            spans.append((start, p, 'nil', None))
        elif t == 1:
            p += 1
            spans.append((start, p, 'raw', None))
        elif t == 3:
            p += 8
            spans.append((start, p, 'raw', None))
        elif t == 4:
            s, p = _read_str_at(data, p - 1 + 1)  # p already advanced past type
            spans.append((start, p, 'str', s))
        else:
            raise ValueError('bad const type %d at %d' % (t, start))
    const_section_end = p

    # rebuild constants section
    out = bytearray()
    out += struct.pack('<I', nconst)
    for i, (start, end, kind, val) in enumerate(spans):
        if kind == 'str' and i in replacements:
            b = replacements[i].encode('utf-8')
            out.append(4)
            out += struct.pack('<Q', len(b) + 1 + 10)
            out += b + b'\x00'
        else:
            out += data[start:end]

    nproto = struct.unpack_from('<I', data, const_section_end)[0]
    if nproto != 0:
        raise ValueError('nested protos not supported in patcher')
    return bytes(data[:const_section_start]) + bytes(out) + bytes(data[const_section_end:])
