import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from typing import List, Dict, Any
from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class BugBlockExtractor:
    """
    Extract indentation-based code blocks for each bug.

    This class starts from the bug snippet (core lines), finds the minimal
    indentation among those lines, and then expands outward by indentation
    layers:

      - Level 0: innermost block (minimal indentation of the snippet)
      - Level 1: outer block when encountering smaller indentation
      - Level 2: further outer block, and so on
      - ...
      - Final level: indentation = 0 (top-level block, usually most of file)

    The goal is to provide a hierarchy of code blocks around each bug location
    that can be used as structured context for LLM-based auto-fix workflows.
    """

    def __init__(self, bug_jsonl_path: str, repo_root: str) -> None:
        """
        Initialize the extractor.

        Args:
            bug_jsonl_path: Path to the JSONL file containing bug entries
                (e.g. bugs_with_snippets.jsonl).
            repo_root: Root directory of the source tree, under which the
                issue "file_path" fields are resolved.
        """
        self.bug_jsonl_path = bug_jsonl_path
        self.repo_root = repo_root

    # ----------------------------------------------------------------------
    # Load bugs JSONL
    # ----------------------------------------------------------------------
    def load_bugs(self) -> List[Dict[str, Any]]:
        """
        Load all bug items from a JSONL file.

        Returns:
            A list of bug dictionaries (one per JSON line).
        """
        return FileReader.read_jsonl(self.bug_jsonl_path)

    # ----------------------------------------------------------------------
    # Resolve the source file path
    # ----------------------------------------------------------------------
    def find_file(self, relative_path: str) -> str:
        """
        Resolve the full path for a given relative file path.

        Args:
            relative_path: Relative path from the repo root, e.g.
                "cpp/oper/control/control.cpp".

        Returns:
            Full file path if it exists; otherwise, None.
        """
        candidate = os.path.join(self.repo_root, relative_path)
        return candidate if os.path.exists(candidate) else None

    # ----------------------------------------------------------------------
    # Main: extract blocks for all bugs
    # ----------------------------------------------------------------------
    def run(self) -> List[Dict[str, Any]]:
        """
        Process all bugs and extract their block layers.

        Returns:
            A list of results, one per bug. Each result contains the bug
            metadata and a list of block layers.
        """
        bugs = self.load_bugs()
        results: List[Dict[str, Any]] = []

        for bug in bugs:
            ctx = self.extract_single_bug(bug)
            results.append(ctx)

        return results

    # ----------------------------------------------------------------------
    # Extract blocks for one bug
    # ----------------------------------------------------------------------
    def extract_single_bug(self, bug: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract indentation-based block layers for a single bug, and include
        all original bug metadata for downstream LLM workflows.
        """
        file_path = self.find_file(bug.get("file_path", ""))

        # If file not found, return metadata + error
        if not file_path:
            out = {k: bug.get(k) for k in bug.keys()}  # include full metadata
            out["error"] = f"Source file not found: {bug.get('file_path', '')}"
            return out

        raw_text = FileReader.read_text(file_path)
        file_lines = raw_text.splitlines(keepends=True)
        total_lines = len(file_lines)

        # Convert start/end to 0-based
        core_start = max(0, min(total_lines - 1, int(bug.get("start_line", 1)) - 1))
        core_end = max(0, min(total_lines - 1, int(bug.get("end_line", 1)) - 1))
        if core_end < core_start:
            core_end = core_start

        blocks = self.extract_blocks(file_lines, core_start, core_end)

        # --- Build final output: include all bug metadata + blocks ---
        result = {k: bug.get(k) for k in bug.keys()}  # passthrough metadata
        result["blocks"] = blocks

        return result

    # ----------------------------------------------------------------------
    # Core logic: extract multi-layer blocks by indentation
    # ----------------------------------------------------------------------
    def extract_blocks(
        self,
        file_lines: List[str],
        core_start: int,
        core_end: int
    ) -> List[Dict[str, Any]]:
        """
        Expand outward from the bug snippet using indentation layers.

        Instead of decrementing indentation by 1 each time, this version
        jumps from the current indentation level to the next *actually
        existing* smaller indentation in the surrounding code. This avoids
        generating multiple identical blocks when there are no intermediate
        indentation levels (e.g. code goes from 12 → 9 directly).
        """
        if not file_lines:
            return []

        # Determine minimal indentation in the snippet (ignore empty lines)
        snippet_indents = [
            self.get_indent(file_lines[i])
            for i in range(core_start, core_end + 1)
            if file_lines[i].strip() != ""
        ]

        if snippet_indents:
            cur_indent = min(snippet_indents)
        else:
            # Fallback: if snippet is all blank lines, treat as top-level
            cur_indent = 0

        blocks: List[Dict[str, Any]] = []
        cur_start = core_start
        cur_end = core_end
        level = 0
        n = len(file_lines)

        while True:
            # -------- Expand upward for current indentation --------
            up = cur_start - 1
            # Also track the first smaller indentation we encounter
            next_indent_candidate = None

            while up >= 0:
                line = file_lines[up]
                if line.strip() != "":
                    indent = self.get_indent(line)
                    if indent < cur_indent:
                        # This is the outer block's indentation candidate
                        next_indent_candidate = indent
                        break
                up -= 1
            new_start = up + 1

            # -------- Expand downward for current indentation --------
            down = cur_end + 1
            while down < n:
                line = file_lines[down]
                if line.strip() != "":
                    indent = self.get_indent(line)
                    if indent < cur_indent:
                        # Combine with upward candidate: choose the outermost
                        if next_indent_candidate is None:
                            next_indent_candidate = indent
                        else:
                            next_indent_candidate = min(next_indent_candidate, indent)
                        break
                down += 1
            new_end = down - 1

            # Extract block code (inclusive)
            block_code = "".join(file_lines[new_start:new_end + 1])

            blocks.append({
                "level": level,
                "indent": cur_indent,
                "start": new_start + 1,  # convert to 1-based
                "end": new_end + 1,
                "code": block_code
            })

            # If we did not find any smaller indentation outside this block,
            # then this block is already the outermost we can get.
            if next_indent_candidate is None or next_indent_candidate < 0:
                break

            # Move to the next outer existing indentation and repeat
            cur_indent = next_indent_candidate
            cur_start, cur_end = new_start, new_end
            level += 1

        return blocks

    # ----------------------------------------------------------------------
    # Indentation helper
    # ----------------------------------------------------------------------
    @staticmethod
    def get_indent(line: str) -> int:
        """
        Count leading spaces of the given line.

        Tabs are treated as width 4 by convention, but here we only count
        spaces to keep it simple. If tabs are common in your codebase, you
        can extend this logic.

        Args:
            line: A single line of code (with or without trailing newline).

        Returns:
            Number of leading spaces.
        """
        # If you later need to treat '\t' explicitly, enhance this function.
        return len(line) - len(line.lstrip(" "))


if __name__ == "__main__":
    BUG_FILE = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_with_snippets.jsonl"
    REPO_ROOT = r"backend/src/outputs/HysysEngine.Engine"

    extractor = BugBlockExtractor(
        bug_jsonl_path=BUG_FILE,
        repo_root=REPO_ROOT
    )

    results = extractor.run()

    print("\n=== Block Extraction Summary ===")
    print(f"Total bugs processed: {len(results)}")

    # Optional: save output for downstream LLM pipelines
    out_path = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_blocks.json"
    FileWriter.write_json(results, out_path)

    print(f"[OK] Block layers saved to: {out_path}")
