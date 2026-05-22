import json

d = json.load(open('data/guild_data.json', encoding='utf-8'))
ch = list(d.get('channels', {}).values())[0]
msgs = ch.get('messages', [])
print('msg count:', len(msgs))
print('first msg content (chars):', len(msgs[0].get('content', '')) if msgs else 0)
total = sum(len(c.get('messages', [])) for c in d.get('channels', {}).values())
print('total msgs:', total)
tags = d.get('tags', {})
print('tag keys:', list(tags.keys())[:3])
for k, v in tags.items():
    print(f'  {k}: {json.dumps(v, ensure_ascii=False)[:200]}')
    break