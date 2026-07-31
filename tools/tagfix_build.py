import json

with open('tagfix_fixes.json', encoding='utf-8') as f:
    fixes = json.load(f)

out = []
with open('tagfix_queue.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        ru = fixes.get(r['key'], r['ru'])
        out.append({'key': r['key'], 'ru': ru})

with open('tagfix_done.jsonl', 'w', encoding='utf-8') as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print(f"written {len(out)} lines, {len(fixes)} fixes applied")
