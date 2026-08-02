# -*- coding: utf-8 -*-
"""Restore m_HorizontalAdvance of ORIGINAL (non-baked) glyphs after the
blanket x0.80 scale_advances pass: original glyphs (Latin, digits,
punctuation) get x1.25 back to their factory values, baked Cyrillic and
other baked-only glyphs keep the tightened x0.80.

Usage: python restore_latin.py <dist_bundle> <orig_bundle> <out_dir> [Asset1,Asset2]
"""
import os, sys
import UnityPy

FACTOR = 1.25  # 1/0.80


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
    dist, orig, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    names = sys.argv[4].split(',') if len(sys.argv) > 4 else None
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(dist)
    targets = []
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        targets.append(tt['m_Name'])
    orig_u = orig_unicodes(orig, set(targets))
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        keep = orig_u.get(tt['m_Name'], set())
        gmap = {g['m_Index']: g for g in tt['m_GlyphTable']}
        n = 0
        for c in tt['m_CharacterTable']:
            if c['m_Unicode'] not in keep:
                continue  # запечённый глиф (кириллица и пр.) — оставляем ужатым
            g = gmap.get(c['m_GlyphIndex'])
            if not g:
                continue
            m = g['m_Metrics']
            m['m_HorizontalAdvance'] = float(m['m_HorizontalAdvance'] * FACTOR)
            n += 1
        o.save_typetree(tt)
        print('%s: restored %d original advances x%.3f' % (tt['m_Name'], n, FACTOR))
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
