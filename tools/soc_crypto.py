# -*- coding: utf-8 -*-
"""Decryption for Sword of Convallaria Lua/TextAsset payloads.

Algorithm credit: github.com/shalzuth/SwordOfConvallariaResearch (Dumper/Utils/Lua.cs)
Two stages:
  1) XOR decrypt (fixed 17-byte key, byte0 ^= 0x35)
  2) LuaZReadDecrypt -> restores a standard Lua 5.1 bytecode chunk (\\x1bLua\\x51)
"""

XOR_KEY = bytes([0x17, 0xF1, 0xC3, 0x55, 0x78, 0x64, 0x39, 0x40,
                 0x42, 0x77, 0x59, 0x12, 0x33, 0xCB, 0x7B, 0xB9, 0x35])


def xor_decrypt(data: bytes) -> bytes:
    buf = bytearray(data)
    buf[0] ^= 0x35
    klen = len(XOR_KEY)
    for i in range(1, len(buf)):
        buf[i] ^= XOR_KEY[(i - 1) % klen]
    return bytes(buf)


def luaz_read_decrypt(buffer: bytes) -> bytes:
    """Second stage. Produces a standard Lua 5.1 bytecode chunk."""
    buf = bytearray(buffer)
    for i in range(2, len(buf)):
        key = (0x20210507 * i) & 0xFFFFFFFFFFFFFFFF
        idx = i % 3
        if idx == 1:
            buf[i] = ((((key >> 16) & 0xFF) - i) & 0xFF) ^ buf[i]
        elif idx == 2:
            buf[i] = (((key >> 21) | i) & 0xFF) ^ buf[i]
        else:
            buf[i] = (((key >> 28) + (key & 1) + i) & 0xFF) ^ buf[i]
    buf[0] = 0x1B
    buf[1] = ord('L')
    buf[2] = ord('u')
    buf[3] = ord('a')
    buf[4] = 0x51
    return bytes(buf)


def full_decrypt(data: bytes) -> bytes:
    """Raw TextAsset bytes -> Lua 5.1 bytecode chunk."""
    return luaz_read_decrypt(xor_decrypt(data))


# True chunk header used by the game's custom VM (recovered from pristine files):
# \x01 "XDI" \x01 — repo's forced \x1bLua\x51 was only for unluac compatibility.
XDI_HEADER = bytes([0x01, 0x58, 0x44, 0x49, 0x01])


def luaz_read_encrypt(buffer: bytes) -> bytes:
    """Stage 2 for re-encryption: same XOR, but WITHOUT forcing the header."""
    buf = bytearray(buffer)
    for i in range(2, len(buf)):
        key = (0x20210507 * i) & 0xFFFFFFFFFFFFFFFF
        idx = i % 3
        if idx == 1:
            buf[i] = ((((key >> 16) & 0xFF) - i) & 0xFF) ^ buf[i]
        elif idx == 2:
            buf[i] = (((key >> 21) | i) & 0xFF) ^ buf[i]
        else:
            buf[i] = (((key >> 28) + (key & 1) + i) & 0xFF) ^ buf[i]
    return bytes(buf)


def full_encrypt(chunk: bytes) -> bytes:
    """Lua chunk -> encrypted TextAsset bytes, byte-exact vs the game format."""
    c = bytearray(chunk)
    c[0:5] = XDI_HEADER
    return xor_decrypt(luaz_read_encrypt(bytes(c)))
