# -*- coding: utf-8 -*-
"""Robust Lua 5.1 chunk parser for SoC: brute-forces proto field layout."""
import struct


class Proto:
    pass


def read_str(d, p):
    n = struct.unpack_from('<Q', d, p)[0]; p += 8
    if n == 0:
        return None, p
    s = d[p:p + n - 1]
    return s.decode('utf-8', 'replace'), p + n


def try_parse_proto(d, p, str_len):
    """Parse proto body assuming source string already consumed.
    Returns (Proto, newpos) or None."""
    start = p
    f = Proto()
    f.source_len = str_len
    # flags: brute-forced position handled by caller; here standard:
    try:
        f.linedefined = struct.unpack_from('<I', d, p)[0]; p += 4
        f.lastlinedefined = struct.unpack_from('<I', d, p)[0]; p += 4
        f.nups = d[p]; f.numparams = d[p+1]; f.is_vararg = d[p+2]; f.maxstack = d[p+3]
        p += 4
        ncode = struct.unpack_from('<I', d, p)[0]; p += 4
        if ncode > (len(d) // 4):
            return None, start
        f.code = list(struct.unpack_from('<%dI' % ncode, d, p)); p += 4 * ncode
        nconst = struct.unpack_from('<I', d, p)[0]; p += 4
        if nconst > len(d):
            return None, start
        consts = []
        for _ in range(nconst):
            t = d[p]; p += 1
            if t == 0:
                consts.append(None)
            elif t == 1:
                consts.append(bool(d[p])); p += 1
            elif t == 3:
                consts.append(struct.unpack_from('<d', d, p)[0]); p += 8
            elif t == 4:
                s, p = read_str(d, p)
                consts.append(s)
            else:
                return None, start
        f.consts = consts
        nproto = struct.unpack_from('<I', d, p)[0]; p += 4
        if nproto > 1000:
            return None, start
        f.protos = []
        for _ in range(nproto):
            sub, p = parse_proto_flex(d, p)
            if sub is None:
                return None, start
            f.protos.append(sub)
        # debug
        nline = struct.unpack_from('<I', d, p)[0]; p += 4
        if nline > len(d):
            return None, start
        p += 4 * nline
        nloc = struct.unpack_from('<I', d, p)[0]; p += 4
        if nloc > 100000:
            return None, start
        for _ in range(nloc):
            _, p = read_str(d, p)
            p += 8
        nupv = struct.unpack_from('<I', d, p)[0]; p += 4
        if nupv > 100000:
            return None, start
        for _ in range(nupv):
            _, p = read_str(d, p)
        if p > len(d):
            return None, start
        return f, p
    except Exception:
        return None, start


def parse_proto_flex(d, p):
    """Parse proto: source string, then brute-force where the proto body starts
    (obfuscator may insert garbage/padding). Accept candidate that parses."""
    str_len = struct.unpack_from('<Q', d, p)[0]
    str_start = p + 8
    body_start = str_start + str_len  # includes NUL
    if str_len == 0:
        body_start = str_start
    if body_start > len(d):
        return None, p
    # try direct, and small shifts in case of padding
    for shift in range(0, 32):
        f, np = try_parse_proto(d, body_start + shift, str_len)
        if f is not None:
            return f, np
    return None, p


def parse_chunk_flex(data):
    assert data[:4] == b'\x1bLua'
    assert data[4] == 0x51
    f, p = parse_proto_flex(data, 12)
    return f, p
