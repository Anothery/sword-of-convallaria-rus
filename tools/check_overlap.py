import sys
import UnityPy

def check(bundle, name):
    env = UnityPy.load(bundle)
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        tt = o.read_typetree()
        if 'm_GlyphTable' not in tt or tt['m_Name'] != name:
            continue
        r0 = [(g['m_GlyphRect'], g['m_Index']) for g in tt['m_GlyphTable']
              if g.get('m_AtlasIndex', 0) == 0 and g['m_GlyphRect']['m_Width'] > 0]
        n = 0
        for i in range(len(r0)):
            for j in range(i + 1, len(r0)):
                (a, ia), (b, ib) = r0[i], r0[j]
                ox = min(a['m_X'] + a['m_Width'], b['m_X'] + b['m_Width']) - max(a['m_X'], b['m_X'])
                oy = min(a['m_Y'] + a['m_Height'], b['m_Y'] + b['m_Height']) - max(a['m_Y'], b['m_Y'])
                if ox > 0 and oy > 0:
                    n += 1
                    if n <= 5:
                        print('  overlap idx %d %s vs %d %s' % (ia, a, ib, b))
        print('%s %s: atlas0 rects=%d overlaps=%d' % (bundle, name, len(r0), n))

check('orig_en/fonts/font_global.unity3d', 'SDFFontTitle_sys')
check('bake_out/global/font_global.unity3d', 'SDFFontTitle_sys')
