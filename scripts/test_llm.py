import asyncio
import os
import json
import httpx

async def test_raw_api():
    print("--- Diagnostic Test for Volcengine (Doubao) API ---")
    
    # Configuration from conf.yaml
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    api_key = "49a788af-5db7-42ab-b7a3-9e51a0f6ec79"
    model = "doubao-1-5-pro-32k-250115"
    
    # Construct the full URL for chat completions
    # Standard OpenAI format: {base_url}/chat/completions
    url = f"{base_url}/chat/completions"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello, simply reply 'OK'."}
        ],
        "stream": False
    }
    
    print(f"Request URL: {url}")
    print(f"Model (Endpoint ID): {model}")
    print("Sending request with 10s timeout...")
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            print(f"\nStatus Code: {response.status_code}")
            try:
                data = response.json()
                print(f"Response Body: {json.dumps(data, indent=2, ensure_ascii=False)}")
                
                if response.status_code == 200:
                    print("\n✅ API Connection Successful!")
                else:
                    print("\n❌ API Error")
                    
            except json.JSONDecodeError:
                print(f"Raw Response: {response.text}")

    except httpx.ConnectTimeout:
        print("\n❌ Connection Timed Out. The server is unreachable.")
        print("Possible causes: Firewall, Proxy, or DNS issues.")
    except httpx.ConnectError as e:
        print(f"\n❌ Connection Failed: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_raw_api())