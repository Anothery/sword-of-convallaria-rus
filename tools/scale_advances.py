# -*- coding: utf-8 -*-
"""Scale m_HorizontalAdvance of all glyphs in TMP font assets (character
tightening that the game's custom TMP cannot ignore).

Usage: python scale_advances.py <bundle> <out_dir> <factor> [Asset1,Asset2]
"""
import os, sys
import UnityPy

def main():
    bundle, out_dir, factor = sys.argv[1], sys.argv[2], float(sys.argv[3])
    names = sys.argv[4].split(',') if len(sys.argv) > 4 else None
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or not tt['m_GlyphTable']:
            continue
        if names and tt['m_Name'] not in names:
            continue
        n = 0
        for g in tt['m_GlyphTable']:
            m = g['m_Metrics']
            m['m_HorizontalAdvance'] = float(m['m_HorizontalAdvance'] * factor)
            n += 1
        o.save_typetree(tt)
        print('%s: scaled %d advances x%.3f' % (tt['m_Name'], n, factor))
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)

if __name__ == '__main__':
    main()
