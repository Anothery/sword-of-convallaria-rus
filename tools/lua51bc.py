# -*- coding: utf-8 -*-
"""Minimal Lua 5.1 bytecode chunk parser (x64: int=4, size_t=8, instr=4, number=8).
Extracts functions, instructions and constants; can rebuild literal data tables.
"""
import struct


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def u64(self):
        v = struct.unpack_from('<Q', self.d, self.p)[0]; self.p += 8; return v

    def f64(self):
        v = struct.unpack_from('<d', self.d, self.p)[0]; self.p += 8; return v

    def lua_str(self):
        n = self.u64()
        if n == 0:
            return None
        s = self.d[self.p:self.p + n - 1]  # trailing NUL excluded
        self.p += n
        return s.decode('utf-8', 'replace')


class Proto:
    pass


def parse_proto(r: Reader) -> Proto:
    f = Proto()
    f.source = r.lua_str()
    f.linedefined = r.u32()
    f.lastlinedefined = r.u32()
    f.nups = r.u8()
    f.numparams = r.u8()
    f.is_vararg = r.u8()
    f.maxstacksize = r.u8()
    # code
    n = r.u32()
    f.code = [r.u32() for _ in range(n)]
    # constants
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
            raise ValueError('unknown const type %d' % t)
    f.consts = consts
    # nested protos
    n = r.u32()
    f.protos = [parse_proto(r) for _ in range(n)]
    # debug (skip)
    n = r.u32(); r.p += 4 * n
    n = r.u32()
    for _ in range(n):
        r.lua_str(); r.u32(); r.u32()
    n = r.u32()
    for _ in range(n):
        r.lua_str()
    return f


def parse_chunk(data: bytes) -> Proto:
    r = Reader(data)
    sig = r.d[:4]; r.p = 4
    assert sig == b'\x1bLua', 'not a lua chunk'
    ver = r.u8(); assert ver == 0x51, 'not lua 5.1'
    r.u8()  # format
    endian = r.u8(); assert endian == 1, 'big endian not supported'
    sz_int, sz_szt, sz_ins, sz_num = r.u8(), r.u8(), r.u8(), r.u8()
    assert (sz_int, sz_szt, sz_ins, sz_num) == (4, 8, 4, 8), 'nonstandard sizes'
    r.u8()  # integral flag
    return parse_proto(r)


# ---- Lua 5.1 opcode table (order matters) ----
OPCODES = ['MOVE','LOADK','LOADBOOL','LOADNIL','GETUPVAL','GETGLOBAL','GETTABLE',
           'SETGLOBAL','SETUPVAL','SETTABLE','NEWTABLE','SELF','ADD','SUB','MUL',
           'DIV','MOD','POW','UNM','NOT','LEN','CONCAT','JMP','EQ','LT','LE','TEST',
           'TESTSET','CALL','TAILCALL','RETURN','FORLOOP','TFORLOOP','SETLIST',
           'CLOSE','CLOSURE','VARARG']

def decode(instr):
    op = instr & 0x3F
    a = (instr >> 6) & 0xFF
    c = (instr >> 14) & 0x1FF
    b = (instr >> 23) & 0x1FF
    bx = instr >> 14
    return OPCODES[op], a, b, c, bx
