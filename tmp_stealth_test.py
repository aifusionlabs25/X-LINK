import sys
import traceback

try:
    from playwright_stealth import stealth_async
    print("SUCCESS")
except Exception as e:
    with open("stealth_error.txt", "w") as f:
        traceback.print_exc(file=f)
    print("FAILED")
