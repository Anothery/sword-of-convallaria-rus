# -*- coding: utf-8 -*-
"""Tighten m_HorizontalAdvance of BAKED-ONLY glyphs (Cyrillic etc.) —
inverse of restore_latin.py: glyphs NOT present in the original bundle's
character table get scaled, original glyphs keep factory advances.

Usage: python tighten_baked.py <bundle> <orig_bundle> <out_dir> <factor> [Asset1,Asset2]
"""
import os, sys
import UnityPy


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
    bundle, orig, out_dir, factor = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    names = sys.argv[5].split(',') if len(sys.argv) > 5 else None
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
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
            if c['m_Unicode'] in keep:
                continue  # оригинальный глиф — не трогаем
            g = gmap.get(c['m_GlyphIndex'])
            if not g:
                continue
            m = g['m_Metrics']
            m['m_HorizontalAdvance'] = float(m['m_HorizontalAdvance'] * factor)
            n += 1
        o.save_typetree(tt)
        print('%s: tightened %d baked advances x%.3f' % (tt['m_Name'], n, factor))
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)


if __name__ == '__main__':
    main()
