import os
os.environ['MINIMAX_API_KEY'] = 'sk-cp-cHWCuGa51eQTXhGFDc9MWw5S3hF35xAkZYyZ3EB3ed7CvrS26Mhln2PUGgtyQR2Mohv1gT4FZB0SmqxCoBc75xwkpavBWTBrm2sHtL0vaeSE_CgcKUwuOwE'

import asyncio
from src.tagger import tag_messages

messages = [
    {"id": "1", "content": "🎤 선곡-수지 🎤\n해당 공간은 \"수지팀\" 선곡을 위한 공간입니다.", "author_name": "unknown"},
    {"id": "2", "content": "https://youtu.be/x3IcrWIcZVM?si=qiFeYhjs", "author_name": "unknown"},
    {"id": "3", "content": "🫡", "author_name": "unknown"},
    {"id": "4", "content": "선곡 회의 시간 잡고 진행해주세요~", "author_name": "unknown"},
    {"id": "5", "content": "@everyone 오늘 회의 전까지 투표 부탁드려요~", "author_name": "unknown"},
    {"id": "6", "content": "📢 5월 회비 안내 📢\n매 월 1일 회비 입금을 진행하려고 합니다.", "author_name": "unknown"},
]

async def test():
    results = await tag_messages(messages, "테스트채널", batch_size=3)
    for msg_id, tags in results.items():
        print(f"[{msg_id}] {tags}")

asyncio.run(test())