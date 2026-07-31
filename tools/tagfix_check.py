import json, re, sys

TAG_RE = re.compile(r'<[^>]+>|\{\w*\}|%[\d.]*[sdif]|\\n')

def tags(s):
    return TAG_RE.findall(s)

def load(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

queue = load('tagfix_queue.jsonl')
try:
    done = load('tagfix_done.jsonl')
except FileNotFoundError:
    done = None

if done is None:
    # diagnostic mode: compare en vs ru in queue
    n_ok = n_bad = 0
    for i, r in enumerate(queue, 1):
        te, tr = tags(r['en']), tags(r['ru'])
        if te == tr:
            n_ok += 1
        else:
            n_bad += 1
            print(f"--- line {i} key={r['key']}")
            print("  EN:", te)
            print("  RU:", tr)
    print(f"OK={n_ok} BAD={n_bad}")
else:
    assert len(done) == len(queue), f"count mismatch: {len(done)} vs {len(queue)}"
    n_ok = n_bad = 0
    for i, (q, d) in enumerate(zip(queue, done), 1):
        assert q['key'] == d['key'], f"key mismatch at line {i}: {q['key']} vs {d['key']}"
        te, tr = tags(q['en']), tags(d['ru'])
        if te == tr:
            n_ok += 1
        else:
            n_bad += 1
            print(f"--- line {i} key={q['key']}")
            print("  EN:", te)
            print("  RU:", tr)
    print(f"OK={n_ok} BAD={n_bad}")
    sys.exit(0 if n_bad == 0 else 1)
