import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from tools.report_ops import build_report_artifacts, dispatch_report_email, write_report_bundle

ROOT_DIR = Path(__file__).resolve().parents[1]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


async def _click_text_button(page, label: str) -> bool:
    locator = page.locator("button, [role='button'], a").filter(has_text=re.compile(rf"^{re.escape(label)}$", re.I)).first
    if await locator.count() == 0:
        locator = page.locator("button, [role='button'], a").filter(has_text=re.compile(re.escape(label), re.I)).first
    if await locator.count() == 0:
        return False
    await locator.click()
    await asyncio.sleep(1.5)
    return True


async def _select_anam_range(page, days: int) -> str:
    target_label = f"Last {days} days"
    dropdown_candidates = [
        page.get_by_role("button", name=re.compile(r"Last\s+\d+\s+days", re.I)).first,
        page.locator("button").filter(has_text=re.compile(r"^Last\s+\d+\s+days$", re.I)).first,
    ]
    dropdown = None
    for candidate in dropdown_candidates:
        try:
            if await candidate.count() > 0:
                dropdown = candidate
                break
        except Exception:
            continue
    if dropdown is None:
        return "unknown"

    current_label = _clean_text(await dropdown.inner_text())
    if len(current_label) > 40:
        current_label = "unknown"
    if target_label.lower() in current_label.lower():
        return current_label

    await dropdown.click(force=True)
    await asyncio.sleep(1)

    option_candidates = [
        page.get_by_role("option", name=target_label),
        page.get_by_role("menuitem", name=target_label),
        page.get_by_role("button", name=target_label),
        page.locator(f"text=\"{target_label}\""),
    ]
    clicked = False
    for candidate in option_candidates:
        try:
            if await candidate.count() > 0:
                item = candidate.last
                await item.click(force=True)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        try:
            await dropdown.click(force=True)
            await page.keyboard.press("Home")
            await page.keyboard.type(str(days))
            await page.keyboard.press("Enter")
        except Exception:
            pass

    await asyncio.sleep(3)
    try:
        refreshed = _clean_text(await dropdown.inner_text())
        if len(refreshed) > 40:
            refreshed = "unknown"
    except Exception:
        refreshed = target_label if clicked else current_label
    return refreshed or current_label or "unknown"


async def _prepare_anam_overview(page, days: int) -> None:
    await _click_text_button(page, "Overview")
    selected = await _select_anam_range(page, days)
    await page.evaluate("window.scrollTo(0, 0)")
    page._xlink_selected_range = selected  # type: ignore[attr-defined]


async def _prepare_anam_history(page, days: int) -> None:
    await _click_text_button(page, "History")
    selected = await _select_anam_range(page, days)
    await page.evaluate("window.scrollTo(0, 0)")
    page._xlink_selected_range = selected  # type: ignore[attr-defined]


