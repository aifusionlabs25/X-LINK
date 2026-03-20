import asyncio
import json
import logging
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

async def test_classification(test_cases):
    print(f"\n{'='*60}")
    print("  🧪 SLOANE INTELLIGENCE TEST: Email Classification")
    print(f"{'='*60}\n")
    
    for sender, sub, body in test_cases:
        print(f"📧 FROM: {sender}")
        print(f"📌 SUB: {sub}")
        print(f"📝 BODY: {body}")
        
        prompt = f"""
        You are Sloane's Command Processor. Analyze the following email from '{sender}'.
        Subject: {sub}
        Body: {body}

        Determine if this is a command to trigger a tool. 
        Available Tools:
        - 'audit': Usage extraction, cost audits, or checking balance.
        - 'sync': Full engine sync, updating metrics, or universal sync.
        - 'scout': Scouting intelligence, checking Keep.md, or autoresearch.
        - 'briefing': Asking for a report, status update, or briefing.

        Return ONLY a JSON object: {{"is_command": true/false, "tool": "tool_name", "reason": "brief reason"}}.
        If not a command, "tool" should be null.
        """
        
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": "qwen3-coder-next",
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=20)
            res = json.loads(response.json()['response'])
            print(f"🧠 SLOANE THOUGHT: {res.get('reason')}")
            print(f"🚀 DECISION: {res.get('tool') if res.get('is_command') else 'None'}")
        except Exception as e:
            print(f"❌ TEST FAILED: {e}")
        print("-" * 40)

if __name__ == "__main__":
    tests = [
        ("rvicks@gmail.com", "sync", "Hey Sloane, can you sync the engines?"),
        ("rvicks@gmail.com", "Report", "I need a fresh briefing on my desk now."),
        ("aifusionlabs@gmail.com", "Usage", "Run a full audit of our spending."),
        ("novaaifusionlabs@gmail.com", "Self-Note", "I should scout Keep.md for those Karpathy notes later tonight."),
        ("someone@random.com", "Hello", "Just wanted to say hi!")
    ]
    asyncio.run(test_classification(tests))
