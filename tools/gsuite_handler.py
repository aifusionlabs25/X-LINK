import asyncio
import logging
import os
import sys
import argparse
import json
from urllib.parse import quote
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import requests

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from x_link_engine import XLinkEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GSuiteHandler:
    def __init__(self):
        self.engine = XLinkEngine()

    async def _build_gmail_feed_session(self, account_email):
        if not self.engine.context:
            return None, f"No browser context available for {account_email}."

        feed_url = f"https://mail.google.com/mail/u/{account_email}/feed/atom"
        cookies = await self.engine.context.cookies([feed_url])
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
        return session, None

    def _parse_gmail_feed_entries(self, xml_text, limit=5, sender_filter="", query=""):
        root = ET.fromstring(xml_text)
        sender_filter = (sender_filter or "").strip().lower()
        query = (query or "").strip().lower()
        entries = []
        for entry in root.findall("{http://purl.org/atom/ns#}entry"):
            author = entry.find("{http://purl.org/atom/ns#}author")
            sender = (author.findtext("{http://purl.org/atom/ns#}email") if author is not None else "") or ""
            item = {
                "subject": (entry.findtext("{http://purl.org/atom/ns#}title") or "").strip(),
                "summary": (entry.findtext("{http://purl.org/atom/ns#}summary") or "").strip(),
                "issued": (entry.findtext("{http://purl.org/atom/ns#}issued") or "").strip(),
                "sender": sender.strip(),
            }
            haystack = f"{item['subject']} {item['summary']}".lower()
            if sender_filter and sender_filter not in item["sender"].lower():
                continue
            if query and query not in haystack:
                continue
            entries.append(item)
            if len(entries) >= max(1, int(limit)):
                break
        return entries

    async def _wait_for_any(self, page, selectors, timeout=5000):
        last_error = None
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=timeout)
                return locator
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("No matching locator became visible.")

    async def _open_gmail_compose(self, page, account_email):
        to_field_selectors = [
            'input[aria-label="To recipients"]',
            'input[aria-label="To"]',
        ]
        compose_selectors = [
            'div[role="button"][gh="cm"]',
            'div[role="button"][aria-label^="Compose"]',
            'button:has-text("Compose")',
        ]

        try:
            return await self._wait_for_any(page, to_field_selectors, timeout=2500)
        except Exception:
            pass

        try:
            compose_button = await self._wait_for_any(page, compose_selectors, timeout=8000)
            await compose_button.click()
            await asyncio.sleep(2)
            return await self._wait_for_any(page, to_field_selectors, timeout=8000)
        except Exception:
            fallback_url = f"https://mail.google.com/mail/u/{account_email}/#inbox?compose=new"
            await page.goto(fallback_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            return await self._wait_for_any(page, to_field_selectors, timeout=8000)

    async def gmail_list(self, account_email="novaaifusionlabs@gmail.com", limit=5, sender_filter=""):
        logging.info(f"Attempting to list Gmail inbox entries for: {account_email}")
        if not await self.engine.connect():
            return {"success": False, "error": "Failed to connect to browser.", "entries": []}

        page = None
        try:
            inbox_url = f"https://mail.google.com/mail/u/{account_email}/#inbox"
            page = await self.engine.ensure_page(
                inbox_url,
                wait_sec=3,
                account_email=account_email,
                reuse_existing=True,
            )
            await asyncio.sleep(2)

            session, session_error = await self._build_gmail_feed_session(account_email)
            if session_error:
                return {"success": False, "error": session_error, "entries": []}

            feed_url = f"https://mail.google.com/mail/u/{account_email}/feed/atom"
            response = session.get(feed_url, timeout=20)
            response.raise_for_status()
            entries = self._parse_gmail_feed_entries(
                response.text,
                limit=limit,
                sender_filter=sender_filter,
            )

            return {
                "success": True,
                "account": account_email,
                "count": len(entries),
                "entries": entries,
            }
        except Exception as e:
            logging.error(f"Gmail list error: {e}")
            return {"success": False, "error": f"Error listing Gmail: {str(e)}", "entries": []}
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

    async def gmail_read_latest(self, account_email="novaaifusionlabs@gmail.com", query="", sender_filter=""):
        logging.info(f"Attempting to read latest Gmail thread for: {account_email} query={query!r} sender_filter={sender_filter!r}")
        if not await self.engine.connect():
            return {"success": False, "error": "Failed to connect to browser."}

        page = None
        try:
            sender_filter = (sender_filter or "").strip()
            query = (query or "").strip()
            search_terms = []
            if query:
                search_terms.append(query)
            if sender_filter:
                search_terms.append(f"from:{sender_filter}")
            if search_terms:
                search_url = f"https://mail.google.com/mail/u/{account_email}/#search/{quote(' '.join(search_terms))}"
            else:
                search_url = f"https://mail.google.com/mail/u/{account_email}/#inbox"

            page = await self.engine.ensure_page(
                search_url,
                wait_sec=4,
                account_email=account_email,
                reuse_existing=True,
            )
            await asyncio.sleep(4)

            session, session_error = await self._build_gmail_feed_session(account_email)
            if session and not session_error:
                feed_url = f"https://mail.google.com/mail/u/{account_email}/feed/atom"
                response = session.get(feed_url, timeout=20)
                response.raise_for_status()
                entries = self._parse_gmail_feed_entries(
                    response.text,
                    limit=1,
                    sender_filter=sender_filter,
                    query=query,
                )
                if entries:
                    top = entries[0]
                    return {
                        "success": True,
                        "account": account_email,
                        "query": query,
                        "sender_filter": sender_filter,
                        "sender": top.get("sender", ""),
                        "subject": top.get("subject", ""),
                        "body": top.get("summary", ""),
                        "body_preview": top.get("summary", "")[:500],
                        "source": "gmail_atom_feed",
                    }

            row = page.locator("tr.zA, tr.zE").first
            await row.wait_for(state="visible", timeout=8000)

            subject = ""
            sender = ""
            try:
                subject = (await row.locator("span.bog").first.inner_text()).strip()
            except Exception:
                pass
            try:
                sender = (
                    await row.locator("span[email]").first.get_attribute("email")
                    or await row.locator("span[email]").first.inner_text()
                )
                sender = (sender or "").strip()
            except Exception:
                pass

            await row.click()
            await asyncio.sleep(3)

            if not subject:
                try:
                    subject = (await page.locator("h2.hP").first.inner_text()).strip()
                except Exception:
                    subject = ""

            body = ""
            try:
                body = (await page.locator("div.a3s.aiL").first.inner_text()).strip()
            except Exception:
                body = ""

            if not sender:
                try:
                    sender = (await page.locator("span[email]").first.get_attribute("email") or "").strip()
                except Exception:
                    sender = ""

            return {
                "success": True,
                "account": account_email,
                "query": query,
                "sender_filter": sender_filter,
                "sender": sender,
                "subject": subject,
                "body": body,
                "body_preview": body[:500],
                "source": "gmail_ui",
            }
        except Exception as e:
            logging.error(f"Gmail latest-read error: {e}")
            return {"success": False, "error": f"Error reading latest Gmail: {str(e)}"}
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

    async def calendar_create(self, title, start_time_str, attendees=None, description=""):
        """
        Creates a Google Calendar event.
        start_time_str: Expects ISO or relative format.
        """
        logging.info(f"📅 Attempting to create calendar event: {title}")
        if not await self.engine.connect():
            return "Failed to connect to browser."

        page = None
        try:
            # 1. Navigate to Calendar (Absolute Email URL)
            page = await self.engine.ensure_page(
                "https://calendar.google.com/calendar/u/novaaifusionlabs@gmail.com/r/eventedit",
                wait_sec=5,
                account_email="novaaifusionlabs@gmail.com",
                reuse_existing=True,
            )
            
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
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

    async def gmail_send(self, to, subject, body, attachments=None):
        """
        Sends an email via Gmail UI in Brave.
        """
        logging.info(f"Attempting to send Gmail to: {to}")
        if not await self.engine.connect():
            return "Failed to connect to browser."

        page = None
        try:
            inbox_url = "https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#inbox"
            page = await self.engine.ensure_page(
                inbox_url,
                wait_sec=3,
                account_email="novaaifusionlabs@gmail.com",
                reuse_existing=True,
            )
            await asyncio.sleep(2)

            to_field = await self._open_gmail_compose(page, "novaaifusionlabs@gmail.com")
            await to_field.click()
            await asyncio.sleep(0.5)
            await to_field.fill(to)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.5)

            subject_field = page.locator('input[name="subjectbox"]').first
            await subject_field.wait_for(state="visible", timeout=5000)
            await subject_field.click()
            await asyncio.sleep(0.3)
            await subject_field.fill(subject)
            await asyncio.sleep(0.5)

            body_field = page.locator('div[aria-label="Message Body"]').first
            await body_field.wait_for(state="visible", timeout=5000)
            await body_field.click()
            await asyncio.sleep(0.3)
            await body_field.fill(body)
            await asyncio.sleep(0.5)

            if attachments:
                file_input = page.locator('input[type="file"][name="Filedata"]').first
                files = [item for item in attachments if item and os.path.exists(item)]
                if files:
                    await file_input.set_input_files(files)
                    await asyncio.sleep(5)

            try:
                send_button = await self._wait_for_any(
                    page,
                    [
                        'div[role="button"][data-tooltip^="Send"]',
                        'div[role="button"][aria-label^="Send"]',
                        'button:has-text("Send")',
                    ],
                    timeout=4000,
                )
                await send_button.click()
            except Exception:
                await page.keyboard.press("Control+Enter")
            await asyncio.sleep(4)

            return f"Gmail sent to {to} successfully."
        except Exception as e:
            logging.error(f"Gmail error: {e}")
            return f"Error sending Gmail: {str(e)}"
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

    async def gmail_reply_founder_latest(self, sender, body):
        """
        Replies to the latest Gmail thread from the founder only.
        """
        founder_email = (sender or "").strip().lower()
        if founder_email != "aifusionlabs@gmail.com":
            return "Founder-only reply is locked to aifusionlabs@gmail.com."

        logging.info(f"📧 Attempting founder-only Gmail reply to latest thread from: {founder_email}")
        if not await self.engine.connect():
            return "Failed to connect to browser."

        page = None
        try:
            search_query = quote(f"from:{founder_email}")
            search_url = f"https://mail.google.com/mail/u/novaaifusionlabs@gmail.com/#search/{search_query}"
            page = await self.engine.ensure_page(
                search_url,
                wait_sec=5,
                account_email="novaaifusionlabs@gmail.com",
                reuse_existing=False,
            )
            await asyncio.sleep(5)

            row = page.locator("tr.zA").first
            await row.wait_for(state="visible", timeout=8000)

            subject = "Founder email"
            try:
                subject = (await row.locator("span.bog").first.inner_text()).strip() or subject
            except Exception:
                pass

            await row.click()
            await asyncio.sleep(4)

            reply_button = page.locator('div[role="button"][aria-label^="Reply"]').first
            try:
                await reply_button.wait_for(state="visible", timeout=5000)
            except Exception:
                reply_button = page.locator('span[role="link"]:has-text("Reply")').first
                await reply_button.wait_for(state="visible", timeout=5000)

            await reply_button.click()
            await asyncio.sleep(2)

            body_field = page.locator('div[role="textbox"][aria-label="Message Body"]').last
            try:
                await body_field.wait_for(state="visible", timeout=5000)
            except Exception:
                body_field = page.locator('div[role="textbox"][g_editable="true"]').last
                await body_field.wait_for(state="visible", timeout=5000)

            await body_field.click()
            await asyncio.sleep(0.3)
            await body_field.fill(body)
            await asyncio.sleep(0.5)

            await page.keyboard.press("Control+Enter")
            await asyncio.sleep(3)

            return f"Reply sent to {founder_email} successfully. Subject: {subject}"
        except Exception as e:
            logging.error(f"Founder reply error: {e}")
            return f"Error replying to founder email: {str(e)}"
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass


