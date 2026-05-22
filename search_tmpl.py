import re

with open('templates/thread.html', 'r', encoding='utf-8') as f:
    content = f.read()

for i, line in enumerate(content.split('\n'), 1):
    if 'msg.content' in line:
        print(f'{i}: {line.rstrip()}')