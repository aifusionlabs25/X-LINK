"""
Wait for the active MEL session to finish, then launch the overnight MEL loop.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

MEL_DIR = ROOT_DIR / "vault" / "mel"
PROGRESS_FILE = MEL_DIR / "progress.json"
SESSION_PID_FILE = MEL_DIR / "session.pid"
OVERNIGHT_DIR = MEL_DIR / "overnight"


def _load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {"running": False}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False}


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def mel_is_running() -> bool:
    progress = _load_progress()
    if progress.get("running"):
        return True
    if SESSION_PID_FILE.exists():
        try:
            pid = int(SESSION_PID_FILE.read_text(encoding="utf-8").strip())
            return _pid_running(pid)
        except Exception:
            return False
    return False


def write_launcher_log(run_dir: Path, message: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "deferred_launcher.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {message}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for active MEL to finish, then launch overnight MEL loop.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--packs", default="default_pack")
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--scenarios", type=int, default=2)
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--difficulty", default="mixed")
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--wait-timeout-minutes", type=int, default=360)
    parser.add_argument("--min-improvement", type=float, default=8.0)
    parser.add_argument("--min-score", type=float, default=78.0)
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OVERNIGHT_DIR / f"deferred_{args.agent}_{ts}"
    write_launcher_log(run_dir, "Deferred overnight MEL watcher started.")

    deadline = time.time() + (args.wait_timeout_minutes * 60)
    while time.time() < deadline:
        if not mel_is_running():
            write_launcher_log(run_dir, "Detected idle MEL state. Launching overnight MEL loop.")
            cmd = [
                sys.executable,
                str(ROOT_DIR / "tools" / "overnight_mel_loop.py"),
                "--agent",
                args.agent,
                "--packs",
                args.packs,
                "--cycles",
                str(args.cycles),
                "--scenarios",
                str(args.scenarios),
                "--turns",
                str(args.turns),
                "--difficulty",
                args.difficulty,
                "--min-improvement",
                str(args.min_improvement),
                "--min-score",
                str(args.min_score),
            ]
            result = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
            write_launcher_log(run_dir, f"Overnight MEL loop exit code: {result.returncode}")
            if result.stdout:
                write_launcher_log(run_dir, f"stdout: {result.stdout.strip()}")
            if result.stderr:
                write_launcher_log(run_dir, f"stderr: {result.stderr.strip()}")
            return
        write_launcher_log(run_dir, "MEL still running; sleeping before next check.")
        time.sleep(max(5, args.poll_seconds))

    write_launcher_log(run_dir, "Watcher timed out before MEL became idle.")


if __name__ == "__main__":
    main()
