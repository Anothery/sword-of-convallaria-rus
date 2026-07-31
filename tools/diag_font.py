# -*- coding: utf-8 -*-
"""Deep diagnostic of a TMP font bundle: geometry conventions, char table
integrity, texture settings. Compare original vs baked glyphs.

Usage: python diag_font.py <bundle> [--dump-prefix P]
"""
import os
import sys

import numpy as np
from PIL import Image
import UnityPy

CYR_LO, CYR_HI = 0x0400, 0x0460


def analyze(bundle, dump_prefix=None):
    print('=' * 78)
    print('BUNDLE: %s' % bundle)
    env = UnityPy.load(bundle)
    textures = {}
    monos = []
    for o in env.objects:
        if o.type.name == 'Texture2D':
            textures[o.path_id] = o
        elif o.type.name == 'MonoBehaviour':
            monos.append(o)

    for t in textures.values():
        d = t.read()
        attrs = {k: getattr(d, k) for k in
                 ('m_Name', 'm_Width', 'm_Height', 'm_TextureFormat', 'm_MipCount', 'm_CompleteImageSize')
                 if hasattr(d, k)}
        print('TEX pid=%d %s' % (t.path_id, attrs))

    for o in monos:
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt:
            continue
        name = tt['m_Name']
        gt = tt['m_GlyphTable']
        ct = tt['m_CharacterTable']
        print('-' * 70)
        print('FONT %s  pt=%s atlasPad=%s  glyphs=%d chars=%d' % (
            name, tt['m_FaceInfo'].get('m_PointSize'), tt.get('m_AtlasPadding'),
            len(gt), len(ct)))
        print('  face keys: %s' % {k: v for k, v in tt['m_FaceInfo'].items() if not k.startswith('m_FamilyName')})
        print('  font keys: %s' % [k for k in tt.keys() if 'Scale' in k or 'Padding' in k or 'Mode' in k])

        # --- char table integrity ---
        unis = [c['m_Unicode'] for c in ct]
        if unis != sorted(unis):
            bad = sum(1 for i in range(1, len(unis)) if unis[i] < unis[i - 1])
            print('  !! CHAR TABLE NOT SORTED (%d inversions)' % bad)
        dupes = {u for u in unis if unis.count(u) > 1}
        if dupes:
            print('  !! DUPLICATE UNICODES: %s' % sorted(['U+%04X' % u for u in dupes])[:40])
        gidx = [g['m_Index'] for g in gt]
        if len(set(gidx)) != len(gidx):
            print('  !! DUPLICATE GLYPH INDICES')
        gmap = {g['m_Index']: g for g in gt}
        missing = [c['m_Unicode'] for c in ct if c['m_GlyphIndex'] not in gmap]
        if missing:
            print('  !! CHARS -> MISSING GLYPH: %s' % ['U+%04X' % u for u in missing[:20]])

        # --- atlas refs ---
        refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        atlases = []
        for r in refs:
            if r in textures:
                try:
                    atlases.append(np.array(textures[r].read().image.getchannel('A')))
                except Exception:
                    pass
        if not atlases:
            continue
        H, W = atlases[0].shape
        print('  atlas0=%dx%d n_atlases=%d' % (W, H, len(atlases)))

        # --- geometry: original vs cyrillic ---
        def geom(g, uni):
            r, m = g['m_GlyphRect'], g['m_Metrics']
            ai = g.get('m_AtlasIndex', 0)
            if ai >= len(atlases) or r['m_Width'] <= 0:
                return None
            a = atlases[ai]
            Hh = a.shape[0]
            y0 = Hh - r['m_Y'] - r['m_Height']
            reg = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']]
            ink = reg > 16
            if ink.any():
                ys, xs = np.nonzero(ink)
                halo = (xs.min(), reg.shape[1] - xs.max() - 1,
                        ys.min(), reg.shape[0] - ys.max() - 1)
                inkw, inkh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
            else:
                halo = None
                inkw = inkh = 0
            return dict(ai=ai, rw=r['m_Width'], rh=r['m_Height'],
                        mw=m['m_Width'], mh=m['m_Height'],
                        dw=r['m_Width'] - m['m_Width'], dh=r['m_Height'] - m['m_Height'],
                        halo=halo, inkw=inkw, inkh=inkh,
                        scale=g.get('m_Scale'), bx=m['m_HorizontalBearingX'],
                        by=m['m_HorizontalBearingY'])

        cyr_u = {c['m_Unicode'] for c in ct if CYR_LO <= c['m_Unicode'] <= CYR_HI}
        rows_o, rows_c = [], []
        for c in ct:
            g = gmap.get(c['m_GlyphIndex'])
            if g is None:
                continue
            geo = geom(g, c['m_Unicode'])
            if geo is None:
                continue
            (rows_c if c['m_Unicode'] in cyr_u else rows_o).append((c['m_Unicode'], geo))

        def summ(rows, label):
            if not rows:
                return
            dws = [g['dw'] for _, g in rows]
            dhs = [g['dh'] for _, g in rows]
            hl = [g['halo'][0] for _, g in rows if g['halo']]
            hr = [g['halo'][1] for _, g in rows if g['halo']]
            ht = [g['halo'][2] for _, g in rows if g['halo']]
            hb = [g['halo'][3] for _, g in rows if g['halo']]
            import statistics as st
            print('  %s n=%d  dW=%.2f..%.2f med=%.2f  dH=%.2f..%.2f med=%.2f' % (
                label, len(rows), min(dws), max(dws), st.median(dws),
                min(dhs), max(dhs), st.median(dhs)))
            if hl:
                print('     halo L=%.1f R=%.1f T=%.1f B=%.1f (medians)' % (
                    st.median(hl), st.median(hr), st.median(ht), st.median(hb)))
                print('     halo ranges L[%d..%d] R[%d..%d] T[%d..%d] B[%d..%d]' % (
                    min(hl), max(hl), min(hr), max(hr), min(ht), max(ht), min(hb), max(hb)))
            # ink size vs metrics size residual
            resw = [g['inkw'] - g['mw'] for _, g in rows if g['halo']]
            resh = [g['inkh'] - g['mh'] for _, g in rows if g['halo']]
            if resw:
                print('     ink-metrics W: min=%.1f med=%.1f max=%.1f | H: min=%.1f med=%.1f max=%.1f' % (
                    min(resw), st.median(resw), max(resw),
                    min(resh), st.median(resh), max(resh)))

        summ(rows_o, 'ORIG ')
        summ(rows_c, 'CYRIL')

        # --- rect overlap / min gap (atlas 0) ---
        rects = [(g['m_GlyphRect'], g.get('m_AtlasIndex', 0)) for g in gt]
        r0 = [r for r, ai in rects if ai == 0 and r['m_Width'] > 0]
        overlap = 0
        mingap = 99
        for i in range(len(r0)):
            for j in range(i + 1, len(r0)):
                a, b = r0[i], r0[j]
                ox = min(a['m_X'] + a['m_Width'], b['m_X'] + b['m_Width']) - max(a['m_X'], b['m_X'])
                oy = min(a['m_Y'] + a['m_Height'], b['m_Y'] + b['m_Height']) - max(a['m_Y'], b['m_Y'])
                if ox > 0 and oy > 0:
                    overlap += 1
                gap = max(max(a['m_X'], b['m_X']) - min(a['m_X'] + a['m_Width'], b['m_X'] + b['m_Width']),
                          max(a['m_Y'], b['m_Y']) - min(a['m_Y'] + a['m_Height'], b['m_Y'] + b['m_Height']))
                if gap < mingap:
                    mingap = gap
        print('  atlas0 rects=%d overlaps=%d min_gap=%d' % (len(r0), overlap, mingap))

        # --- dump specific glyphs ---
        if dump_prefix:
            for cp, tag in ((0x0420, 'ER'), (0x0050, 'P'), (0x041B, 'EL'), (0x0430, 'a_cyr')):
                ent = next((c for c in ct if c['m_Unicode'] == cp), None)
                if not ent:
                    continue
                g = gmap.get(ent['m_GlyphIndex'])
                r = g['m_GlyphRect']
                ai = g.get('m_AtlasIndex', 0)
                if ai >= len(atlases):
                    continue
                a = atlases[ai]
                Hh = a.shape[0]
                y0 = Hh - r['m_Y'] - r['m_Height']
                x0, y1 = r['m_X'], y0
                pad = 12
                reg = a[max(0, y0 - pad):y0 + r['m_Height'] + pad,
                        max(0, x0 - pad):x0 + r['m_Width'] + pad]
                Image.fromarray(reg).resize((reg.shape[1] * 4, reg.shape[0] * 4),
                                            Image.NEAREST).save(
                    '%s_%s_%s.png' % (dump_prefix, name, tag))
                print('  dump U+%04X %s: rect=%s ai=%d metrics=%s scale=%s' % (
                    cp, tag, r, ai, g['m_Metrics'], g.get('m_Scale')))


if __name__ == '__main__':
    dump = None
    args = []
    for a in sys.argv[1:]:
        if a.startswith('--dump-prefix='):
            dump = a.split('=', 1)[1]
        else:
            args.append(a)
    for b in args:
        analyze(b, dump)
