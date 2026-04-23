import os
import subprocess
import json
import re
from typing import Dict, Any
from tools.base_tool import BaseTool, ToolResult

class SystemScoutTool(BaseTool):
    """
    X-LINK System Scout — Gives Hermes the ability to 'see' his project environment.
    Provides file discovery, content inspection, and hardware telemetry.
    """
    key: str = "system_scout"
    description: str = "Gives Hermes the ability to see his project environment, inspect files, and check hardware telemetry."

    async def prepare(self, context: dict, inputs: dict) -> bool:
        # Path Sanitization - Remove Windows absolute prefixes if passed incorrectly
        if isinstance(self.params, dict) and 'path' in self.params:
            p = self.params['path']
            if ':' in p:
                p = p.split(':')[-1].replace('\\', '/').strip('/')
                if p.startswith('AI Fusion Labs/X AGENTS/REPOS/X-LINK/'):
                    p = p.replace('AI Fusion Labs/X AGENTS/REPOS/X-LINK/', '')
                self.params['path'] = p

        self.action = inputs.get("action", "stats")
        self.params = inputs.get("params", {})
        self.project_root = context.get("root_dir", os.getcwd())
        return True

    def _is_safe_path(self, path):
        abs_path = os.path.abspath(os.path.join(self.project_root, path))
        return abs_path.startswith(os.path.abspath(self.project_root))

    async def execute(self, context: dict) -> ToolResult:
        if self.action == "ls":
            self._do_ls()
        elif self.action == "cat":
            self._do_cat()
        elif self.action == "grep":
            self._do_grep()
        elif self.action == "stats":
            self._do_stats()
        else:
            self._mark_error(f"Unknown scout action: {self.action}")
        return self.result

    def _do_ls(self):
        directory = self.params.get("directory", ".")
        if not self._is_safe_path(directory):
            self._mark_error("Access denied: Path outside project root.")
            return
        
        try:
            target = os.path.join(self.project_root, directory)
            items = os.listdir(target)
            results = []
            for item in items:
                full_path = os.path.join(target, item)
                results.append({
                    "name": item,
                    "type": "dir" if os.path.isdir(full_path) else "file",
                    "size": os.path.getsize(full_path) if os.path.isfile(full_path) else 0
                })
            self.result.data = {"directory": directory, "items": results}
            self._mark_success(f"Listed {len(results)} items in '{directory}'.")
        except Exception as e:
            self._mark_error(str(e))

    def _do_cat(self):
        file_path = self.params.get("file")
        start_line = int(self.params.get("start", 1))
        end_line = int(self.params.get("end", 50))
        
        if not file_path:
            self._mark_error("Missing 'file' parameter for cat.")
            return

        if not self._is_safe_path(file_path):
            self._mark_error("Access denied: Path outside project root.")
            return

        try:
            full_path = os.path.join(self.project_root, file_path)
            if not os.path.isfile(full_path):
                self._mark_error(f"File not found: {file_path}")
                return

            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                total_lines = len(lines)
                content = "".join(lines[start_line-1:end_line])
                self.result.data = {
                    "file": file_path,
                    "total_lines": total_lines,
                    "range": f"{start_line}-{min(end_line, total_lines)}",
                    "content": content
                }
                self._mark_success(f"Read {file_path} (lines {start_line}-{min(end_line, total_lines)}).")
        except Exception as e:
            self._mark_error(str(e))

    def _do_grep(self):
        pattern = self.params.get("pattern")
        directory = self.params.get("directory", ".")
        file_ext = self.params.get("ext", ".yaml")

        if not pattern:
            self._mark_error("Missing 'pattern' parameter for grep.")
            return

        if not self._is_safe_path(directory):
            self._mark_error("Access denied: Path outside project root.")
            return

        try:
            results = []
            target_dir = os.path.join(self.project_root, directory)
            regex = re.compile(pattern, re.IGNORECASE)

            for root, dirs, files in os.walk(target_dir):
                if ".git" in root or "node_modules" in root or "venv" in root:
                    continue
                for file in files:
                    if file.endswith(file_ext):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, self.project_root)
                        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                            for i, line in enumerate(f, 1):
                                if regex.search(line):
                                    results.append({
                                        "file": rel_path,
                                        "line": i,
                                        "match": line.strip()
                                    })
                                if len(results) >= 20:
                                    self.result.data = {"results": results, "note": "Capped at 20 matches."}
                                    self._mark_success(f"Grep for '{pattern}' found {len(results)} matches.")
                                    return
            self.result.data = {"results": results}
            self._mark_success(f"Grep for '{pattern}' found {len(results)} matches.")
        except Exception as e:
            self._mark_error(str(e))

    def _do_stats(self):
        """Hardware telemetry for the RTX 5080 and local system."""
        stats = {"gpu": "Unknown", "cpu": "Unknown"}
        
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
                encoding='utf-8'
            ).strip()
            util, mem_used, mem_total, name = output.split(', ')
            stats["gpu"] = {
                "name": name,
                "utilization": f"{util}%",
                "vram_used": f"{mem_used}MB",
                "vram_total": f"{mem_total}MB",
                "vram_pct": f"{round(int(mem_used)/int(mem_total)*100, 1)}%"
            }
        except:
            stats["gpu"] = "nvidia-smi not available"

        self.result.data = stats
        self._mark_success("System stats collected.")

    async def summarize(self, result: ToolResult) -> str:
        if result.status == "error":
            return f"Scout failed: {', '.join(result.errors)}"
        return result.summary
