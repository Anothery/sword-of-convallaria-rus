# -*- coding: utf-8 -*-
"""Sim render with character tracking (normalSpacingOffset emulation)."""
import sys
import numpy as np
from PIL import Image
import UnityPy

bundle, font_name, out = sys.argv[1], sys.argv[2], sys.argv[3]
tracking = float(sys.argv[4])
lines = sys.argv[5:]
env = UnityPy.load(bundle)
textures = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D'}
for o in env.objects:
    if o.type.name != 'MonoBehaviour':
        continue
    tt = o.read_typetree()
    if 'm_GlyphTable' not in tt or tt['m_Name'] != font_name:
        continue
    refs = [a['m_PathID'] for a in tt['m_AtlasTextures']]
    atlases = [np.array(textures[r].read().image.getchannel('A')) for r in refs if r in textures]
    gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
    cmap = {c['m_Unicode']: c['m_GlyphIndex'] for c in tt['m_CharacterTable']}
    R = 0.75
    spread = 128.0 / 31.0
    imgs = []
    for text in lines:
        W, H = 1600, 90
        canvas = np.zeros((H, W), np.float32)
        pen = 16.0
        base = 62.0
        for ch in text:
            cp = ord(ch)
            if cp == 32:
                pen += 8 + tracking * R; continue
            gi = cmap.get(cp)
            if gi is None:
                pen += 15; continue
            g = gmap[gi]
            r, m = g['m_GlyphRect'], g['m_Metrics']
            a = atlases[g.get('m_AtlasIndex', 0)]
            y0 = a.shape[0] - r['m_Y'] - r['m_Height']
            bmp = a[y0:y0 + r['m_Height'], r['m_X']:r['m_X'] + r['m_Width']].astype(np.float32)
            x = int(round(pen + m['m_HorizontalBearingX'] * R - spread))
            y = int(round(base - m['m_HorizontalBearingY'] * R - spread))
            sub = canvas[max(0, y):y + bmp.shape[0], max(0, x):x + bmp.shape[1]]
            sh, sw = sub.shape
            np.maximum(sub, bmp[:sh, :sw], out=sub)
            pen += (m['m_HorizontalAdvance'] + tracking) * R
        imgs.append(canvas[:, :int(pen) + 30])
    Ht = sum(i.shape[0] for i in imgs) + 14 * len(imgs)
    Wt = max(i.shape[1] for i in imgs)
    outimg = np.zeros((Ht, Wt), np.uint8)
    yy = 0
    for i in imgs:
        outimg[yy:yy + i.shape[0], :i.shape[1]] = np.clip(i, 0, 255).astype(np.uint8)
        yy += i.shape[0] + 14
    Image.fromarray(outimg).save(out)
    print('saved', out)
    break
