import sys
sys.path.insert(0, 'C:/Users/user/goinfre/band-archive')

from src.tagger import parse_batch_response

# Test cases
tests = [
    '{"results": [{"id": "999", "tags": ["자원/유튜브"]}]}',
    '{"results": [{"id": "999", "tags": ["자원/유튜브"]}]}  EXTRA DATA',
    '{"results": [{"id": "999", "tags": ["선곡/수지", "공연"]}]}  extra text',
    '{"results":[]}',
    '',
    'not json at all',
]

for raw in tests:
    result = parse_batch_response(raw)
    print(f'INPUT: {repr(raw[:50])}')
    print(f'OUTPUT: {result}')
    print()