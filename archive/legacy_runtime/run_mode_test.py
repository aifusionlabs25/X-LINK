import asyncio
import argparse
from x_link_engine import XLinkEngine

async def main():
    engine = XLinkEngine()
    connected = await engine.connect()
    
    if connected:
        try:
            print(f"\n--- INITIATING SCATTER-GATHER MODE ---\n")
            
            # The exact Fulton Homes Workflow as targets mapping
            targets = {
                "grok.com": "Search realtime data for unfiltered sentiment regarding buying new construction homes in Phoenix right now. What are buyers complaining about most on X/Twitter? Are there delays, hidden fees, or poor communication from sales reps?",
                "perplexity.ai": "Search the web for the current state of AI adoption among major home builders in 2026. What specific software or incumbent CRM systems are they currently using for their sales funnels?",
                "gemini.google.com": "Analyze the legal and compliance risks for an AI Sales Concierge representing a Home Builder. If the AI hallucinates a lower interest rate, an incorrect base price, or a false timeline, what is the exact liability profile? Outline 3 strict guardrails to prevent this."
            }
            synthesis_target = "chatgpt.com"
            synthesis_prompt = "Assume the role of the X Agent Factory Dojo Master. Await the findings from Grok, Perplexity, and Gemini. I will provide those to you shortly. When you receive them, use them to generate the ultimate, highly-refined System Prompt for the Fulton Homes \"Sales Concierge\" agent."

            result = await engine.run_scatter_gather(
                targets=targets,
                synthesis_target=synthesis_target,
                synthesis_prompt=synthesis_prompt,
                timeout_sec=120 
            )
            
            with open("final_system_prompt_v2.txt", "w", encoding="utf-8") as f:
                f.write(result)
                
            print("\n================ FINAL SYNTHESIZED RESPONSE ================\n")
            print("Successfully executed SCATTER-GATHER across 4 targets simultaneously.")
            print("Results saved to final_system_prompt_v2.txt")
            print("\n==========================================================\n")
        except Exception as e:
            print(f"Error during execution: {e}")
        finally:
            await engine.close()

if __name__ == "__main__":
    asyncio.run(main())
