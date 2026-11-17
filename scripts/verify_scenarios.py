import json

with open('src/loan_agent/scenarios.jsonl') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Verify all lines are valid JSON
for i, line in enumerate(lines, 1):
    try:
        d = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON on line {i}: {e}")
        break
else:
    print("All lines are valid JSON")

# Print first 3 and last 3
for i, line in enumerate(lines[:3]):
    d = json.loads(line)
    print(f"  {d['scenario_id']}: {d['category']} - {d['description'][:50]}")

print("  ...")

for i, line in enumerate(lines[-3:]):
    d = json.loads(line)
    print(f"  {d['scenario_id']}: {d['category']} - {d['description'][:50]}")

# Verify all scenario IDs are unique
ids = [json.loads(l)['scenario_id'] for l in lines]
print(f"\nUnique IDs: {len(set(ids))} / {len(ids)}")

# Count by category
from collections import Counter
cats = Counter(json.loads(l)['category'] for l in lines)
for cat, count in sorted(cats.items()):
    print(f"  {cat}: {count}")