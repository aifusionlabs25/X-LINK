from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vault" / "reports" / "x_link_app_summary.pdf"
PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def pdf_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap(text, width):
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def add_text(lines, x, y, font, size, leading, items):
    lines.append("BT")
    lines.append(f"/{font} {size} Tf")
    lines.append(f"{x} {y} Td")
    first = True
    for item in items:
        if not first:
            lines.append(f"0 -{leading} Td")
        lines.append(f"({pdf_escape(item)}) Tj")
        first = False
    lines.append("ET")


def build_content():
    content = []

    content.append("0.82 0.86 0.91 RG")
    content.append("1 w")
    content.append("36 36 540 720 re S")
    content.append("0.06 0.10 0.18 rg")
    add_text(content, 50, 748, "F2", 19, 22, ["X-LINK App Summary"])
    content.append("0.35 0.40 0.48 rg")
    add_text(
        content,
        50,
        730,
        "F1",
        8,
        10,
        ["Evidence-based one-page summary generated from repository contents only."],
    )

    y = 706

    def section(title, body_lines):
        nonlocal y
        content.append("0.04 0.37 0.80 rg")
        add_text(content, 50, y, "F2", 11, 13, [title])
        y -= 14
        content.append("0.12 0.16 0.22 rg")
        add_text(content, 50, y, "F1", 8.7, 10.4, body_lines)
        y -= 10.4 * len(body_lines) + 8

    section(
        "What It Is",
        wrap(
            "X-LINK is a local-only browser orchestration and command hub for Windows 11. "
            "It attaches to an already running Brave browser over CDP, routes work through a "
            "local FastAPI hub, and stores outputs in a local vault instead of relying on "
            "cloud-hosted browser sessions.",
            95,
        ),
    )

    section(
        "Who It's For",
        wrap(
            "Primary persona: a solo founder/operator managing AI agents and authenticated "
            "browser workflows locally. Repo evidence points specifically to an internal "
            "AI Fusion Labs founder workflow.",
            95,
        ),
    )

    content.append("0.04 0.37 0.80 rg")
    add_text(content, 50, y, "F2", 11, 13, ["What It Does"])
    y -= 14
    content.append("0.12 0.16 0.22 rg")
    feature_bullets = [
        "Provides a Direct Line chat lane to the Sloane assistant via local Ollama.",
        "Runs a Usage Auditor against configured platform targets and saves JSON reports.",
        "Offers an Intelligence Scout flow to gather and synthesize research.",
        "Executes X-Agent Eval batches with scenarios, scoring, and review packets.",
        "Generates Direct Briefings from recent tool outputs for executive summaries.",
        "Tracks bridge and sync status for the Hub UI, including CDP connectivity.",
        "Persists sessions, intel, reports, evals, logs, and screenshots in the local vault.",
    ]
    for bullet in feature_bullets:
        wrapped = wrap(bullet, 86)
        add_text(content, 58, y, "F1", 8.2, 9.6, [f"- {wrapped[0]}"] + [f"  {line}" for line in wrapped[1:]])
        y -= 9.6 * len(wrapped) + 2
    y -= 4

    content.append("0.04 0.37 0.80 rg")
    add_text(content, 50, y, "F2", 11, 13, ["How It Works"])
    y -= 16

    box_top = y + 4
    box_bottom = y - 116
    content.append("0.97 0.98 0.99 rg")
    content.append(f"48 {box_bottom} 516 {box_top - box_bottom} re f")
    content.append("0.82 0.86 0.91 RG")
    content.append("0.5 w")
    content.append(f"48 {box_bottom} 516 {box_top - box_bottom} re S")
    content.append("306 {0} m 306 {1} l S".format(box_bottom, box_top))
    content.append("48 {0} m 564 {0} l S".format(box_top - 38))
    content.append("48 {0} m 564 {0} l S".format(box_top - 76))

    content.append("0.12 0.16 0.22 rg")
    left_rows = [
        "Frontend: hub/index.html + hub/app.js render workspaces and poll API endpoints.",
        "Routing: hub/router.py resolves tool keys from config/tool_registry.yaml and executes tools through a shared BaseTool contract.",
        "Data flow: Hub action -> FastAPI route -> router/tool -> local browser or Ollama work -> artifacts written to vault -> Hub reads status/results back.",
    ]
    right_rows = [
        "Controller: tools/synapse_bridge.py runs a local FastAPI app on 127.0.0.1:5001, serves /hub, exposes API routes, and launches subprocess tools.",
        "Runtime services: CDP/Brave at 127.0.0.1:9222, local Ollama at 127.0.0.1:11434, YAML config files, and vault storage.",
        "Not found in repo: external production deployment, multi-user auth model, or hosted SaaS architecture.",
    ]

    row_y = box_top - 18
    for left, right in zip(left_rows, right_rows):
        add_text(content, 56, row_y, "F1", 7.9, 9.2, wrap(left, 43))
        add_text(content, 314, row_y, "F1", 7.9, 9.2, wrap(right, 43))
        row_y -= 38

    y = box_bottom - 18
    content.append("0.04 0.37 0.80 rg")
    add_text(content, 50, y, "F2", 11, 13, ["How To Run"])
    y -= 14
    content.append("0.12 0.16 0.22 rg")
    run_steps = [
        "Install Python deps: pip install -r requirements.txt",
        "Optional for tests: npm install",
        "Launch Brave with remote debugging on port 9222 using the repo-documented stealth launcher.",
        "Start the local hub with .venv\\Scripts\\python.exe tools\\synapse_bridge.py or launch_hub.bat",
        "Open http://localhost:5001/hub/ and use python test_trinity_heartbeat.py if CDP verification is needed.",
    ]
    for step in run_steps:
        wrapped = wrap(step, 88)
        add_text(content, 58, y, "F1", 8.2, 9.6, [f"- {wrapped[0]}"] + [f"  {line}" for line in wrapped[1:]])
        y -= 9.6 * len(wrapped) + 2

    content.append("0.35 0.40 0.48 rg")
    add_text(
        content,
        50,
        56,
        "F1",
        7.2,
        8.4,
        wrap(
            "Key evidence used: README.md, tools/synapse_bridge.py, hub/*.py/js/html, "
            "config/hub_menu.yaml, config/tool_registry.yaml, x_link_engine.py, and tests/test_hub_smoke.py.",
            100,
        ),
    )

    stream = "\n".join(content).encode("ascii")
    return stream


def make_pdf(stream):
    objects = []

    def add_object(body):
        objects.append(body)
        return len(objects)

    font1 = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font2 = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    content_id = add_object(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
    page_id = add_object(
        f"<< /Type /Page /Parent 5 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
        f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
        f"/Contents {content_id} 0 R >>"
    )
    pages_id = add_object("<< /Type /Pages /Kids [4 0 R] /Count 1 >>")
    catalog_id = add_object("<< /Type /Catalog /Pages 5 0 R >>")

    data = bytearray()
    data.extend(b"%PDF-1.4\n%\xC7\xEC\x8F\xA2\n")
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        if isinstance(obj, bytes):
            data.extend(obj)
        else:
            data.extend(obj.encode("ascii"))
        data.extend(b"\nendobj\n")

    xref_start = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return data


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    stream = build_content()
    pdf_bytes = make_pdf(stream)
    OUTPUT.write_bytes(pdf_bytes)
    print(OUTPUT)


if __name__ == "__main__":
    main()
