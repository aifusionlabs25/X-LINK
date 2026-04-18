import playwright_stealth
import inspect

print("Attributes in playwright_stealth:")
for name in dir(playwright_stealth):
    print(f" - {name}")

# Check if it's sync or async
try:
    from playwright_stealth import stealth
    print(f"\nStealth signature: {inspect.signature(stealth)}")
except Exception as e:
    print(f"\nError inspecting 'stealth': {e}")
