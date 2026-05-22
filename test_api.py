import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import asyncio, httpx, json

async def test():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.minimaxi.chat/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-cp-cHWCuGa51eQTXhGFDc9MWw5S3hF35xAkZYyZ3EB3ed7CvrS26Mhln2PUGgtyQR2Mohv1gT4FZB0SmqxCoBc75xwkpavBWTBrm2sHtL0vaeSE_CgcKUwuOwE",
                "Content-Type": "application/json",
            },
            json={
                "model": "MiniMax-M2.7",
                "messages": [
                    {"role": "system", "content": "You are a tagger. Output ONLY JSON like {\"tags\": [\"선곡\", \"일정\"]}. No explanation."},
                    {"role": "user", "content": 'Message: 선곡 회의 시간 잡고 진행해주세요~\nExtract tags as JSON.'},
                ],
                "temperature": 0.1,
                "max_tokens": 256,
                "reasoning": False,
            },
            timeout=30.0,
        )
        print("Status:", resp.status_code)
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print("Content:", content[:500])
        usage = data.get("usage", {})
        print("Usage:", usage)

asyncio.run(test())