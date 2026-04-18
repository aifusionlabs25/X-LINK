import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


def build_report_artifacts(report_root: Path, prefix: str, screenshot_names: Iterable[str]) -> Dict[str, str]:
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifacts: Dict[str, str] = {
        "report_json": str(report_root / f"{prefix}_{stamp}.json"),
        "report_text": str(report_root / f"{prefix}_{stamp}.txt"),
    }
    for name in screenshot_names:
        artifacts[f"{name}_screenshot"] = str(report_root / f"{prefix}_{stamp}_{name}.png")
    return artifacts


def write_report_bundle(report_json_path: str, report_text_path: str, payload: Dict[str, Any], body: str) -> None:
    json_path = Path(report_json_path)
    text_path = Path(report_text_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    with text_path.open("w", encoding="utf-8") as fh:
        fh.write(body)


def dispatch_report_email(subject: str, body: str, recipient: str, attachments: Iterable[str] | None = None) -> Dict[str, Any]:
    from tools.sloane_jobs import _dispatch_email

    return _dispatch_email(subject, body, recipient, list(attachments or []))
