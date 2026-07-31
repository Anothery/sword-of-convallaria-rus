# -*- coding: utf-8 -*-
"""Lua 5.1 chunk parser adjusted for SoC custom VM quirks:
- every dumped string length is inflated by +10 (real = claimed - 10)
- opcodes are custom-shuffled (structure parse unaffected)
"""
import struct


class Proto:
    pass


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def f64(self):
        v = struct.unpack_from('<d', self.d, self.p)[0]; self.p += 8; return v

    def lua_str(self):
        n = struct.unpack_from('<Q', self.d, self.p)[0]; self.p += 8
        if n == 0:
            return None
        real = n - 10
        s = self.d[self.p:self.p + real - 1]  # exclude trailing NUL
        self.p += real
        return s.decode('utf-8', 'replace')


def parse_proto(r):
    f = Proto()
    f.source = r.lua_str()
    f.linedefined = r.u32()
    f.lastlinedefined = r.u32()
    f.nups = r.u8(); f.numparams = r.u8(); f.is_vararg = r.u8(); f.maxstack = r.u8()
    n = r.u32()
    f.code = [r.u32() for _ in range(n)]
    n = r.u32()
    consts = []
    for _ in range(n):
        t = r.u8()
        if t == 0:
            consts.append(None)
        elif t == 1:
            consts.append(bool(r.u8()))
        elif t == 3:
            consts.append(r.f64())
        elif t == 4:
            consts.append(r.lua_str())
        else:
            raise ValueError('bad const type %d at %d' % (t, r.p - 1))
    f.consts = consts
    n = r.u32()
    f.protos = [parse_proto(r) for _ in range(n)]
    n = r.u32(); r.p += 4 * n
    n = r.u32()
    for _ in range(n):
        r.lua_str(); r.u32(); r.u32()
    n = r.u32()
    for _ in range(n):
        r.lua_str()
    return f


def parse_chunk(data):
    assert data[:4] == b'\x1bLua' and data[4] == 0x51
    r = Reader(data)
    r.p = 12
    f = parse_proto(r)
    return f, r.p