def _extract_anam_overview_metrics(text: str) -> Dict[str, str]:
    content = _clean_text(text)
    metrics: Dict[str, str] = {}

    patterns = {
        "total_sessions": r"Total\s+Sessions\s+(\d+)",
        "total_usage": r"Total\s+Usage\s+([0-9hms\s]+)",
        "latest_session": r"Latest\s+session:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            metrics[key] = _clean_text(match.group(1))

    range_match = re.search(r"Last\s+(\d+)\s+days", content, re.IGNORECASE)
    if range_match:
        metrics["range_label"] = f"Last {range_match.group(1)} days"

    metrics["preview"] = content[:280]
    return metrics


def _extract_anam_history_metrics(text: str) -> Dict[str, str]:
    content = _clean_text(text)
    metrics: Dict[str, str] = {}

    patterns = {
        "latest_session": r"Latest\s+session:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
        "active_sessions": r"(\d+)\s+Active",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            metrics[key] = _clean_text(match.group(1))

    metrics["preview"] = content[:280]
    return metrics


def _compose_anam_report(days: int, recipient: str, primary: Dict[str, str], secondary: Dict[str, str], artifacts: Dict[str, str]) -> Dict[str, str]:
    subject = f"Anam Usage Report - Last {days} Days"
    actual_range = primary.get("range_label", f"Last {days} days")
    range_verified = actual_range.lower() == f"last {days} days".lower()
    short_take = (
        "I was able to verify the requested date range and read the visible analytics directly from the Anam sessions view."
        if range_verified
        else "I captured the analytics view, but I could not verify that Anam actually switched to the requested date range before capture."
    )
    lines = [
        "Rob,",
        "",
        f"I checked Anam on the Sessions page and captured the overview and history screenshots.",
        "",
        "What I found:",
        f"- Requested range: Last {days} days",
        f"- Actual range shown: {actual_range}",
        f"- Total sessions: {primary.get('total_sessions', 'Not clearly detected')}",
        f"- Total usage: {primary.get('total_usage', 'Not clearly detected')}",
        f"- Latest session shown: {secondary.get('latest_session', primary.get('latest_session', 'Not clearly detected'))}",
        f"- Active sessions: {secondary.get('active_sessions', 'Not clearly detected')}",
        "",
        "My short take:",
        short_take,
        "",
        "Attachments:",
        "- Overview screenshot",
        "- History screenshot",
        "",
        "Sloane",
    ]
    return {"subject": subject, "body": "\n".join(lines), "recipient": recipient}


SITE_REPORTS: Dict[str, Dict[str, Any]] = {
    "anam": {
        "label": "Anam",
        "aliases": ("anam", "anam site", "anam lab"),
        "report_dir": ROOT_DIR / "vault" / "reports" / "anam",
        "prefix": "anam_usage",
        "primary_url": "https://lab.anam.ai/sessions",
        "secondary_url": "https://lab.anam.ai/sessions",
        "primary_name": "overview",
        "secondary_name": "history",
        "prepare_primary": _prepare_anam_overview,
        "prepare_secondary": _prepare_anam_history,
        "primary_extractor": _extract_anam_overview_metrics,
        "secondary_extractor": _extract_anam_history_metrics,
        "compose_report": _compose_anam_report,
    }
}


def identify_site_report_request(user_msg: str) -> Optional[str]:
    text = (user_msg or "").lower()
    has_send = bool(re.search(r"\b(send|email)\b", text))
    has_report = bool(re.search(r"\b(report|usage|numbers|metrics|graphs?|screenshots?|ss)\b", text))
    if not (has_send and has_report):
        return None

    for site_key, spec in SITE_REPORTS.items():
        for alias in spec.get("aliases", ()):
            if alias in text:
                return site_key
    return None


async def run_site_usage_email_report(site_key: str, days: int = 7, recipient: str = "aifusionlabs@gmail.com") -> Dict[str, Any]:
    from x_link_engine import XLinkEngine

    spec = SITE_REPORTS.get(site_key)
    if not spec:
        return {
            "success": False,
            "recipient": recipient,
            "days": days,
            "site_key": site_key,
            "error": f"Unknown site report workflow: {site_key}",
        }

    artifacts = build_report_artifacts(
        spec["report_dir"],
        spec["prefix"],
        (spec["primary_name"], spec["secondary_name"]),
    )

    engine = XLinkEngine()
    result: Dict[str, Any] = {
        "success": False,
        "recipient": recipient,
        "days": days,
        "site_key": site_key,
        "site_label": spec["label"],
        "artifacts": artifacts,
        "primary": {},
        "secondary": {},
        "email": {"success": False},
    }

    try:
        if not await engine.connect():
            result["error"] = "Failed to connect to browser."
            return result

        page = await engine.ensure_page(
            spec["primary_url"],
            wait_sec=4,
            bring_to_front=False,
            reuse_existing=False,
        )
        if spec.get("prepare_primary"):
            await spec["prepare_primary"](page, days)
        await page.screenshot(path=artifacts[f"{spec['primary_name']}_screenshot"], full_page=True)
        primary_text = await page.locator("body").inner_text()
        result["primary"] = spec["primary_extractor"](primary_text)
        selected_primary_range = getattr(page, "_xlink_selected_range", None)
        if selected_primary_range:
            result["primary"]["range_label"] = selected_primary_range

        await page.goto(spec["secondary_url"], wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)
        if spec.get("prepare_secondary"):
            await spec["prepare_secondary"](page, days)
        await page.screenshot(path=artifacts[f"{spec['secondary_name']}_screenshot"], full_page=True)
        secondary_text = await page.locator("body").inner_text()
        result["secondary"] = spec["secondary_extractor"](secondary_text)

        payload = spec["compose_report"](days, recipient, result["primary"], result["secondary"], artifacts)
        report_payload = {
            "generated_at": datetime.now().isoformat(),
            "recipient": recipient,
            "days": days,
            "site_key": site_key,
            "site_label": spec["label"],
            "primary": result["primary"],
            "secondary": result["secondary"],
            "artifacts": artifacts,
        }
        write_report_bundle(artifacts["report_json"], artifacts["report_text"], report_payload, payload["body"])

        dispatch = dispatch_report_email(
            payload["subject"],
            payload["body"],
            recipient,
            attachments=[
                artifacts.get(f"{spec['primary_name']}_screenshot"),
                artifacts.get(f"{spec['secondary_name']}_screenshot"),
            ],
        )
        result["email"] = dispatch
        result["success"] = bool(dispatch.get("success"))
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        if "page" in locals() and page and not page.is_closed():
            try:
                await page.close()
            except Exception:
                pass
        await engine.close()
