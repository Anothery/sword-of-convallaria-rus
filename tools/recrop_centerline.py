# -*- coding: utf-8 -*-
"""Re-crop baked glyph rects to the DEVS' convention: original glyphs'
m_GlyphRect is cropped at the SDF centerline (v ~= 128), our bake cropped
at v > 0 (full ramp, ~4 extra rows at top) — which makes baked glyphs
render ~3-4 px too low in game.

For every glyph NOT present in the original bundle (i.e. baked by us),
shrink m_GlyphRect to the bbox of pixels with v >= THRESH inside the
current rect. Bitmaps and metrics stay untouched.

Usage: python recrop_centerline.py <bundle> <orig_bundle> <out_dir> [Asset1,Asset2]
"""
import os, sys
import numpy as np
import UnityPy

THRESH = 120  # devs' first row is ~119-142


def orig_unicodes(bundle, names):
    env = UnityPy.load(bundle)
    out = {}
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_CharacterTable' not in tt or tt['m_Name'] not in names:
            continue
        out[tt['m_Name']] = set(c['m_Unicode'] for c in tt['m_CharacterTable'])
    return out


def main():
    bundle, orig, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    names = sys.argv[4].split(',') if len(sys.argv) > 4 else None
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}
    targets = set()
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        targets.add(tt['m_Name'])
    orig_u = orig_unicodes(orig, targets)

    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        keep = orig_u.get(tt['m_Name'], set())
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        atlases = [np.array(textures[r].read().image.getchannel('A'))
                   for r in refs if r in textures]
        if not atlases:
            continue
        gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
        n = skip = 0
        used = tt.get('m_UsedGlyphRects', [])
        for c in tt['m_CharacterTable']:
            if c['m_Unicode'] in keep:
                continue
            g = gmap.get(c['m_GlyphIndex'])
            if not g:
                continue
            r = g['m_GlyphRect']
            if r['m_Width'] <= 0 or r['m_Height'] <= 0:
                continue
            a = atlases[g.get('m_AtlasIndex', 0)]
            H = a.shape[0]
            y0 = H - r['m_Y'] - r['m_Height']
            sub = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']]
            ys, xs = np.where(sub >= THRESH)
            if not len(ys):
                skip += 1
                continue
            ny0, ny1 = int(ys.min()), int(ys.max()) + 1
            nx0, nx1 = int(xs.min()), int(xs.max()) + 1
            if ny0 == 0 and nx0 == 0 and ny1 == sub.shape[0] and nx1 == sub.shape[1]:
                continue  # уже по конвенции
            old = (r['m_X'], r['m_Y'], r['m_Width'], r['m_Height'])
            r['m_X'] = int(r['m_X'] + nx0)
            r['m_Y'] = int(r['m_Y'] + (sub.shape[0] - ny1))  # bottom-left origin
            r['m_Width'] = int(nx1 - nx0)
            r['m_Height'] = int(ny1 - ny0)
            for ur in used:
                if (ur['m_X'], ur['m_Y'], ur['m_Width'], ur['m_Height']) == old:
                    ur['m_X'], ur['m_Y'] = r['m_X'], r['m_Y']
                    ur['m_Width'], ur['m_Height'] = r['m_Width'], r['m_Height']
                    break
            n += 1
        print('%s: re-cropped %d baked rects (skip %d)' % (tt['m_Name'], n, skip))
        o.save_typetree(tt)
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
