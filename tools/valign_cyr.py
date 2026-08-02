# -*- coding: utf-8 -*-
"""Optical vertical alignment of baked Cyrillic glyphs.

Sim convention (same as sim_track2): glyph rect top lands at
    y = base - bearY*R - spread   (R=0.75, spread=128/slope)
so a glyph's INK top sits at  y + ink_row(rect). We measure ink rows in
the atlas bitmaps and shift m_HorizontalBearingY so each baked glyph's
ink top matches its class anchor from the ORIGINAL Latin glyphs:
    x-height class (TTF yMax <= 620)  -> 'a'
    ascender class (TTF yMax > 620)   -> 'b'
    short i (й, ё)                    -> 'i'  (breve/dots at dot level)
    capitals (uppercase, yMax <= 820) -> 'A'
Corrections < 0.5 sim-px are ignored.

Usage: python valign_cyr.py <bundle> <out_dir> [Asset1,Asset2]
"""
import os, sys
import numpy as np
import UnityPy
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

BASE = os.path.dirname(os.path.abspath(__file__))
R = 0.75
TTF = os.path.join(BASE, 'fonts', 'Font_sys_en.ttf')
TTF_TITLE = os.path.join(BASE, 'fonts', 'FontTitle_sys_en.ttf')

LOWER = set(range(0x430, 0x450)) | {0x451}
UPPER = set(range(0x410, 0x430)) | {0x401}
DOTTED = {0x439, 0x419, 0x451, 0x401}  # й Й ё Ё


def bounds_of(gset, gname):
    pen = BoundsPen(gset)
    gset[gname].draw(pen)
    return pen.bounds


def main():
    bundle, out_dir = sys.argv[1], sys.argv[2]
    names = sys.argv[3].split(',') if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}
    ttf_cache = {}

    def ttf_bounds(cp, title=False):
        key = title
        if key not in ttf_cache:
            f = TTFont(TTF_TITLE if title else TTF)
            ttf_cache[key] = (f.getBestCmap(), f.getGlyphSet())
        cmap, gset = ttf_cache[key]
        if cp not in cmap:
            return None
        return bounds_of(gset, cmap[cp])

    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        is_title = 'Title' in tt['m_Name']
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        atlases = [np.array(textures[r].read().image.getchannel('A'))
                   for r in refs if r in textures]
        gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
        cmap = {c['m_Unicode']: c['m_GlyphIndex'] for c in tt['m_CharacterTable']}
        orig_set = set()
        # slope for this asset: 128/spread; infer spread from a reference glyph
        # ink row = first row with v >= 96 inside rect
        def ink_top(g):
            # центральная линия SDF (v=128) — истинное положение контура,
            # устойчиво к разной ширине рампы у dev/PIL растеризаторов
            a = atlases[g.get('m_AtlasIndex', 0)]
            r = g['m_GlyphRect']
            y0 = a.shape[0] - r['m_Y'] - r['m_Height']
            sub = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']]
            rowmax = sub.max(axis=1).astype(np.float32)
            above = np.where(rowmax >= 128)[0]
            if not len(above):
                return None
            i = int(above[0])
            if i == 0:
                return 0.0
            v0, v1 = rowmax[i - 1], rowmax[i]
            if v1 == v0:
                return float(i)
            return float(i - 1) + (128.0 - v0) / (v1 - v0)

        def pos_top(cp):
            gi = cmap.get(cp)
            if gi is None:
                return None
            g = gmap[gi]
            it = ink_top(g)
            if it is None:
                return None
            return -g['m_Metrics']['m_HorizontalBearingY'] * R + it

        anchors = {}
        for key, cp in [('a', 0x61), ('b', 0x62), ('i', 0x69), ('A', 0x41)]:
            p = pos_top(cp)
            if p is not None:
                anchors[key] = p
        if len(anchors) < 3:
            print('%s: anchors missing %s — skip' % (tt['m_Name'], list(anchors)))
            continue

        n = 0
        for c in tt['m_CharacterTable']:
            cp = c['m_Unicode']
            if not (0x400 <= cp <= 0x45F):
                continue
            g = gmap.get(c['m_GlyphIndex'])
            if not g:
                continue
            b = ttf_bounds(cp, title=is_title)
            if b is None:
                continue
            yMax = b[3]
            if cp in (0x439, 0x419):
                tgt = anchors.get('i')
            elif cp in (0x451, 0x401):
                tgt = anchors.get('i') if cp == 0x451 else anchors.get('A')
            elif cp in UPPER:
                tgt = anchors.get('A') if yMax <= 820 else None
            elif yMax > 620:
                tgt = anchors.get('b')
            else:
                tgt = anchors.get('a')
            if tgt is None:
                continue
            cur = pos_top(cp)
            if cur is None:
                continue
            d_px = cur - tgt  # >0: glyph sits too LOW
            if abs(d_px) < 0.5:
                continue
            m = g['m_Metrics']
            m['m_HorizontalBearingY'] = float(m['m_HorizontalBearingY'] + d_px / R)
            n += 1
            if n <= 12 or abs(d_px) > 1.5:
                print('  %s U+%04X %s: ink dev %+.1fpx -> bearY %+.2f pt' % (
                    tt['m_Name'], cp, chr(cp), d_px, d_px / R))
        print('%s: valign corrected %d glyphs (anchors %s)' % (
            tt['m_Name'], n, {k: round(v, 1) for k, v in anchors.items()}))
        o.save_typetree(tt)
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
