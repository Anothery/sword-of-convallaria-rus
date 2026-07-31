# -*- coding: utf-8 -*-
"""Repack a font asset's atlas: move ALL glyphs (original + baked) into a
single atlas texture (shelf packing), rewriting m_GlyphRect/m_UsedGlyphRects
and m_AtlasIndex. Fixes renderers that mishandle m_AtlasIndex>0 and
fragmented atlases.

Usage: python repack_atlas.py <bundle> <out_dir> AssetName
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image
import UnityPy

PAD = 2  # gap between cells


def main():
    bundle, out_dir, name = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}

    for o in env.objects:
        if o.type.name != 'MonoBehaviour' or o.read().m_Name != name:
            continue
        d = o.read()
        tt = o.read_typetree()
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        tex_objs = [textures[r] for r in refs if r in textures]
        atlases = [np.array(t.read().image.getchannel('A')) for t in tex_objs]
        H, W = atlases[0].shape

        # collect glyph bitmaps
        items = []  # (glyph_entry, bitmap)
        for g in tt['m_GlyphTable']:
            ai = g.get('m_AtlasIndex', 0)
            r = g['m_GlyphRect']
            if r['m_Width'] <= 0 or ai >= len(atlases):
                items.append((g, None))
                continue
            a = atlases[ai]
            Hh = a.shape[0]
            y0 = Hh - r['m_Y'] - r['m_Height']
            bmp = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']].copy()
            items.append((g, bmp))

        # sort by height desc, shelf-pack
        with_bmp = [(g, b) for g, b in items if b is not None]
        with_bmp.sort(key=lambda gb: -gb[1].shape[0])
        new_atlas = np.zeros_like(atlases[0])
        x = y = shelf_h = 0
        used = []
        for g, bmp in with_bmp:
            h, w = bmp.shape
            if x + w > W:
                x = 0
                y += shelf_h + PAD
                shelf_h = 0
            if y + h > H:
                print('OVERFLOW: glyph %s does not fit!' % g['m_Index'])
                continue
            new_atlas[y:y + h, x:x + w] = bmp
            rect_y = H - (y + h)
            g['m_GlyphRect'] = {'m_X': int(x), 'm_Y': int(rect_y),
                                'm_Width': int(w), 'm_Height': int(h)}
            g['m_AtlasIndex'] = 0
            used.append({'m_X': int(x), 'm_Y': int(rect_y),
                         'm_Width': int(w), 'm_Height': int(h)})
            x += w + PAD
            shelf_h = max(shelf_h, h)
        tt['m_UsedGlyphRects'] = used
        tt['m_FreeGlyphRects'] = []
        print('%s: repacked %d glyphs into single atlas (fill %.1f%%)' % (
            name, len(used), 100.0 * (new_atlas > 0).sum() / new_atlas.size))

        # write back: atlas 0 = new, other atlases zeroed
        for i, t in enumerate(tex_objs):
            td = t.read()
            Hh, Ww = td.image.size
            arr = new_atlas if i == 0 else np.zeros_like(atlases[i])
            td.image = Image.merge('RGBA', (Image.new('L', (arr.shape[1], arr.shape[0]), 0),) * 3 + (Image.fromarray(arr),))
            td.save()
        o.save_typetree(tt)

    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
