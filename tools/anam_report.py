from typing import Any, Dict

from tools.site_report_workflows import run_site_usage_email_report


async def run_anam_usage_email_report(days: int = 7, recipient: str = "aifusionlabs@gmail.com") -> Dict[str, Any]:
    return await run_site_usage_email_report("anam", days=days, recipient=recipient)
