# -*- coding: utf-8 -*-
"""Set normalSpacingOffset/boldSpacing (character tracking) on TMP font assets.

Usage: python set_tracking.py <bundle> <out_dir> AssetName=offset [...]
Offsets are in font units (px at face point size); negative = tighter.
"""
import os, sys
import UnityPy

def main():
    bundle, out_dir = sys.argv[1], sys.argv[2]
    offsets = {}
    for a in sys.argv[3:]:
        k, v = a.split('=')
        offsets[k] = float(v)
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or tt['m_Name'] not in offsets:
            continue
        v = offsets[tt['m_Name']]
        tt['normalSpacingOffset'] = v
        tt['boldSpacing'] = v
        o.save_typetree(tt)
        print('%s: tracking %.2f (pt=%s)' % (tt['m_Name'], v, tt['m_FaceInfo']['m_PointSize']))
    env.save(pack='lz4', out_path=out_dir)
    print('saved ->', out_dir)

if __name__ == '__main__':
    main()
