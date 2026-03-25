# X-Link: Local Bridge Orchestration
**Role:** Solo Founder Automation Layer (Windows 11)

X-Link is a highly specific, local-only browser orchestration layer. It utilizes Playwright via CDP (Chrome DevTools Protocol - Port 9222) to attach to an *already running* instance of Brave browser. 

This establishes a "Synapse Bridge" between local reasoning agents (like the Dojo Kernel) and authenticated web sessions (like BitWarden, Email, and Calendar) without triggering strict `navigator.webdriver` bot detection or requiring constant re-authentication.

### 🏗️ Architecture (The Trinity Build)
The code in this repository was synthesized from three parallel AI streams:
1. **Perplexity (Architect):** Provided the clean Playwright configuration optimized for a local RTX 5080 environment.
2. **Gemini (Policy/Security Audit):** Directed the separation of the transport layer and established logging protocols to ensure no local sensitive data leaks back to the cloud accidentally.
3. **Grok (Unfiltered Ops):** Designed the `XLinkSynapse` Python class that utilizes stealth Native CDP attachment instead of launching fresh contexts.

### 🚀 Getting Started
1. Run `pip install -r requirements.txt`. (Optional: run `npm install` for Playwright TS typings/tests).
2. Launch Brave Browser using the **Stealth Launcher** on your Desktop:
   `C:\Users\AI Fusion Labs\Desktop\Sloane_Stealth_Launcher.bat`
   *This ensures CDP port 9222 is active with bot-detection suppression flags.*
3. Run `python synapse_bridge.py` to confirm the secure link is active.
4. Run `python test_trinity_heartbeat.py` to verify Perplexity, Gemini, and Grok selectors.
