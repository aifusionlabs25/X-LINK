import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools import synapse_bridge


def test_extract_upload_preview_reads_text(tmp_path):
    sample = tmp_path / "notes.txt"
    sample.write_text("hello world\nthis is a preview", encoding="utf-8")

    preview = synapse_bridge._extract_upload_preview(str(sample))

    assert "hello world" in preview
    assert "preview" in preview


def test_extract_upload_preview_skips_binary_extensions(tmp_path):
    sample = tmp_path / "image.png"
    sample.write_bytes(b"\x89PNG\r\n")

    preview = synapse_bridge._extract_upload_preview(str(sample))

    assert preview == ""


def test_collect_recent_vault_items_includes_uploads(monkeypatch, tmp_path):
    vault_dir = tmp_path / "vault"
    intel_dir = vault_dir / "intel"
    reports_dir = vault_dir / "reports"
    uploads_dir = vault_dir / "artifacts" / "uploads"
    intel_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    uploads_dir.mkdir(parents=True)

    upload_file = uploads_dir / "brief.md"
    upload_file.write_text("# hello", encoding="utf-8")

    monkeypatch.setattr(synapse_bridge, "VAULT_DIR", str(vault_dir))
    monkeypatch.setattr(synapse_bridge, "REPORTS_DIR", str(reports_dir))
    monkeypatch.setattr(synapse_bridge, "UPLOADS_DIR", str(uploads_dir))

    items = synapse_bridge._collect_recent_vault_items(scope="uploads", limit=5)

    assert len(items) == 1
    assert items[0]["name"] == "brief.md"
    assert items[0]["category"] == "uploads"
    assert items[0]["url"].endswith("/artifacts/uploads/brief.md")


def test_build_attachment_context_block_uses_names_and_preview():
    block = synapse_bridge._build_attachment_context_block([
        {
            "name": "research.md",
            "path": r"C:\vault\uploads\research.md",
            "preview": "First paragraph of useful context.",
        }
    ])

    assert "Uploaded file context:" in block
    assert "research.md" in block
    assert "First paragraph of useful context." in block
