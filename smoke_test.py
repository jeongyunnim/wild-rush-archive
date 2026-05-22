import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('C:/Users/user/goinfre/band-archive/data/guild_data.json', encoding='utf-8') as f:
    d = json.load(f)

channels = list(d['channels'].values())
print(f"총 채널: {len(channels)}\n")

for ch in channels:
    name = ch['name']
    msgs = ch['messages']
    print(f"=== {name} ({len(msgs)} messages) ===")
    for msg in msgs[:15]:
        content = msg.get('content', '')[:80]
        author = msg.get('author', {}).get('name', 'unknown')
        print(f"  [{author}] {content}")
    print()