async def main():
    parser = argparse.ArgumentParser(description="X-LINK GSuite Handler")
    parser.add_argument("--action", required=True, choices=["gmail_send", "calendar_create", "gmail_reply_founder_latest", "gmail_list", "gmail_read_latest"])
    parser.add_argument("--to", help="Recipient email")
    parser.add_argument("--subject", help="Email subject")
    parser.add_argument("--body", help="Email body")
    parser.add_argument("--attachments", help="Attachment paths separated by ||")
    parser.add_argument("--sender", help="Sender email for founder-only reply flow")
    parser.add_argument("--account", help="Account email to inspect")
    parser.add_argument("--limit", type=int, default=5, help="Max inbox entries to list")
    parser.add_argument("--sender-filter", help="Optional sender filter substring")
    parser.add_argument("--query", help="Optional Gmail search query")
    parser.add_argument("--title", help="Event title")
    parser.add_argument("--attendees", help="Guest emails (comma separated)")
    parser.add_argument("--description", help="Event description")

    args = parser.parse_args()
    handler = GSuiteHandler()

    if args.action == "gmail_send":
        attachments = [part for part in (args.attachments or "").split("||") if part]
        res = await handler.gmail_send(args.to, args.subject, args.body, attachments=attachments)
        print(res)
    elif args.action == "calendar_create":
        res = await handler.calendar_create(args.title, "tomorrow 07:30", args.attendees, args.description)
        print(res)
    elif args.action == "gmail_reply_founder_latest":
        res = await handler.gmail_reply_founder_latest(args.sender, args.body)
        print(res)
    elif args.action == "gmail_list":
        res = await handler.gmail_list(
            account_email=args.account or "novaaifusionlabs@gmail.com",
            limit=args.limit or 5,
            sender_filter=args.sender_filter or "",
        )
        print(json.dumps(res, ensure_ascii=False))
    elif args.action == "gmail_read_latest":
        res = await handler.gmail_read_latest(
            account_email=args.account or "novaaifusionlabs@gmail.com",
            query=args.query or "",
            sender_filter=args.sender_filter or "",
        )
        print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
