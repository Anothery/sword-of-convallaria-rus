# -*- coding: utf-8 -*-
"""Bake Cyrillic glyphs into SoC TMP (SDF) font assets. v2

v2 fixes the SDF convention after precise measurement of the original
atlases (see DEVELOPER.md):
  * atlas raster scale ~= 1.0 px per pt (metrics full pt);
    calibrated PER FONT from original glyphs (v=128 outline crossings);
  * SDF slope calibrated per font (32/px @36pt, ~25.5/px @48pt);
  * rect = tight bbox of the v>0 region (ramp reaches ~0 at rect edges,
    NO extra zero margin inside the rect).

Usage: python bake_cyrillic.py <font_bundle> <out_dir> [asset1,asset2 ...]
       [AssetName=path.ttf ...] [--tight] [--single]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt, binary_dilation
import UnityPy

BASE = os.path.dirname(os.path.abspath(__file__))
CYR = [c for c in range(0x0400, 0x0460)]  # U+0400..U+045F
RUS = [c for c in list(range(0x0410, 0x0430)) + list(range(0x0430, 0x0450)) + [0x0401, 0x0451]]
EXTRA = [ord(c) for c in '©«·»×´–—…‰※№→−≤≥①②③■▲▼♠♣♥♦♪']
SUP = 8          # supersample factor
GAP = 4          # min gap between glyph cells in atlas (original min_gap=7)


# ---------------------------------------------------------------- calibration

def _crossings(prof):
    """Fractional positions where profile crosses 128."""
    idx = np.nonzero(np.diff((prof > 128).astype(np.int8)))[0]
    out = []
    for i in idx:
        v0, v1 = float(prof[i]), float(prof[i + 1])
        t = (128.0 - v0) / (v1 - v0) if v1 != v0 else 0.5
        out.append((i + t, abs(v1 - v0)))
    return out


def calibrate(tt, atlases):
    """Measure (raster_scale, sdf_slope) of the original atlas.

    raster_scale = ink bbox (v>=128) span in atlas px / metrics span.
    Measured over ALL glyphs (median): mid-row crossings used before gave
    ~0.77 and were WRONG — the true convention is ~1.0 px per pt.
    sdf_slope = |dv/dx| at v=128 crossings (32/px for 36pt fonts).
    """
    ratios, slopes = [], []
    for g in tt['m_GlyphTable']:
        r, m = g['m_GlyphRect'], g['m_Metrics']
        if r['m_Width'] <= 2 or m['m_Width'] < 6 or m['m_Height'] < 6:
            continue
        ai = g.get('m_AtlasIndex', 0)
        if ai >= len(atlases):
            continue
        a = atlases[ai]
        y0 = a.shape[0] - r['m_Y'] - r['m_Height']
        reg = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']]
        if reg.size == 0 or not (reg >= 128).any():
            continue
        ys, xs = np.nonzero(reg >= 128)
        iw = xs.max() - xs.min() + 1
        ih = ys.max() - ys.min() + 1
        ratios.append(iw / m['m_Width'])
        ratios.append(ih / m['m_Height'])
        crx = _crossings(reg[reg.shape[0] // 2])
        cry = _crossings(reg[:, reg.shape[1] // 2])
        slopes += [s for _, s in crx + cry if 5 < s < 64]
    if not ratios or not slopes:
        return None
    scale = float(np.median(ratios))
    slope = float(np.median(slopes))
    return scale, slope


# ---------------------------------------------------------------- SDF render

def sdf_bitmap(font_pil_big, ch, size_px, slope):
    """Render ch at SUP x size; return SDF uint8 cropped to bbox(v>0).

    v = clip(128 + slope * d), d = signed distance in final atlas px.
    The crop keeps the full negative ramp (outline -> v~0 at rect edge).
    """
    spread = 128.0 / slope
    big = int(size_px * SUP) + 64 + 2 * int(spread * SUP) + 16
    off = 32 + int(spread * SUP) + 8
    img = Image.new('L', (big, big), 0)
    dr = ImageDraw.Draw(img)
    dr.text((off, off), ch, font=font_pil_big, fill=255)
    arr = np.array(img) > 127
    if not arr.any():
        return None
    ys, xs = np.nonzero(arr)
    pad = int(spread * SUP) + SUP
    y0 = max(0, ys.min() - pad)
    y1 = min(arr.shape[0], ys.max() + 1 + pad)
    x0 = max(0, xs.min() - pad)
    x1 = min(arr.shape[1], xs.max() + 1 + pad)
    mask = arr[y0:y1, x0:x1]
    din = distance_transform_edt(mask)
    dout = distance_transform_edt(~mask)
    d = (din - dout) / SUP           # signed distance in final px
    v = np.clip(128.0 + slope * d, 0, 255)
    h, w = v.shape
    h2, w2 = h // SUP * SUP, w // SUP * SUP
    v = v[:h2, :w2].reshape(h2 // SUP, SUP, w2 // SUP, SUP).mean(axis=(1, 3))
    v = v.astype(np.uint8)
    # crop to bbox(v>=120): devs crop rects at the SDF centerline (v~128),
    # NOT at v>0 — full-ramp rects render the glyph ~3-4px too low in game
    nz = v >= 120
    ys, xs = np.nonzero(nz)
    v = v[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return v, v.shape[1], v.shape[0]


def bake(mb_obj, tex_objs, font_ttf_path, charset, log=print, dscale=1.0):
    """tex_objs: list of Texture2D object readers (atlas index 0..n).
    dscale: design-scale correction for cases where the source TTF's
    design differs from the atlas' original glyphs (e.g. baking
    Font_sys_en Cyrillic into the Font_sys atlas: ~0.954)."""
    tt = mb_obj.read_typetree()
    texs = [t.read() for t in tex_objs]
    atlases = [np.array(t.image.getchannel('A')) for t in texs]
    pt = tt['m_FaceInfo']['m_PointSize']

    cal = calibrate(tt, atlases)
    if cal is None:
        log('CALIBRATION FAILED (no glyphs?), using scale=0.75 slope=32')
        rscale, slope = 0.75, 32.0
    else:
        rscale, slope = cal
    log('calibration: raster_scale=%.4f slope=%.2f/px (spread=%.2f px)' % (
        rscale, slope, 128.0 / slope))

    from fontTools.ttLib import TTFont
    from fontTools.pens.boundsPen import BoundsPen
    ft = TTFont(font_ttf_path)
    upem = ft['head'].unitsPerEm
    cmap = ft.getBestCmap()
    gset = ft.getGlyphSet()
    hmtx = ft['hmtx']
    scale = pt / upem  # FULL scale for metrics (game convention)

    def glyph_bounds(gname):
        pen = BoundsPen(gset)
        gset[gname].draw(pen)
        if pen.bounds is None:
            return None
        return pen.bounds  # xMin, yMin, xMax, yMax

    # design-scale correction (source TTF design vs atlas' original design)
    if dscale == 'auto':
        # ratio: original Latin 'a' bearY in atlas / Cyrillic 'а' yMax from TTF
        cmap_tt = {c['m_Unicode']: c['m_GlyphIndex'] for c in tt['m_CharacterTable']}
        gmap_tt = {g['m_Index']: g for g in tt['m_GlyphTable']}
        orig_a = gmap_tt[cmap_tt[0x61]]['m_Metrics']['m_HorizontalBearingY']
        cyr_a_top = glyph_bounds(cmap[0x430])[3] * scale
        dscale = orig_a / cyr_a_top
    if dscale != 1.0:
        scale *= dscale
        log('dscale=%.4f applied' % dscale)

    # sanity: metrics convention check against an existing char
    have = {c['m_Unicode'] for c in tt['m_CharacterTable']}
    if 65 in have:
        gidx = next(c for c in tt['m_CharacterTable'] if c['m_Unicode'] == 65)
        gm = next(g for g in tt['m_GlyphTable'] if g['m_Index'] == gidx['m_GlyphIndex'])
        adv = hmtx[cmap[65]][0] * scale
        log('calib A: bundle adv=%.3f computed=%.3f' % (
            gm['m_Metrics']['m_HorizontalAdvance'], adv))

    font_big = ImageFont.truetype(font_ttf_path, max(8, round(pt * rscale * dscale * SUP)))
    raster_px = pt * rscale * dscale

    next_index = max(g['m_Index'] for g in tt['m_GlyphTable']) + 1

    # --- per-atlas occupancy state (integral image over occupied mask) ---
    # Reserve existing glyph RECTS (not just ink): a new glyph placed inside
    # an empty corner of an existing rect would corrupt that glyph's render.
    occs, integs = [], []
    for ai, a in enumerate(atlases):
        occ = binary_dilation(a > 0, iterations=GAP)
        Hh = a.shape[0]
        for g in tt['m_GlyphTable']:
            if g.get('m_AtlasIndex', 0) != ai:
                continue
            r = g['m_GlyphRect']
            if r['m_Width'] <= 0:
                continue
            y0 = Hh - r['m_Y'] - r['m_Height']
            occ[max(0, y0 - GAP):y0 + r['m_Height'] + GAP,
                max(0, r['m_X'] - GAP):r['m_X'] + r['m_Width'] + GAP] = True
        occs.append(occ)
        integs.append(np.pad(occ.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0))))

    def find_spot(w, h):
        for ai in range(len(atlases)):
            Hh, Ww = atlases[ai].shape
            if w > Ww or h > Hh:
                continue
            integ = integs[ai]
            for y in range(0, Hh - h + 1, 1):
                for x in range(0, Ww - w + 1, 1):
                    s = integ[y + h, x + w] - integ[y, x + w] - integ[y + h, x] + integ[y, x]
                    if s == 0:
                        return ai, x, y
        return None

    def mark(ai, x, y, w, h):
        Hh, Ww = atlases[ai].shape
        occs[ai][max(0, y - GAP):min(Hh, y + h + GAP),
                 max(0, x - GAP):min(Ww, x + w + GAP)] = True
        integs[ai] = np.pad(occs[ai].astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    # render all glyphs first, place tallest-first for better packing
    pending = []
    for cp in charset:
        if cp in have or cp not in cmap:
            continue
        ch = chr(cp)
        gname = cmap[cp]
        adv, lsb = hmtx[gname]
        bounds = glyph_bounds(gname)
        if bounds is None:
            continue
        xMin, yMin, xMax, yMax = bounds
        mw = (xMax - xMin) * scale
        mh = (yMax - yMin) * scale
        if mw <= 0 or mh <= 0:
            continue
        res = sdf_bitmap(font_big, ch, raster_px, slope)
        if res is None:
            continue
        bmp, bw, bh = res
        pending.append((cp, adv, lsb, xMin, yMin, xMax, yMax, mw, mh, bmp, bw, bh))
    pending.sort(key=lambda r: -r[11])

    added = 0
    for cp, adv, lsb, xMin, yMin, xMax, yMax, mw, mh, bmp, bw, bh in pending:
        cell_w, cell_h = bw, bh
        spot = find_spot(cell_w, cell_h)
        if spot is None:
            log('NO SPACE for cp=%X (added %d)' % (cp, added))
            continue
        ai, cur_x, cur_y = spot
        Hh = atlases[ai].shape[0]
        atlases[ai][cur_y:cur_y + bh, cur_x:cur_x + bw] = bmp
        mark(ai, cur_x, cur_y, cell_w, cell_h)
        rect_y = Hh - (cur_y + cell_h)  # bottom-left origin
        tt['m_GlyphTable'].append({
            'm_Index': next_index,
            'm_Metrics': {
                'm_Width': float(mw), 'm_Height': float(mh),
                'm_HorizontalBearingX': float(lsb * scale),
                'm_HorizontalBearingY': float(yMax * scale),
                'm_HorizontalAdvance': float(adv * scale),
            },
            'm_GlyphRect': {'m_X': int(cur_x), 'm_Y': int(rect_y),
                            'm_Width': int(cell_w), 'm_Height': int(cell_h)},
            'm_Scale': 1.0, 'm_AtlasIndex': int(ai),
        })
        tt['m_CharacterTable'].append({
            'm_ElementType': 1, 'm_Unicode': int(cp),
            'm_GlyphIndex': int(next_index), 'm_Scale': 1.0,
        })
        tt['m_UsedGlyphRects'].append({'m_X': int(cur_x), 'm_Y': int(rect_y),
                                       'm_Width': int(cell_w), 'm_Height': int(cell_h)})
        next_index += 1
        added += 1
    log('added %d glyphs' % added)

    # prevent runtime dynamic-add from tripping over stale free rects (hang fix)
    tt['m_FreeGlyphRects'] = []

    # write back
    for ai, t in enumerate(texs):
        Hh, Ww = atlases[ai].shape
        out_img = Image.merge('RGBA', (Image.new('L', (Ww, Hh), 0),) * 3 + (Image.fromarray(atlases[ai]),))
        t.image = out_img
        t.save()
    mb_obj.save_typetree(tt)
    return added


def main():
    bundle = sys.argv[1]
    out_dir = sys.argv[2]
    names = sys.argv[3].split(',') if len(sys.argv) > 3 else None
    # optional: AssetName=path.ttf overrides for source fonts
    tight = '--tight' in sys.argv
    single = '--single' in sys.argv
    dscale = 1.0
    for a in sys.argv[4:]:
        if a.startswith('--dscale'):
            v = a.split('=', 1)[1]
            dscale = v if v == 'auto' else float(v)
    overrides = {}
    for a in [x for x in sys.argv[4:] if not x.startswith('--')]:
        k, v = a.split('=', 1)
        overrides[k] = v
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)

    # map TTF fonts by path id
    fonts = {}
    textures = {}
    monos = {}
    for o in env.objects:
        if o.type.name == 'Font':
            d = o.read()
            data = d.m_FontData
            p = os.path.join(BASE, 'fonts', 'extracted_%s.ttf' % d.m_Name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if not os.path.exists(p):
                open(p, 'wb').write(bytes(data))
            fonts[o.path_id] = p
        elif o.type.name == 'Texture2D':
            textures[o.path_id] = o
        elif o.type.name == 'MonoBehaviour':
            monos[o.read().m_Name] = o

    for name, o in monos.items():
        if names and name not in names:
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt:
            continue
        src = tt['m_SourceFontFile']['m_PathID']
        atlas_refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
        font_path = overrides.get(name) or fonts.get(src)
        tex_objs = [textures[r] for r in atlas_refs if r in textures]
        if single:
            tex_objs = tex_objs[:1]
        if not font_path or not tex_objs:
            print('SKIP %s (refs missing: font %s, atlases %d/%d)' % (name, bool(font_path), len(tex_objs), len(atlas_refs)))
            continue
        print('== baking %s (font %s, atlases %d)' % (name, os.path.basename(font_path), len(tex_objs)))
        charset = RUS + EXTRA if tight else CYR + EXTRA
        # dscale применяем только к ассетам с чужим дизайном TTF (override)
        ds = dscale if name in overrides else 1.0
        bake(o, tex_objs, font_path, charset, dscale=ds)

    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
