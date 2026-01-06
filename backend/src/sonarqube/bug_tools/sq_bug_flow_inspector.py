import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from typing import Dict, Any, Optional
from backend.src.data_io.file_reader import FileReader


class SQBugFlowInspector:
    """
    SonarQube BUG Flow Inspector

    Purpose
    -------
    This component provides a structured and extensible framework to analyze
    SonarQube BUG issues stored in JSONL format and determine whether any
    flow-related metadata exists.

    In SonarQube, BUG issues *may* include:
        - issue["flows"]       : Dataflow traces (multi-step propagation paths)
        - issue["locations"]   : Secondary or related locations

    Not all rules generate flow information. Some bugs are purely single-point
    findings, while certain taint/dataflow rules (depending on language and
    analyzer capabilities) may include detailed flow paths.

    Current Functionality
    ---------------------
    - Read a raw BUG issues JSONL file using FileReader.
    - Support both formats produced by SQIssuesLister:
        * page-per-line    ({"issues": [...], "components": [...]})
        * issue-per-line   (one JSON object per line)
    - For each BUG issue, detect and report:
        * Flow Metadata Present (YES)
        * Flow Metadata Absent  (NO)

    This class intentionally keeps the logic minimal, while reserving clear
    extension points for future enhancements, including:
        - Detailed flow path extraction
        - Flow-aware snippet extraction
        - Multi-location bug analysis
        - Integration with LLM-based fix models (e.g., Copilot / GPT)

    The naming and structure reflect production-quality tooling, while allowing
    incremental feature development as more complex BUG patterns are observed.
    """

    def __init__(self, project_key: Optional[str] = None):
        self.project_key = project_key

    def run(self, jsonl_path: str) -> None:
        """
        Execute flow inspection on BUG issues stored in JSONL format.

        Args:
            jsonl_path: Path to the raw BUG issues JSONL file (e.g., bugs_raw.jsonl)
        """
        print(f"[SQBugFlowInspector] Scanning BUG issues from: {jsonl_path}")

        objects = FileReader.read_jsonl(jsonl_path)
        total = 0

        for obj in objects:
            # Format A: page-per-line ("issues": [...])
            if isinstance(obj, dict) and "issues" in obj and isinstance(obj.get("issues"), list):
                for issue in obj["issues"]:
                    total += 1
                    self._inspect_issue(issue)

            # Format B: single issue per line
            elif isinstance(obj, dict):
                total += 1
                self._inspect_issue(obj)

        print(f"[SQBugFlowInspector] Inspection complete. Total BUG issues scanned: {total}")

    def _inspect_issue(self, issue: Dict[str, Any]) -> None:
        """
        Inspect a single BUG issue and report whether flow-related metadata exists.

        Prints:
            YES  - if 'flows' or 'locations' is present and non-empty
            NO   - otherwise
        """
        issue_key = issue.get("key") or issue.get("issue_key")
        has_flows = bool(issue.get("flows"))
        has_locations = bool(issue.get("locations"))

        if has_flows or has_locations:
            print(f"[Issue {issue_key}] Flow Metadata: YES")
        else:
            print(f"[Issue {issue_key}] Flow Metadata: NO")


if __name__ == "__main__":
    PROJECT_KEY = "HysysEngine.Engine"
    JSONL_PATH = f"backend/src/outputs/{PROJECT_KEY}.bugs/bugs_with_snippets.jsonl"

    inspector = SQBugFlowInspector(project_key=PROJECT_KEY)
    inspector.run(JSONL_PATH)
