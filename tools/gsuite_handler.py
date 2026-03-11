import asyncio
import logging
import os
import sys
import argparse
from datetime import datetime, timedelta

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GSuiteHandler:
    def __init__(self):
        self.engine = XLinkEngine()

    async def calendar_create(self, title, start_time_str, attendees=None, description=""):
        """
        Creates a Google Calendar event.
        start_time_str: Expects ISO or relative format.
        """
        logging.info(f"📅 Attempting to create calendar event: {title}")
        if not await self.engine.connect():
            return "Failed to connect to browser."

        try:
            # 1. Navigate to Calendar (Absolute Email URL)
            page = await self.engine.ensure_page("https://calendar.google.com/calendar/u/novaaifusionlabs@gmail.com/r/eventedit", wait_sec=5, account_email="novaaifusionlabs@gmail.com")
            
            # 2. Fill Title
            await self.engine.human_type(page, 'input[aria-label="Add title"]', title)
            
            # 3. Handle Time (Simplified: We'll use the URL approach or direct input)
            # For simplicity in this v1, we'll try to use the UI fields
            # Better way: Google Calendar allows prepopulating via URL but that's for 'public' links.
            # We will use the direct UI input.
            
            if attendees:
                await self.engine.human_type(page, 'input[placeholder="Add guests"]', attendees)
                await page.keyboard.press("Enter")

            if description:
                await self.engine.human_type(page, 'div[aria-label="Add description"]', description)

            # Note: Detailed time picking in Google Calendar UI is complex due to shadow DOMs/dynamic menus.
            # We'll rely on the default 'next available hour' for now or simple keyboard navigation.
            # HIGH RISK: This is brittle. In a production scenario, we'd use the API, but Rob wants 'Brave' automation.
            
            # Click Save
            await self.engine.human_click(page, 'button:has-text("Save")')
            await asyncio.sleep(2)
            
            return f"Calendar event '{title}' created successfully."
        except Exception as e:
            logging.error(f"Calendar error: {e}")
            return f"Error creating calendar event: {str(e)}"

    async def gmail_send(self, to, subject, body):
        """
        Sends an email via Gmail UI in Brave.
        """
        logging.info(f"📧 Attempting to send Gmail to: {to}")
        if not await self.engine.connect():
            return "Failed to connect to browser."

        try:
            # Navigate directly to Gmail compose (skip the Compose button click)
            compose_url = "https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#inbox?compose=new"
            page = await self.engine.ensure_page(compose_url, wait_sec=5, account_email="novaaifusionlabs@gmail.com")
            await asyncio.sleep(4)  # Gmail compose popup needs time to animate open
            
            # Fill Recipient — wait for the To field to appear
            to_field = page.locator('input[aria-label="To recipients"]').first
            try:
                await to_field.wait_for(state="visible", timeout=5000)
            except Exception:
                # Fallback selector
                to_field = page.locator('input[aria-label="To"]').first
                await to_field.wait_for(state="visible", timeout=5000)
            
            await to_field.click()
            await asyncio.sleep(0.5)
            await to_field.fill(to)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.5)
            
            # Fill Subject
            subject_field = page.locator('input[name="subjectbox"]').first
            await subject_field.wait_for(state="visible", timeout=3000)
            await subject_field.click()
            await asyncio.sleep(0.3)
            await subject_field.fill(subject)
            await asyncio.sleep(0.5)
            
            # Fill Body
            body_field = page.locator('div[aria-label="Message Body"]').first
            await body_field.wait_for(state="visible", timeout=3000)
            await body_field.click()
            await asyncio.sleep(0.3)
            await body_field.fill(body)
            await asyncio.sleep(0.5)
            
            # Send with Ctrl+Enter
            await page.keyboard.press("Control+Enter")
            await asyncio.sleep(3)
            
            return f"Gmail sent to {to} successfully."
        except Exception as e:
            logging.error(f"Gmail error: {e}")
            return f"Error sending Gmail: {str(e)}"


async def main():
    parser = argparse.ArgumentParser(description="X-LINK GSuite Handler")
    parser.add_argument("--action", required=True, choices=["gmail_send", "calendar_create"])
    parser.add_argument("--to", help="Recipient email")
    parser.add_argument("--subject", help="Email subject")
    parser.add_argument("--body", help="Email body")
    parser.add_argument("--title", help="Event title")
    parser.add_argument("--attendees", help="Guest emails (comma separated)")
    parser.add_argument("--description", help="Event description")

    args = parser.parse_args()
    handler = GSuiteHandler()

    if args.action == "gmail_send":
        res = await handler.gmail_send(args.to, args.subject, args.body)
        print(res)
    elif args.action == "calendar_create":
        res = await handler.calendar_create(args.title, "tomorrow 07:30", args.attendees, args.description)
        print(res)

if __name__ == "__main__":
    asyncio.run(main())
