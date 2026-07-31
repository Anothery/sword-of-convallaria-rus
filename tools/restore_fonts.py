# -*- coding: utf-8 -*-
"""Remove previously baked Cyrillic/extra glyphs from patched font bundles
(zero their atlas rects, drop char/glyph entries, clear free rects) so the
bundles can be re-baked cleanly.

Usage: python restore_fonts.py <bundle> <out_dir> Asset1,Asset2
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image
import UnityPy
from bake_cyrillic import CYR, EXTRA

CHARSET = set(CYR) | set(EXTRA)


def main():
    bundle, out_dir = sys.argv[1], sys.argv[2]
    names = set(sys.argv[3].split(','))
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}

    for o in env.objects:
        if o.type.name != 'MonoBehaviour' or o.read().m_Name not in names:
            continue
        d = o.read()
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt:
            continue
        atlas_refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        texs = {i: textures[r].read() for i, r in enumerate(atlas_refs) if r in textures}
        atlas_arrays = {i: np.array(t.image.getchannel('A')) for i, t in texs.items()}

        drop_chars = [c for c in tt['m_CharacterTable'] if c['m_Unicode'] in CHARSET]
        drop_idx = {c['m_GlyphIndex'] for c in drop_chars}
        drop_glyphs = [g for g in tt['m_GlyphTable'] if g['m_Index'] in drop_idx]
        for g in drop_glyphs:
            ai = g.get('m_AtlasIndex', 0)
            r = g['m_GlyphRect']
            if ai in atlas_arrays:
                a = atlas_arrays[ai]
                H = a.shape[0]
                y0 = H - r['m_Y'] - r['m_Height']
                a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']] = 0
        print('%s: removing %d chars / %d glyphs' % (d.m_Name, len(drop_chars), len(drop_glyphs)))
        tt['m_CharacterTable'] = [c for c in tt['m_CharacterTable'] if c['m_Unicode'] not in CHARSET]
        tt['m_GlyphTable'] = [g for g in tt['m_GlyphTable'] if g['m_Index'] not in drop_idx]
        drop_rects = {(g['m_GlyphRect']['m_X'], g['m_GlyphRect']['m_Y']) for g in drop_glyphs}
        tt['m_UsedGlyphRects'] = [r for r in tt['m_UsedGlyphRects']
                                  if (r['m_X'], r['m_Y']) not in drop_rects]
        tt['m_FreeGlyphRects'] = []
        for i, t in texs.items():
            a = atlas_arrays[i]
            Hh, Ww = a.shape
            t.image = Image.merge('RGBA', (Image.new('L', (Ww, Hh), 0),) * 3 + (Image.fromarray(a),))
            t.save()
        o.save_typetree(tt)

    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
