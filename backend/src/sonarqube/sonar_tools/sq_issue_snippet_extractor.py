import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import json
from typing import Dict, Any, Iterable, Iterator, Optional, List, Tuple

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class SQIssueSnippetExtractor:
    """
    Map SonarQube issues to local repository files and extract code snippets.

    Responsibilities
    ----------------
    - Read raw issues JSONL from a file path (page-per-line or issue-per-line).
    - Resolve file path and line ranges for each issue.
    - Extract source snippet from the given repo_root.
    - Write normalized results to a target JSONL or JSON file via FileWriter.

    Input JSONL shapes supported
    ----------------------------
    (A) Page-per-line:
        {
          "issues": [...],
          "components": [...],   # optional; used to resolve component->path
          ...
        }
    (B) Issue-per-line:
        {
          "...": "...",          # a single issue object
          "key": "AX...."
        }

    Output record schema (one per issue)
    ------------------------------------
    {
      "issue_key": str | None,
      "project": str | None,
      "component": str | None,
      "rule": str | None,
      "rule_name": str | None,
      "type": str | None,
      "severity": str | None,
      "message": str | None,
      "effort": str | None,
      "tags": list | None,

      "file_path": str | None,        # relative to repo_root
      "start_line": int | None,       # 1-based (inclusive)
      "end_line": int | None,         # 1-based (inclusive)
      "code_snippet": str | None,     # may be truncated to max_chars

      "creation_date": str | None,
      "update_date": str | None,

      # Present only when snippet extraction fails:
      "error": "missing_path" | "missing_start_line" | "invalid_line_numbers" | "file_read_error"
    }
    """

    def __init__(
        self,
        repo_root: str,
        context_lines: int = 0,
        encoding: str = "utf-8",
        max_chars: int = 20000,
        normalize_tabs: bool = False,
    ):
        """
        Args:
            repo_root: Local repository root mirroring Sonar relative paths (e.g., "cpp/...", "src/...").
            context_lines: Extra lines to include above and below [start_line, end_line].
            encoding: Encoding used to read source files from repo_root.
            max_chars: Hard cap for snippet length; longer snippets will be truncated.
            normalize_tabs: If True, replace TABs with spaces in the extracted snippet.
        """
        self.repo_root = os.path.abspath(repo_root)
        self.context_lines = int(context_lines)
        self.encoding = encoding
        self.max_chars = int(max_chars)
        self.normalize_tabs = bool(normalize_tabs)
        self._line_cache: Dict[str, Optional[List[str]]] = {}  # abs_path -> lines or None

    # ------------------------------------------------------------------
    # Public: file-path in -> file-path out (using FileReader/FileWriter)
    # ------------------------------------------------------------------
    def extract_file_to_jsonl(self, issues_jsonl_path: str, out_jsonl_path: str, ensure_ascii: bool = False) -> None:
        """
        Read raw issues JSONL from 'issues_jsonl_path' and write normalized JSONL to 'out_jsonl_path'.
        Uses FileReader/FileWriter as requested.
        """
        text = FileReader.read_text(issues_jsonl_path)
        lines = text.splitlines()  # JSONL: one JSON object per line
        records = self.iter_from_jsonl_lines(lines)
        FileWriter.write_jsonl(records, out_jsonl_path, ensure_ascii=ensure_ascii)

    def extract_file_to_json(self, issues_jsonl_path: str, out_json_path: str, ensure_ascii: bool = False) -> None:
        """
        Read raw issues JSONL from 'issues_jsonl_path' and write a single JSON object {"items": [...]} to 'out_json_path'.
        This materializes all records in memory; prefer JSONL for very large datasets.
        """
        text = FileReader.read_text(issues_jsonl_path)
        lines = text.splitlines()
        items = list(self.iter_from_jsonl_lines(lines))
        FileWriter.write_json_obj({"items": items}, out_json_path, ensure_ascii=ensure_ascii, pretty=True)

    # ------------------------------------------------------------------
    # Core transform: JSONL lines -> normalized records (streaming-friendly)
    # ------------------------------------------------------------------
    def iter_from_jsonl_lines(self, lines: Iterable[str]) -> Iterator[Dict[str, Any]]:
        """
        Convert an iterable of JSONL lines to normalized issue records with code snippets.
        Yields one dict per issue (see schema in class docstring).
        """
        for raw_line in lines:
            line = (raw_line or "").strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except Exception as e:
                yield {"_raw": line, "error": f"json_parse_error: {e}"}
                continue

            # Shape A: page-per-line
            if isinstance(obj, dict) and "issues" in obj and isinstance(obj.get("issues"), list):
                components_idx = self._build_components_index(obj.get("components") or [])
                for issue in obj["issues"]:
                    yield self._issue_to_record(issue, components_idx)
                continue

            # Shape B: single issue per line
            if isinstance(obj, dict) and ("key" in obj or "issue_key" in obj):
                yield self._issue_to_record(obj, components_idx=None)
                continue

            # Unknown shape
            yield {"_raw": obj, "error": "unknown_jsonl_shape"}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _issue_to_record(self, issue: Dict[str, Any], components_idx: Optional[Dict[str, str]]) -> Dict[str, Any]:
        """Normalize one raw issue object and attach a code snippet if possible."""
        # Basic fields (support both Sonar API names and possible custom keys)
        issue_key     = issue.get("key") or issue.get("issue_key")
        rule          = issue.get("rule") or issue.get("rule_key")
        rule_name     = issue.get("rule_name")
        message       = issue.get("message") or issue.get("rule_message")
        severity      = issue.get("severity")
        issue_type    = issue.get("type")
        effort        = issue.get("effort")
        tags          = issue.get("tags")
        creation_date = issue.get("creationDate") or issue.get("creation_date")
        update_date   = issue.get("updateDate") or issue.get("update_date")
        component     = issue.get("component")
        project       = issue.get("project")

        # Resolve relative path
        path = issue.get("path")
        if not path:
            if components_idx and component in components_idx:
                path = components_idx[component]
            elif component and ":" in component:
                # "{project_key}:{relative_path}" -> "relative_path"
                path = component.split(":", 1)[1]

        # Resolve line numbers (1-based)
        tr = issue.get("textRange") or {}
        start_line = tr.get("startLine") or issue.get("start_line")
        end_line   = tr.get("endLine")   or issue.get("end_line") or start_line

        snippet, snip_err = self._extract_snippet(path, start_line, end_line)

        out = {
            "issue_key": issue_key,
            "project": project,
            "component": component,
            "rule": rule,
            "rule_name": rule_name,
            "type": issue_type,
            "severity": severity,
            "message": message,
            "effort": effort,
            "tags": tags,

            "file_path": path,
            "start_line": start_line,
            "end_line": end_line,
            "code_snippet": snippet,

            "creation_date": creation_date,
            "update_date": update_date,
        }
        if snip_err:
            out["error"] = snip_err
        return out

    def _extract_snippet(
        self,
        rel_path: Optional[str],
        start_line: Optional[int],
        end_line: Optional[int],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract source snippet from repo_root/rel_path between [start_line, end_line] (1-based, inclusive),
        with optional context lines and a length cap.
        """
        if not rel_path:
            return None, "missing_path"
        if start_line is None:
            return None, "missing_start_line"

        try:
            s = int(start_line)
            e = int(end_line) if end_line is not None else s
        except Exception:
            return None, "invalid_line_numbers"

        # Apply context; clamp later
        s = max(1, s - self.context_lines)
        e = max(s, e + self.context_lines)

        abs_path = os.path.join(self.repo_root, rel_path)
        lines = self._read_lines(abs_path)
        if lines is None:
            return None, "file_read_error"

        n = len(lines)
        if n == 0:
            return "", None

        s = max(1, min(s, n))
        e = max(1, min(e, n))
        if e < s:
            e = s

        segment = "".join(lines[s - 1 : e])
        if self.normalize_tabs:
            segment = segment.replace("\t", "    ")
        if len(segment) > self.max_chars:
            segment = segment[: self.max_chars] + "\n/* ...TRUNCATED... */\n"

        return segment, None

    def _read_lines(self, abs_path: str) -> Optional[List[str]]:
        """
        Read file content via FileReader and cache the line list.
        Returns None on failure.
        """
        if abs_path in self._line_cache:
            return self._line_cache[abs_path]
        try:
            text = FileReader.read_text(abs_path)
            lines = text.splitlines(keepends=True)
            self._line_cache[abs_path] = lines
            return lines
        except Exception:
            self._line_cache[abs_path] = None
            return None

    @staticmethod
    def _build_components_index(components: List[Dict[str, Any]]) -> Dict[str, str]:
        """Build {component_key -> relative_path} from payload['components']."""
        idx: Dict[str, str] = {}
        for c in components:
            key = c.get("key")
            path = c.get("path")
            if key and path:
                idx[key] = path
        return idx


if __name__ == "__main__":
    ISSUES_RAW = "backend/src/outputs/HysysEngine.Engine.issues/issues_raw.jsonl"
    OUT_JSONL  = "backend/src/outputs/HysysEngine.Engine.issues/issues_with_snippets.jsonl"

    REPO_ROOT  = "backend/src/outputs/HysysEngine.Engine"

    extractor = SQIssueSnippetExtractor(
        repo_root=REPO_ROOT,
        context_lines=2,  
        encoding="utf-8",
        max_chars=20000,  
        normalize_tabs=False,
    )

    extractor.extract_file_to_jsonl(ISSUES_RAW, OUT_JSONL)
    print(f"[OK] Wrote: {OUT_JSONL}")
