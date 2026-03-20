# Legacy Runtime Archive

This directory contains legacy scripts and modules that are now deprecated following the transition to the **Hub v3 (Browser-Grounded)** architecture.

### ⚠️ Warning
**Do not build new features here.** These files are preserved for historical reference and post-mortem analysis of the original brittle interaction models.

### Replacement Mapping
| Legacy Script | Replacement / New Module |
| :--- | :--- |
| `x_link_engine.py` | `tools/xagent_eval/tool.py` |
| `run_workflow.py` | `tools/xagent_eval/transcript_capture.py` |
| `vertical_intel.py` | `tools/xagent_eval/reviewer_runner.py` |

### Statistics
- **Reason for Archiving**: Brittle DOM-click dependencies, lack of concurrency support, and inconsistent transcript capture.
- **Last Known Good Commit**: `82045756784f265bf8111e8480470719e4679e85`
- **Certified Baseline**: Phase 5G (RC1)

### Files Archived
- `x_link_engine.py`
- `run_workflow.py`
- `vertical_intel.py`
- `intel_report_raw.txt`
- `run_mode_test.py`
- `temp_keep.html`
