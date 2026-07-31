# -*- coding: utf-8 -*-
"""Brute-force search of valid Lua 5.1 proto layout inside decrypted chunk."""
import struct


def read_str(d, p):
    n = struct.unpack_from('<Q', d, p)[0]; p += 8
    if n == 0:
        return None, p
    if p + n > len(d):
        raise ValueError('str overrun')
    s = d[p:p + n - 1]
    return s.decode('utf-8', 'replace'), p + n


def parse_body(d, p, depth=0):
    """Parse from flags. Returns end position or None."""
    start = p
    try:
        if p + 4 > len(d): return None
        nups, numparams, is_vararg, maxstack = d[p], d[p+1], d[p+2], d[p+3]
        if is_vararg > 7 or maxstack < 1 or maxstack > 250: return None
        if numparams > 100 or nups > 100: return None
        p += 4
        ncode = struct.unpack_from('<I', d, p)[0]; p += 4
        if ncode < 1 or ncode > (len(d) - p) // 4: return None
        p += 4 * ncode
        nconst = struct.unpack_from('<I', d, p)[0]; p += 4
        if nconst > (len(d) - p): return None
        for _ in range(nconst):
            t = d[p]; p += 1
            if t == 0: pass
            elif t == 1: p += 1
            elif t == 3: p += 8
            elif t == 4:
                _, p = read_str(d, p)
            else: return None
            if p > len(d): return None
        nproto = struct.unpack_from('<I', d, p)[0]; p += 4
        if nproto > 10000: return None
        for _ in range(nproto):
            # nested proto: string + flags
            _, p2 = read_str(d, p)
            np = parse_body_flex(d, p2, depth + 1)
            if np is None: return None
            p = np
        # debug
        nline = struct.unpack_from('<I', d, p)[0]; p += 4
        if nline > (len(d) - p) // 4: return None
        p += 4 * nline
        nloc = struct.unpack_from('<I', d, p)[0]; p += 4
        if nloc > 100000: return None
        for _ in range(nloc):
            _, p = read_str(d, p); p += 8
            if p > len(d): return None
        nupv = struct.unpack_from('<I', d, p)[0]; p += 4
        if nupv > 100000: return None
        for _ in range(nupv):
            _, p = read_str(d, p)
            if p > len(d): return None
        return p
    except Exception:
        return None


def parse_body_flex(d, p, depth=0):
    for shift in range(0, 40):
        r = parse_body(d, p + shift, depth)
        if r is not None:
            return r
    return None


def find_layout(data):
    """Try all combinations: skip linedefined fields or not, string len as-is."""
    results = []
    # standard: header 12 bytes, then source string
    str_len = struct.unpack_from('<Q', data, 12)[0]
    base = 20 + (str_len if str_len else 0)
    for sstart in range(20, 60):
        for ld in (8, 4, 0):  # linedefined+lastlinedefined bytes present?
            p = sstart + ld
            r = parse_body(data, p)
            if r == len(data):
                results.append((sstart, ld))
    return results
