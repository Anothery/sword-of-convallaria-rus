# -*- coding: utf-8 -*-
"""Measure atlas raster scale ratio per font asset: v=128 crossing span of
straight-stem glyphs (H, I, E, F, T) vs their metrics width."""
import sys
import numpy as np
import UnityPy

def measure(bundle):
    print('==', bundle)
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        if not any(r in textures for r in refs):
            continue
        atlases = {}
        for r in refs:
            if r in textures:
                try:
                    atlases[r] = np.array(textures[r].read().image.getchannel('A'))
                except Exception:
                    pass
        gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
        ratios = []
        slopes = []
        for cp in (0x48, 0x49, 0x54, 0x46, 0x45, 0x4C):  # H I T F E L
            ent = next((c for c in tt['m_CharacterTable'] if c['m_Unicode'] == cp), None)
            if not ent:
                continue
            g = gmap.get(ent['m_GlyphIndex'])
            r, m = g['m_GlyphRect'], g['m_Metrics']
            ai = g.get('m_AtlasIndex', 0)
            ref = refs[ai] if ai < len(refs) else None
            if ref not in atlases or r['m_Width'] <= 0:
                continue
            a = atlases[ref]
            y0 = a.shape[0] - r['m_Y'] - r['m_Height']
            reg = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']]
            if cp == 0x49:  # I: single stem -> whole row span
                mid = reg[reg.shape[0] // 2].astype(float)
                xs = np.nonzero(mid > 100)[0]
                if len(xs) < 2:
                    continue
                span = None
                # use crossings on widest row
                cr = np.nonzero(np.diff((mid > 128).astype(int)))[0]
                if len(cr) >= 2:
                    span = (cr[-1] - cr[0])
                if span and m['m_Width'] > 0:
                    ratios.append((chr(cp), span / m['m_Width']))
            else:
                # outer crossings of middle row
                mid = reg[reg.shape[0] // 2].astype(float)
                cr = np.nonzero(np.diff((mid > 128).astype(int)))[0]
                if len(cr) >= 2:
                    span = cr[-1] - cr[0]
                    ratios.append((chr(cp), span / m['m_Width']))
                    # slope at first crossing
                    i = cr[0]
                    if 0 < i < len(mid) - 1:
                        slopes.append(mid[i + 1] - mid[i])
        if ratios:
            rs = [v for _, v in ratios]
            print('  %-22s pt=%s ratios=%s -> median %.4f  slopes %s' % (
                tt['m_Name'], tt['m_FaceInfo']['m_PointSize'],
                ['%s:%.3f' % t for t in ratios], float(np.median(rs)),
                ['%.0f' % s for s in slopes[:6]]))

for b in ['orig_en/fonts/font_en.unity3d', 'orig_en/fonts/login_font.unity3d',
          'orig_en/fonts/font_global.unity3d']:
    try:
        measure(b)
    except Exception as e:
        print(b, 'ERR', e)
