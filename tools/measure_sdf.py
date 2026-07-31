# -*- coding: utf-8 -*-
"""Measure the REAL SDF/bitmap convention of original atlas glyphs:
profile across straight edges, rect vs metrics relation, material props."""
import sys, os
import numpy as np
import UnityPy

def load_font(bundle, want):
    env = UnityPy.load(bundle)
    textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}
    mats = {}
    for o in env.objects:
        if o.type.name == 'Material':
            try:
                tt = o.read_typetree()
                mats[tt['m_Name']] = tt
            except Exception:
                pass
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or tt['m_Name'] != want:
            continue
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        atlases = [np.array(textures[r].read().image.getchannel('A')) for r in refs if r in textures]
        return tt, atlases, mats
    return None, None, mats

def region(atlas, r):
    H = atlas.shape[0]
    y0 = H - r['m_Y'] - r['m_Height']
    return atlas[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']], y0

def profile_report(tt, atlases, cp):
    gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
    ent = next((c for c in tt['m_CharacterTable'] if c['m_Unicode'] == cp), None)
    if not ent:
        print('U+%04X not present' % cp); return
    g = gmap[ent['m_GlyphIndex']]
    r, m = g['m_GlyphRect'], g['m_Metrics']
    reg, _ = region(atlases[g.get('m_AtlasIndex', 0)], r)
    print('U+%04X %r rect=%dx%d metrics w=%.2f h=%.2f bx=%.2f by=%.2f adv=%.2f' % (
        cp, chr(cp), r['m_Width'], r['m_Height'], m['m_Width'], m['m_Height'],
        m['m_HorizontalBearingX'], m['m_HorizontalBearingY'], m['m_HorizontalAdvance']))
    # horizontal profile through middle rows: find a row with long flat top
    mid = reg[reg.shape[0] // 3: 2 * reg.shape[0] // 3]
    rowscores = [(np.sum(row > 200), i) for i, row in enumerate(mid)]
    rowscores.sort(reverse=True)
    ri = rowscores[0][1]
    row = mid[ri].astype(int)
    print(' row profile (mid):', ' '.join('%3d' % v for v in row))
    # vertical profile through middle col
    col = reg[:, reg.shape[1] // 2].astype(int)
    print(' col profile (mid):', ' '.join('%3d' % v for v in col))
    # gradient estimate at edges where value crosses 128
    for lbl, prof in (('row', row), ('col', col)):
        cr = [i for i in range(1, len(prof)) if (prof[i-1] - 128) * (prof[i] - 128) < 0]
        for i in cr:
            slope = prof[i] - prof[i-1]
            print('  %s crosses 128 between px %d(%d)->%d(%d) slope=%d/px' % (lbl, i-1, prof[i-1], i, prof[i], slope))
    print('  edge col values: L=%d R=%d | edge row: T=%d B=%d' % (reg[:,0].max(), reg[:,-1].max(), reg[0,:].max(), reg[-1,:].max()))
    print('  value histogram:', np.histogram(reg, bins=[0,8,16,32,64,96,112,128,144,160,192,224,256])[0])

for bundle, want, cps in [
    ('orig_en/fonts/font_global.unity3d', 'SDFFont_sys', [0x48, 0x49, 0x50, 0x67]),  # H I P g
    ('orig_en/fonts/font_en.unity3d', None, []),
]:
    if want is None:
        env = UnityPy.load(bundle)
        for o in env.objects:
            if o.type.name == 'MonoBehaviour':
                tt = o.read_typetree()
                if 'm_GlyphTable' in tt:
                    print(bundle, '->', tt['m_Name'], 'glyphs', len(tt['m_GlyphTable']), 'renderMode', tt.get('m_AtlasRenderMode'))
        continue
    tt, atlases, mats = load_font(bundle, want)
    print('== %s :: %s renderMode=%s ==' % (bundle, want, tt.get('m_AtlasRenderMode')))
    for name, mt in mats.items():
        props = {}
        sp = mt.get('m_SavedProperties', {})
        for k, v in sp.get('m_Floats', []):
            if 'Gradient' in k or 'Scale' in k or 'Outline' in k or 'Underlay' in k or 'Face' in k or 'Weight' in k:
                props[k] = v
        print('  MAT %s shader_pid=%s floats=%s' % (name, mt['m_Shader']['m_PathID'], props))
    for cp in cps:
        profile_report(tt, atlases, cp)
