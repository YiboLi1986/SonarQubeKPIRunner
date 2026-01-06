import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class BugReferenceScanner:
    """
    For each Sonar / Bug item, locate its enclosing function definition
    (the "anchor") and then search the repository for potential call sites
    of that function, applying several heuristic filters and ranking signals.

    High-level pipeline:
      1) Load bug items with indentation-based blocks (output of BugBlockExtractor).
      2) For each bug:
         - Use the last block (whole-file block) and a line window above the
           bug line to locate the closest enclosing function definition.
             * Only treat a line as a function definition if it:
                 - contains '(' and ')'
                 - does not end with ';' (exclude declarations)
                 - is not an obvious control-flow line (if/for/while/...)
                 - has strictly smaller indentation than the bug line
                   (helps avoid treating file-level code as belonging to
                    the previous function).
         - Extract the function name and the optional class name from the signature.
         - Attach a local bug context window around the bug lines.
         - Extract a simple include-block from the top of the function's file.
      3) For each function anchor, use ripgrep (rg) to search the repository
         for potential call sites of this function name and build a call-site list:
             * Skip header files when ignore_headers is True.
             * Skip files under certain non-core folders (tests, tools, examples, ...).
             * Skip lines that look like function definitions for this func_name.
             * If we know the anchor's class_name, skip lines that clearly belong
               to a different class's method with the same func_name.
             * For each remaining candidate line:
                 - Build a local context window around the call-site line.
                 - Extract the include-block for that file.
                 - Compute simple ranking signals:
                     · whether the file includes the bug's header (by stem)
                     · whether the file is in the same directory as the bug file
                     · whether the top-level module directory matches
                 - Combine these into a numeric "score".
      4) Sort call sites by score (descending), and optionally keep only the
         top-N highest scoring sites per anchor (controlled by max_call_sites).

    Notes:
        - This is a lightweight heuristic approach, not a full C++ parser.
        - The goal is to gather a reasonably small, high-quality set of
          candidate call sites so that an LLM can further analyze and decide
          which references are truly related to the bug.
        - ripgrep results are cached per (func_name, def_file_name) so that
          multiple bugs under the same function do not repeatedly scan
          the entire repository.
    """

    def __init__(
        self,
        bugs_blocks_path: str,
        repo_root: str,
        search_window: int = 200,
        context_window: int = 6,
        max_bugs: Optional[int] = None,
        max_call_sites: Optional[int] = None,
    ) -> None:
        """
        Args:
            bugs_blocks_path: Path to JSON file produced by BugBlockExtractor.
            repo_root: Root directory of the C++ repository to search.
            search_window: Max number of lines above the bug line to scan
                           when looking for the enclosing function definition.
            context_window: Number of lines before/after a target line to include
                            in local context snippets.
            max_bugs: Optional limit for how many bugs to process (for debugging).
            max_call_sites: Optional limit for how many top-ranked call sites to
                            keep per function anchor. If None, keep all.
        """
        self.bugs_blocks_path = bugs_blocks_path
        self.repo_root = Path(repo_root)
        self.search_window = max(1, int(search_window))
        self.context_window = max(1, int(context_window))
        self.max_bugs = max_bugs
        self.max_call_sites = max_call_sites

        # Simple in-memory cache for file contents (per relative path).
        self._file_cache: Dict[str, List[str]] = {}

        # Cache for rg results per (func_name, def_file_name).
        # This avoids scanning the whole repo multiple times for the same function.
        self._rg_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        # Simple directory blacklist for non-core logic folders.
        self._excluded_dir_names = {
            "test", "tests", "testing",
            "example", "examples",
            "demo", "demos",
            "tool", "tools",
        }

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def run(self) -> List[Dict[str, Any]]:
        """
        Process all bugs and attach function anchors + their ranked call sites.
        Also prints simple progress information.
        """
        bugs: List[Dict[str, Any]] = FileReader.read_json(self.bugs_blocks_path)

        if self.max_bugs is not None:
            bugs = bugs[: self.max_bugs]

        total = len(bugs)
        print(f"[INFO] Loaded {total} bugs from {self.bugs_blocks_path}")

        results: List[Dict[str, Any]] = []

        for idx, bug in enumerate(bugs, start=1):
            issue_key = bug.get("issue_key", "")
            file_rel = bug.get("file_path", "")
            print(f"[INFO] Processing bug {idx}/{total} "
                  f"(issue_key={issue_key}, file={file_rel}) ...")

            enriched = self._process_single_bug(bug)
            results.append(enriched)

        print("[INFO] Completed processing all bugs.")
        return results

    # ------------------------------------------------------------------
    def _process_single_bug(self, bug: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process one bug:
          - Use the whole-file block (last block) to locate the closest
            enclosing function definition above the bug line (anchor).
          - If found, parse class_name, attach bug-local context and
            def-file includes.
          - Search for potential call sites using ripgrep (with caching)
            and attach ranked call sites to the anchor.
        """
        # Copy all original metadata
        out: Dict[str, Any] = dict(bug)

        file_rel = bug.get("file_path")
        bug_start = int(bug.get("start_line", 1))
        bug_end = int(bug.get("end_line", bug_start))
        blocks: List[Dict[str, Any]] = bug.get("blocks", [])

        if not file_rel:
            out["anchors"] = []
            out["error"] = "Missing file_path in bug metadata."
            return out

        if not blocks:
            out["anchors"] = []
            out["error"] = "Missing blocks; please run BugBlockExtractor first."
            return out

        # Assume the last block is the whole-file block, as produced by BugBlockExtractor.
        whole_block = blocks[-1]

        # Step 2–3: find the closest enclosing function definition in whole-file block
        anchor = self._find_enclosing_function_in_block(
            block=whole_block,
            bug_start=bug_start,
            bug_end=bug_end,
            file_path=file_rel,
        )

        if anchor is None:
            # No function found in the search window; treat as file-level bug for now.
            out["anchors"] = []
            out["error"] = (
                "No function definition found in search window above bug line."
            )
            return out

        # Attach class name parsed from the signature, if any.
        class_name = self._extract_class_name(anchor.get("signature", ""))
        anchor["class_name"] = class_name

        # Attach bug-local context (around the bug location in the same file)
        bug_context = self._build_bug_context(
            block=whole_block,
            bug_start=bug_start,
            bug_end=bug_end,
        )
        anchor["bug_context"] = bug_context

        # Attach include block for the definition file
        def_includes = self._get_file_includes(file_rel)
        anchor["def_includes"] = def_includes

        # Step 4: search for potential call sites of this function in the repo,
        # using a simple cache keyed by (func_name, def_file_name).
        func_name = anchor["name"]
        def_file_name = os.path.basename(anchor["def_file"])

        bug_dir = os.path.dirname(file_rel) or ""
        header_stem = Path(file_rel).stem  # e.g., "control" from "cpp/.../control.cpp"

        cache_key = (func_name, def_file_name)
        if cache_key in self._rg_cache:
            call_sites = self._rg_cache[cache_key]
        else:
            call_sites = self._search_call_sites(
                func_name=func_name,
                def_file=def_file_name,
                bug_dir=bug_dir,
                header_stem=header_stem,
                class_name=class_name,
            )
            self._rg_cache[cache_key] = call_sites

        anchor["call_sites"] = call_sites

        out["anchors"] = [anchor]
        return out

    # ------------------------------------------------------------------
    # Step 2–3: locate enclosing function in whole-file block
    # ------------------------------------------------------------------
    def _find_enclosing_function_in_block(
        self,
        block: Dict[str, Any],
        bug_start: int,
        bug_end: int,
        file_path: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Given the whole-file indentation-based block, scan a window above the
        bug line to find the closest line that looks like a C++ function
        definition.

        Extra heuristic:
          - We also require the function definition line to have a strictly
            smaller indentation than the bug line. This helps avoid treating
            file-level / global code as if it belonged to the previous function.
        """
        block_start = int(block.get("start", 1))
        block_end = int(block.get("end", block_start))
        code = block.get("code", "")
        lines = code.splitlines()

        if not lines:
            return None

        # Compute the indentation of the bug start line within this block,
        # if possible. We treat "indentation" as the count of leading
        # whitespace characters of that line.
        bug_indent: Optional[int] = None
        if block_start <= bug_start <= block_end:
            bug_idx = bug_start - block_start  # 0-based index
            if 0 <= bug_idx < len(lines):
                bug_line = lines[bug_idx]
                bug_indent = len(bug_line) - len(bug_line.lstrip())

        # Define the line window in source coordinates (1-based).
        search_end_line = min(bug_start, block_end)
        search_start_line = max(block_start, search_end_line - self.search_window)

        # Traverse from src_line = search_end_line down to search_start_line.
        for src_line in range(search_end_line, search_start_line - 1, -1):
            local_idx = src_line - block_start
            if local_idx < 0 or local_idx >= len(lines):
                continue

            line = lines[local_idx]
            stripped = line.strip()
            if not stripped:
                continue

            lower = stripped.lower()

            # Skip obvious control-flow constructs that are not function definitions.
            if lower.startswith(
                ("if ", "for ", "while ", "switch ", "catch ", "else", "do ")
            ):
                continue

            # Heuristic: looks like a function definition:
            #   - Contains '(' and ')'
            #   - Does not end with ';' (to exclude pure declarations)
            if "(" in stripped and ")" in stripped and not stripped.endswith(";"):
                # Extra heuristic: if we know the bug line indentation, require
                # the function definition to be less indented (i.e., more to the left).
                if bug_indent is not None:
                    def_indent = len(line) - len(line.lstrip())
                    if def_indent >= bug_indent:
                        # Same or deeper indentation than bug line: very unlikely
                        # to be the enclosing function header, so skip it.
                        continue

                func_name = self._extract_function_name(stripped)
                if not func_name:
                    continue

                anchor = {
                    "kind": "function",
                    "name": func_name,
                    "def_file": file_path,
                    "def_line": src_line,  # 1-based
                    "block_level": int(block.get("level", -1)),
                    "block_indent": int(block.get("indent", -1)),
                    "signature": stripped,
                }
                return anchor

        # No function definition found within the window
        return None

    # ------------------------------------------------------------------
    # Bug-local context (around bug lines) from whole-file block
    # ------------------------------------------------------------------
    def _build_bug_context(
        self,
        block: Dict[str, Any],
        bug_start: int,
        bug_end: int,
    ) -> Dict[str, Any]:
        """
        Build a small context snippet around the bug location, using the
        whole-file block code.
        """
        block_start = int(block.get("start", 1))
        block_end = int(block.get("end", block_start))
        code = block.get("code", "")
        lines = code.splitlines()

        if not lines:
            return {
                "start_line": bug_start,
                "end_line": bug_end,
                "code": "",
            }

        ctx_start = max(block_start, bug_start - self.context_window)
        ctx_end = min(block_end, bug_end + self.context_window)

        local_start = max(0, ctx_start - block_start)
        local_end = min(len(lines) - 1, ctx_end - block_start)

        snippet = "\n".join(lines[local_start : local_end + 1])

        return {
            "start_line": ctx_start,
            "end_line": ctx_end,
            "code": snippet,
        }

    # ------------------------------------------------------------------
    # Simple file loading + include extraction helpers
    # ------------------------------------------------------------------
    def _load_file_lines(self, rel_path: str) -> Optional[List[str]]:
        """
        Load a file (relative to repo_root) and cache its content as a list of lines.
        """
        if rel_path in self._file_cache:
            return self._file_cache[rel_path]

        abs_path = self.repo_root / rel_path
        if not abs_path.exists():
            return None

        try:
            text = FileReader.read_text(str(abs_path))
        except Exception:
            return None

        lines = text.splitlines()
        self._file_cache[rel_path] = lines
        return lines

    def _get_file_includes(self, rel_path: str) -> List[str]:
        """
        Extract a simple include block from the top of a file.

        We collect consecutive lines from the top that are:
          - empty/whitespace
          - comments (starting with // or /*)
          - preprocessor includes (#include ...)

        Once we hit a non-include, non-comment, non-empty line, we stop.
        """
        lines = self._load_file_lines(rel_path)
        if not lines:
            return []

        includes: List[str] = []
        for line in lines:
            stripped = line.lstrip()
            if not stripped:
                includes.append(line)
                continue
            if stripped.startswith("//") or stripped.startswith("/*"):
                includes.append(line)
                continue
            if stripped.startswith("#include"):
                includes.append(line)
                continue
            # Stop at first "real" code line
            break

        return includes

    @staticmethod
    def _extract_function_name(line: str) -> Optional[str]:
        """
        Extract a potential C++ function name from a single line.
        """
        try:
            paren_idx = line.index("(")
        except ValueError:
            return None

        before = line[:paren_idx].strip()
        if not before:
            return None

        tokens = before.split()
        if not tokens:
            return None

        candidate = tokens[-1]

        # Strip scope qualifiers like MyClass::Foo -> Foo
        if "::" in candidate:
            candidate = candidate.split("::")[-1]

        # Strip pointer/reference symbols
        candidate = candidate.strip("*&")

        if not candidate:
            return None

        # Filter out some obvious non-function identifiers
        if candidate in {"if", "for", "while", "switch", "return"}:
            return None

        return candidate

    @staticmethod
    def _extract_class_name(signature: str) -> Optional[str]:
        """
        Try to extract a C++ class name from a function signature line,
        e.g. 'Boolean Controller::AutoRegisterDll()' -> 'Controller'.
        """
        if "::" not in signature:
            return None

        # Look only before the first '(' to avoid parameters.
        before_paren = signature.split("(", 1)[0]
        parts = before_paren.split("::")
        if len(parts) < 2:
            return None

        # The second last part should be the class (namespace::Class::Func).
        class_part = parts[-2].strip()
        if not class_part:
            return None

        # Class part may contain trailing return type tokens; take the last token.
        tokens = class_part.split()
        if not tokens:
            return None

        return tokens[-1]

    # ------------------------------------------------------------------
    # Helper: directory blacklist
    # ------------------------------------------------------------------
    def _is_in_excluded_dir(self, rel_path: str) -> bool:
        """
        Return True if the given relative path is under a blacklisted directory.
        """
        path = Path(rel_path)
        for part in path.parts:
            name = part.lower()
            if name in self._excluded_dir_names:
                return True
        return False

    # ------------------------------------------------------------------
    # Helper: detect if a line looks like a function definition
    # ------------------------------------------------------------------
    def _looks_like_function_definition(self, code_line: str, func_name: str) -> bool:
        """
        Heuristic to detect if a line is likely a function definition for any class
        with the given function name, e.g. 'Boolean Controller_MPC::AutoRegisterDll()'.

        We mainly look for '::<func_name>' without a trailing ';'.
        """
        stripped = code_line.strip()
        if not stripped:
            return False
        if "(" not in stripped or ")" not in stripped:
            return False
        if stripped.endswith(";"):
            return False
        # Method definition like 'ReturnType ClassName::FuncName(...)'
        if "::" in stripped and f"::{func_name}" in stripped:
            return True
        return False

    # ------------------------------------------------------------------
    # Helper: detect if a line refers to another class's method
    # ------------------------------------------------------------------
    def _belongs_to_other_class(
        self,
        code_line: str,
        func_name: str,
        class_name: Optional[str],
    ) -> bool:
        """
        If we know the anchor's class_name, detect whether this line is a call or
        definition on a *different* class, e.g.:

          anchor:   class_name = 'Controller'
          line:     'Boolean Controller_MPC::AutoRegisterDll()'

        In that case we consider it unrelated and skip it.
        """
        if not class_name:
            return False

        stripped = code_line.strip()
        if f"{class_name}::{func_name}" in stripped:
            # Same class, this is fine.
            return False

        if "::" not in stripped or f"::{func_name}" not in stripped:
            return False

        # Try to find the qualifier before '::func_name'
        marker = f"::{func_name}"
        idx = stripped.find(marker)
        if idx <= 0:
            return False

        left = stripped[:idx].rstrip()
        if not left:
            return False

        # Take the last token as the qualifier (may be ClassName / Namespace::ClassName).
        qualifier_token = left.split()[-1]
        # If there are nested scopes, take the last piece.
        qualifier = qualifier_token.split("::")[-1]

        # Different from the anchor's class -> treat as other class.
        return qualifier != class_name

    # ------------------------------------------------------------------
    # Helper: check whether includes mention the bug header
    # ------------------------------------------------------------------
    @staticmethod
    def _includes_bug_header(
        includes: List[str],
        header_stem: str,
    ) -> bool:
        """
        Return True if any of the include lines mention a header whose stem matches
        the bug file stem (e.g., 'control' -> 'control.h', 'control.hpp', etc.).
        """
        if not header_stem:
            return False

        candidates = [
            f"{header_stem}.h",
            f"{header_stem}.hpp",
            f"{header_stem}.hh",
            f"{header_stem}.hxx",
        ]

        for line in includes:
            for cand in candidates:
                if cand in line:
                    return True
        return False

    # ------------------------------------------------------------------
    # Step 4: search call sites using ripgrep, and attach context/includes
    # ------------------------------------------------------------------
    def _search_call_sites(
        self,
        func_name: str,
        def_file: str,
        bug_dir: str,
        header_stem: str,
        class_name: Optional[str],
        ignore_headers: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Use ripgrep (rg) to search all places where 'func_name(' appears, and
        enrich each hit with a local context snippet and the include block
        of the corresponding file.

        In addition, apply the following heuristics:
          - Skip files under certain non-core directories (tests, tools, examples, ...).
          - Skip lines that look like function definitions (e.g. 'Xxx::FuncName()').
          - Skip lines that are calls/defs on a different class when class_name is known.
          - Compute simple ranking signals:
                * whether the file includes the bug's header (by stem)
                * whether the file is in the same directory as the bug file
                * whether the top-level module directory matches
          - Combine these signals into a numeric score, sort by score (descending),
            and optionally keep only the top-N call sites per anchor.
        """
        pattern = rf"{func_name}\s*\("

        cmd: List[str] = [
            "rg",
            "--line-number",
            "--word-regexp",
            pattern,
            str(self.repo_root),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
        except FileNotFoundError:
            # ripgrep is not installed or not found in PATH
            return [{
                "file": "",
                "line": 0,
                "code": "",
                "context_start": 0,
                "context_end": 0,
                "context": "",
                "includes": [],
                "includes_bug_header": False,
                "same_dir": False,
                "same_top_module": False,
                "score": 0,
                "error": "ripgrep (rg) not found in PATH.",
            }]

        # rg return codes:
        #   0: matches found
        #   1: no matches
        #   2: error (bad regex, IO error, etc.)
        if result.returncode == 1:
            # No matches in the repository
            return []
        elif result.returncode not in (0, 1):
            return [{
                "file": "",
                "line": 0,
                "code": "",
                "context_start": 0,
                "context_end": 0,
                "context": "",
                "includes": [],
                "includes_bug_header": False,
                "same_dir": False,
                "same_top_module": False,
                "score": 0,
                "error": f"rg failed with code {result.returncode}: {result.stderr.strip()}",
            }]

        stdout = result.stdout or ""
        call_sites: List[Dict[str, Any]] = []

        bug_dir_path = Path(bug_dir) if bug_dir else None
        bug_top_module = bug_dir.split(os.sep)[0] if bug_dir else ""

        for line in stdout.splitlines():
            # Typical rg output line:
            #   path/to/file.cpp:123:    Foo(bar);
            try:
                path_str, lineno_str, code_snippet = line.split(":", 2)
            except ValueError:
                continue

            path = Path(path_str)
            try:
                lineno = int(lineno_str)
            except ValueError:
                continue

            # Optionally skip header files
            if ignore_headers and path.suffix in {".h", ".hpp", ".hh", ".hxx"}:
                continue

            # Convert to a path relative to repo_root, if possible, for checks.
            try:
                rel_path_for_check = str(path.relative_to(self.repo_root))
            except ValueError:
                rel_path_for_check = path_str

            # Skip files under excluded directories.
            if self._is_in_excluded_dir(rel_path_for_check):
                continue

            code_line = code_snippet.strip()

            # Skip lines that look like function definitions for this func_name.
            if self._looks_like_function_definition(code_line, func_name):
                continue

            # If anchor has a class_name, skip lines that clearly belong
            # to another class's method with the same func_name.
            if self._belongs_to_other_class(code_line, func_name, class_name):
                continue

            rel_path = rel_path_for_check

            # Load file lines for this call-site file
            file_lines = self._load_file_lines(rel_path)
            if not file_lines:
                call_sites.append({
                    "file": rel_path,
                    "line": lineno,
                    "code": code_line,
                    "context_start": lineno,
                    "context_end": lineno,
                    "context": "",
                    "includes": [],
                    "includes_bug_header": False,
                    "same_dir": False,
                    "same_top_module": False,
                    "score": 0,
                    "error": "Failed to load file for context.",
                })
                continue

            # Build local context window around the call-site line
            idx = lineno - 1
            ctx_start_idx = max(0, idx - self.context_window)
            ctx_end_idx = min(len(file_lines) - 1, idx + self.context_window)
            ctx_start_line = ctx_start_idx + 1
            ctx_end_line = ctx_end_idx + 1

            ctx_snippet = "\n".join(file_lines[ctx_start_idx : ctx_end_idx + 1])

            # Extract include block for this file
            includes = self._get_file_includes(rel_path)

            # Compute ranking signals.
            includes_bug_header = self._includes_bug_header(includes, header_stem)

            call_dir = Path(rel_path).parent
            same_dir = bool(bug_dir_path and call_dir == bug_dir_path)

            call_top_module = rel_path.split(os.sep)[0]
            same_top_module = bool(bug_top_module and bug_top_module == call_top_module)

            score = 1  # base score for being a candidate
            if same_dir:
                score += 3
            elif same_top_module:
                score += 1

            if includes_bug_header:
                score += 3

            call_sites.append({
                "file": rel_path,
                "line": lineno,
                "code": code_line,
                "context_start": ctx_start_line,
                "context_end": ctx_end_line,
                "context": ctx_snippet,
                "includes": includes,
                "includes_bug_header": includes_bug_header,
                "same_dir": same_dir,
                "same_top_module": same_top_module,
                "score": score,
            })

        # Sort by score (descending) so that the most likely related call sites
        # appear first.
        call_sites.sort(key=lambda cs: cs.get("score", 0), reverse=True)

        # If a per-anchor limit is configured, keep only the top-N.
        if self.max_call_sites is not None and self.max_call_sites > 0:
            call_sites = call_sites[: self.max_call_sites]

        return call_sites


if __name__ == "__main__":
    BUG_BLOCKS = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_blocks.json"
    REPO_ROOT = r"backend/src/outputs/HysysEngine.Engine"

    scanner = BugReferenceScanner(
        bugs_blocks_path=BUG_BLOCKS,
        repo_root=REPO_ROOT,
        search_window=200,
        context_window=6,
        max_bugs=200,         # still keep a small number while testing
        max_call_sites=20,   # e.g. keep top 20 call sites per anchor
    )

    results = scanner.run()

    out_path = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_with_anchors_and_calls.json"
    FileWriter.write_json(results, out_path)

    print(f"[OK] Bug reference analysis saved to: {out_path}")
