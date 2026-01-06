import os
import sys
import time  # NEW: for simple rate limiting (sleep between calls)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import json
from datetime import datetime
from typing import Dict, Any, Iterator, Optional, Tuple, List

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter
from backend.src.llm.copilot_client import CopilotClient


class SQBugCallsiteAdvisor:
    """
    Iterate bugs-with-blocks-and-callsites JSON/JSONL, build prompts, call Copilot/LLM,
    and save augmented JSONL.

    Typical workflow:
      1) Input is the output of a previous pipeline
         (e.g. BugBlockExtractor + CallsiteExtractor),
         such as bugs_blocks_callsites.json or .jsonl.
      2) Each bug record contains:
           - rule, message, type, severity, code_snippet, file_path, ...
           - blocks: [ { level, indent, start, end, code }, ... ]
           - anchors: [
                {
                  "kind": "function",
                  "name": "...",
                  "signature": "Boolean Controller::AutoRegisterDll()",
                  "bug_context": { start_line, end_line, code },
                  "call_sites": [
                     {
                       "file": "...",
                       "line": ...,
                       "code": "AutoRegisterDll();",
                       "context_start": ...,
                       "context_end": ...,
                       "context": "local source lines...",
                       "includes": [...],
                       "includes_bug_header": false,
                       "same_dir": true,
                       "same_top_module": false,
                       "score": 4
                     },
                     ...
                  ]
                }
             ]
      3) For each bug:
           - Extract metadata: rule, message, code_snippet, etc.
           - Extract context: the second-to-last block (fallback to last block).
           - Collect candidate call sites from anchors[*].call_sites.
           - Build user prompt from template (with {call_sites_section}).
           - Call Copilot/LLM and parse the reply into:
                bug_callsite_advice = { explanation, code_update, raw, model }
             The explanation is expected to mention which call sites are relevant.
      4) Stream-write augmented bug records into an output JSONL file.

    User template placeholders supported:
      {issue_key} {severity} {type} {rule} {message}
      {file_path} {start_line} {end_line}
      {code_snippet}
      {context_block}
      {call_sites_section}
    """

    def __init__(
        self,
        bugs_path: str,
        system_prompt_path: str,
        user_prompt_path: str,
        out_jsonl_path: str,
        client: Optional[CopilotClient] = None,
        max_callsites: int = 20,
        verbose: bool = True,
        log_every: int = 10,
        # NEW: prompt size and throttling controls
        max_prompt_chars: int = 24000,
        min_callsites: int = 3,
        callsite_step: int = 5,
        sleep_between_calls: float = 0.5,
    ) -> None:
        """
        Args:
            bugs_path: Path to bugs_blocks_callsites.json or .jsonl.
            system_prompt_path: Path to system prompt template file.
            user_prompt_path: Path to user prompt template file.
            out_jsonl_path: Output JSONL path for augmented bugs.
            client: Optional CopilotClient; if None, a default one will be created.
            max_callsites: Max number of callsites to serialize into the prompt per bug
                           (to avoid over-long prompts). The selection is currently the
                           first N callsites as listed in the JSON.
            verbose: Whether to print progress logs to stdout.
            log_every: Print a progress line after processing every N bugs.
            max_prompt_chars: Soft limit on total user prompt character length.
            min_callsites: Minimum number of callsites to keep when shrinking.
            callsite_step: How many callsites to remove per shrink step.
            sleep_between_calls: Seconds to sleep between model calls to reduce 429s.
        """
        self.bugs_path = bugs_path
        self.system_prompt_path = system_prompt_path
        self.user_prompt_path = user_prompt_path
        self.out_jsonl_path = out_jsonl_path
        self.client = client or CopilotClient()
        self.max_callsites = int(max_callsites)

        self.verbose = bool(verbose)
        self.log_every = max(1, int(log_every))

        # Prompt size and throttling settings
        self.max_prompt_chars = int(max_prompt_chars)
        self.min_callsites = int(min_callsites)
        self.callsite_step = int(callsite_step)
        self.sleep_between_calls = float(sleep_between_calls)

        # Heuristic maximum lengths for code/context blocks (in characters)
        self.max_code_snippet_chars = 4000
        self.max_context_block_chars = 4000

        self._system_tmpl: Optional[str] = None
        self._user_tmpl: Optional[str] = None

    # ----------------------------------------------------------------------
    # I/O helpers
    # ----------------------------------------------------------------------
    def load_prompts(self) -> Tuple[str, str]:
        """Load system and user prompt templates from files via FileReader."""
        if self._system_tmpl is None:
            self._system_tmpl = FileReader.read_text(self.system_prompt_path)
        if self._user_tmpl is None:
            self._user_tmpl = FileReader.read_text(self.user_prompt_path)
        return self._system_tmpl, self._user_tmpl

    def _iter_bugs_from_json(self) -> Iterator[Dict[str, Any]]:
        """
        Try to read bugs as a JSON array (list of dicts).
        If this fails, the caller can fall back to JSONL mode.
        """
        try:
            data = FileReader.read_json(self.bugs_path)
        except Exception:
            return iter([])  # return empty iterator on failure

        if isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict):
                    yield obj
        elif isinstance(data, dict):
            # Single dict, still yield it
            yield data

    def _iter_bugs_from_jsonl(self) -> Iterator[Dict[str, Any]]:
        """
        Read bugs from JSONL: one JSON object per line.
        """
        with open(self.bugs_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = (raw or "").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        yield obj
                    else:
                        yield {"_raw": line, "_parse_error": "not_dict"}
                except Exception as e:
                    yield {"_raw": line, "_parse_error": str(e)}

    def iter_bugs(self) -> Iterator[Dict[str, Any]]:
        """
        Iterate bugs from either JSON (array) or JSONL file.
        Priority:
          1) Try JSON (list of objects).
          2) If empty, fall back to JSONL.
        """
        json_iter = list(self._iter_bugs_from_json())
        if json_iter:
            for it in json_iter:
                yield it
            return

        # Fallback to JSONL mode
        for it in self._iter_bugs_from_jsonl():
            yield it

    # ----------------------------------------------------------------------
    # Prompt building helpers
    # ----------------------------------------------------------------------
    def _get_context_block_text(self, bug: Dict[str, Any]) -> str:
        """
        Get the second-to-last block's code as context.
        If there is only one block, use the last (only) block.
        If 'blocks' is missing or not a list, return empty string.

        The returned string includes a small header with line range for clarity.
        """
        blocks = bug.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return ""

        # second-to-last block if possible, else last block
        if len(blocks) >= 2:
            block = blocks[-2]
        else:
            block = blocks[-1]

        start = block.get("start")
        end = block.get("end")
        code = block.get("code", "")

        header = f"// Context block (level {block.get('level')}, lines {start}–{end})\n"
        return header + (code or "")

    def _format_includes(self, includes: Any) -> str:
        """
        Normalize includes (could be list or string) into a multi-line string.
        """
        if includes is None:
            return ""
        if isinstance(includes, list):
            return "\n".join(str(x) for x in includes if x)
        return str(includes)

    def _format_single_callsite(
        self,
        idx: int,
        cs: Dict[str, Any],
        callee_signature: str = "",
    ) -> str:
        """
        Format a single callsite dict into a human-readable block.

        Current JSON fields:
          - file
          - line
          - code                 // call expression, e.g. "AutoRegisterDll();"
          - context_start / context_end
          - context              // local surrounding lines
          - includes             // list of header / comment lines
          - includes_bug_header  // bool
          - same_dir / same_top_module / score // heuristic hints
        """
        file_path = (
            cs.get("file")
            or cs.get("file_path")
            or cs.get("path")
            or ""
        )
        call_line = cs.get("line", "")
        context_start = cs.get("context_start", "")
        context_end = cs.get("context_end", "")
        call_code = cs.get("code") or ""
        snippet = (
            cs.get("context")
            or cs.get("code_snippet")
            or call_code
            or ""
        )
        includes = self._format_includes(cs.get("includes"))

        score = cs.get("score", None)
        same_dir = cs.get("same_dir", None)
        same_top = cs.get("same_top_module", None)
        includes_bug_header = cs.get("includes_bug_header", None)

        lines: List[str] = []
        lines.append(f"// CALLSITE #{idx}")
        if file_path:
            lines.append(f"// File: {file_path}")
        if call_line != "":
            lines.append(f"// Call line: {call_line}")
        if context_start != "" or context_end != "":
            lines.append(f"// Context lines: {context_start}–{context_end}")
        if callee_signature:
            lines.append(f"// Suspected callee signature: {callee_signature}")
        if call_code:
            lines.append(f"// Call expression: {call_code}")
        if score is not None:
            lines.append(f"// Heuristic score: {score}")
        if same_dir is not None:
            lines.append(f"// same_dir: {same_dir}")
        if same_top is not None:
            lines.append(f"// same_top_module: {same_top}")
        if includes_bug_header is not None:
            lines.append(f"// includes_bug_header: {includes_bug_header}")

        if includes:
            lines.append("// Includes around callsite:")
            lines.append(includes)
        if snippet:
            lines.append("// Local call context:")
            lines.append(snippet)

        return "\n".join(lines)

    def _format_call_sites_section(
        self,
        bug: Dict[str, Any],
        max_callsites: Optional[int] = None,
    ) -> str:
        """
        Build a combined text section for all callsites of this bug, up to max_callsites.

        Supports current JSON structure:
        - Prefer bug-level "call_sites" if present.
        - Otherwise, collect from anchors[*].call_sites (your example format).
        """
        # Use override limit if provided, otherwise fall back to self.max_callsites.
        limit = int(max_callsites) if max_callsites is not None else self.max_callsites

        # Bug-level call_sites, if any (future-proof).
        call_sites = (
            bug.get("call_sites")
            or bug.get("callsites")
            or bug.get("callsite_blocks")
        )

        callee_signature = ""

        # Current format: call_sites live under anchors[*].
        if not isinstance(call_sites, list) or not call_sites:
            anchors = bug.get("anchors")
            if isinstance(anchors, list):
                for a in anchors:
                    if not isinstance(a, dict):
                        continue
                    cs = a.get("call_sites")
                    if isinstance(cs, list) and cs:
                        call_sites = cs
                        # Example: "Boolean Controller::AutoRegisterDll()"
                        callee_signature = (
                            a.get("signature")
                            or a.get("name")
                            or ""
                        )
                        break

        if not isinstance(call_sites, list) or not call_sites:
            return "// No call sites were discovered for this bug.\n"

        selected = call_sites[: limit]

        blocks: List[str] = []
        for idx, cs in enumerate(selected, start=1):
            if not isinstance(cs, dict):
                continue
            blocks.append(self._format_single_callsite(idx, cs, callee_signature))

        if not blocks:
            return "// No valid call site objects for this bug.\n"

        section = (
            "// Candidate call sites for this bug (each block is one callsite):\n"
            + "\n\n".join(blocks)
        )
        if len(call_sites) > limit:
            section += (
                f"\n\n// NOTE: There are {len(call_sites)} callsites in total, "
                f"but only the first {limit} are shown here.\n"
            )
        return section

    def _truncate_text(self, text: str, max_chars: int, note: str) -> str:
        """
        Truncate text to at most max_chars, appending a note comment.

        This is used as a last resort to keep the total prompt under a safe size.
        """
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[: max_chars] + f"\n// [TRUNCATED: {note}]\n"

    def _build_user_prompt_from_bug(
        self,
        user_tmpl: str,
        bug: Dict[str, Any],
        max_chars: Optional[int] = None,
    ) -> str:
        """
        Render the user prompt from the provided template and a single
        bug-with-blocks-and-callsites dict, with basic size control.

        Strategy:
          1) Start with self.max_callsites.
          2) If prompt is too long, gradually reduce callsites (from the tail).
          3) If still too long, truncate context_block and code_snippet.
        """
        max_chars = max_chars or self.max_prompt_chars

        # Original full code/context
        code_snippet_full = bug.get("code_snippet") or ""
        context_block_full = self._get_context_block_text(bug)

        # Mutable copies for possible truncation
        code_snippet = code_snippet_full
        context_block = context_block_full
        cs_limit = self.max_callsites

        def build_prompt() -> str:
            call_sites_section = self._format_call_sites_section(
                bug,
                max_callsites=cs_limit,
            )
            kwargs = {
                "issue_key": bug.get("issue_key") or bug.get("key") or "",
                "severity": bug.get("severity") or "",
                "type": bug.get("type") or "",
                "rule": bug.get("rule") or "",
                "message": bug.get("message") or "",
                "file_path": bug.get("file_path") or bug.get("path") or "",
                "start_line": bug.get("start_line") or "",
                "end_line": bug.get("end_line") or "",
                "code_snippet": code_snippet,
                "context_block": context_block,
                "call_sites_section": call_sites_section,
            }
            return user_tmpl.format(**kwargs)

        # Step 0: build with full callsites
        user_prompt = build_prompt()

        # Step 1: shrink callsites while prompt is too long
        while len(user_prompt) > max_chars and cs_limit > self.min_callsites:
            old_cs_limit = cs_limit
            cs_limit = max(self.min_callsites, cs_limit - self.callsite_step)
            if self.verbose:
                print(
                    f"[SQBugCallsiteAdvisor] Prompt too long (len={len(user_prompt)}), "
                    f"shrinking callsites from {old_cs_limit} to {cs_limit}..."
                )
            user_prompt = build_prompt()

        # Step 2: if still too long, truncate context/code
        if len(user_prompt) > max_chars:
            if self.verbose:
                print(
                    f"[SQBugCallsiteAdvisor] Prompt still long after callsite shrink "
                    f"(len={len(user_prompt)}, limit={max_chars}), truncating context/code..."
                )

            context_block = self._truncate_text(
                context_block,
                self.max_context_block_chars,
                "context block",
            )
            code_snippet = self._truncate_text(
                code_snippet,
                self.max_code_snippet_chars,
                "code snippet",
            )
            user_prompt = build_prompt()

            if self.verbose and len(user_prompt) > max_chars:
                print(
                    f"[SQBugCallsiteAdvisor] WARNING: prompt still exceeds limit "
                    f"(len={len(user_prompt)}, limit={max_chars}) after truncation."
                )

        return user_prompt

    # ----------------------------------------------------------------------
    # Advice post-processing
    # ----------------------------------------------------------------------
    def _extract_advice_parts(self, text: str) -> Dict[str, str]:
        """
        Split model reply into 'explanation' and 'code_update'.

        Strategy:
          1) If reply is a JSON object with keys, read them directly.
          2) Otherwise, take the text before the first code fence as 'explanation',
             and the first fenced code block as 'code_update'.

        Returns:
          {"explanation": "...", "code_update": "...", "raw": original_text}
        """
        explanation, code_update = "", ""
        raw = text or ""

        # Try JSON first
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                exp = obj.get("explanation") or obj.get("reasoning") or ""
                upd = obj.get("code_update") or obj.get("patch") or obj.get("code") or ""
                if exp or upd:
                    return {"explanation": str(exp), "code_update": str(upd), "raw": raw}
        except Exception:
            pass

        # Fallback: split by first fenced code block
        start = raw.find("```")
        if start == -1:
            # No code fence; everything is explanation
            explanation = raw.strip()
            code_update = ""
            return {"explanation": explanation, "code_update": code_update, "raw": raw}

        explanation = raw[:start].strip()

        end = raw.find("```", start + 3)
        if end != -1:
            code_update = raw[start:end + 3].strip()
        else:
            code_update = raw[start:].strip()

        return {"explanation": explanation, "code_update": code_update, "raw": raw}

    # ----------------------------------------------------------------------
    # Main processing
    # ----------------------------------------------------------------------
    def process_and_save(
        self,
        stop_after: Optional[int] = None,
        ensure_ascii: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Iterate bugs-with-blocks-and-callsites, call the LLM client, attach advice,
        and write to output JSONL.

        Important:
            - Input bug objects contain a "blocks" field (potentially large).
            - Output records WILL NOT include "blocks".
              Only the original non-block metadata is preserved,
              plus the generated advice under "bug_callsite_advice".
            - Callsite information (e.g. "anchors" and "call_sites") is preserved
              verbatim in the output so that downstream stages can still analyze
              or visualize it.
        """
        system_tmpl, user_tmpl = self.load_prompts()

        bugs_iter = self.iter_bugs()
        bugs_list = list(bugs_iter)

        counters = {
            "read": len(bugs_list),
            "processed": 0,
            "written": 0,
            "errors": 0,
        }

        if self.verbose:
            print(
                f"[SQBugCallsiteAdvisor] Loaded {counters['read']} bugs from {self.bugs_path}"
            )
            if stop_after is not None:
                print(f"[SQBugCallsiteAdvisor] Will stop after {stop_after} bugs.")

        overrides: Dict[str, Any] = {}
        if temperature is not None:
            overrides["temperature"] = float(temperature)
        if max_tokens is not None:
            overrides["max_tokens"] = int(max_tokens)

        with FileWriter.jsonl_writer(self.out_jsonl_path, mode="w", ensure_ascii=ensure_ascii) as write_one:
            for bug in bugs_list:
                if stop_after is not None and counters["processed"] >= stop_after:
                    break

                issue_key = bug.get("issue_key") or bug.get("key") or "<unknown>"

                # -------------------------------------------------------------
                # Build prompts (using blocks & callsites internally for context)
                # -------------------------------------------------------------
                try:
                    user_prompt = self._build_user_prompt_from_bug(
                        user_tmpl,
                        bug,
                        max_chars=self.max_prompt_chars,
                    )
                    system_prompt = system_tmpl
                except Exception as e:
                    # Prepare output object WITHOUT blocks
                    clean_bug = {k: v for k, v in bug.items() if k != "blocks"}
                    clean_bug["bug_callsite_advice"] = {
                        "error": f"prompt_build_error: {e}",
                        "model": self.client.model,
                    }
                    write_one(clean_bug)
                    counters["errors"] += 1
                    counters["written"] += 1

                    if self.verbose:
                        print(
                            f"[SQBugCallsiteAdvisor] Prompt build error for bug {issue_key}: {e}"
                        )
                    continue

                # -------------------------------------------------------------
                # Call model
                # -------------------------------------------------------------
                try:
                    advice_text = self.client.chat_text(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        **overrides,
                    )
                    parts = self._extract_advice_parts(advice_text)

                    # Prepare output object WITHOUT blocks
                    clean_bug = {k: v for k, v in bug.items() if k != "blocks"}
                    clean_bug["bug_callsite_advice"] = {
                        "model": self.client.model,
                        "explanation": parts.get("explanation", ""),
                        "code_update": parts.get("code_update", ""),
                        "raw": parts.get("raw", ""),
                    }

                except Exception as e:
                    clean_bug = {k: v for k, v in bug.items() if k != "blocks"}
                    clean_bug["bug_callsite_advice"] = {
                        "error": f"model_call_error: {e}",
                        "model": self.client.model,
                    }
                    counters["errors"] += 1

                    if self.verbose:
                        print(
                            f"[SQBugCallsiteAdvisor] Model call error for bug {issue_key}: {e}"
                        )

                # -------------------------------------------------------------
                # Write output record
                # -------------------------------------------------------------
                counters["processed"] += 1
                write_one(clean_bug)
                counters["written"] += 1

                # Progress logging
                if self.verbose:
                    if (
                        counters["processed"] == 1
                        or counters["processed"] % self.log_every == 0
                        or counters["processed"] == counters["read"]
                        or (
                            stop_after is not None
                            and counters["processed"] == stop_after
                        )
                    ):
                        print(
                            f"[SQBugCallsiteAdvisor] Progress: "
                            f"{counters['processed']}/{counters['read']} processed, "
                            f"{counters['errors']} errors so far."
                        )

                # Simple throttling to reduce 429 Too Many Requests
                if self.sleep_between_calls > 0:
                    time.sleep(self.sleep_between_calls)

        if self.verbose:
            print(
                f"[SQBugCallsiteAdvisor] Finished. "
                f"Processed={counters['processed']}, Errors={counters['errors']}, "
                f"Written={counters['written']} -> {self.out_jsonl_path}"
            )

        return counters


if __name__ == "__main__":
    PROJECT_KEY = "HysysEngine.Engine"

    BUGS_IN = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_with_anchors_and_calls.json"
    SYS_T = r"backend/src/prompts/system.bug_callsite.review.txt"
    USR_T = r"backend/src/prompts/user.bug_callsite.review.txt"

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = f"backend/src/outputs/evaluations/{PROJECT_KEY}/bug_callsites/{ts}"
    os.makedirs(out_dir, exist_ok=True)
    OUT = f"{out_dir}/bugs_with_bug_callsite_advice.jsonl"

    advisor = SQBugCallsiteAdvisor(
        bugs_path=BUGS_IN,
        system_prompt_path=SYS_T,
        user_prompt_path=USR_T,
        out_jsonl_path=OUT,
        client=CopilotClient(model="openai/gpt-4.1", max_tokens=2048, temperature=0.1),
        max_callsites=20,
        verbose=True,      # print progress logs
        log_every=10,      # print every 10 bugs
        # NEW: you can tune these if needed
        max_prompt_chars=24000,
        min_callsites=3,
        callsite_step=5,
        sleep_between_calls=1,
    )

    stats = advisor.process_and_save(
        stop_after=200,        # or e.g. 100 for testing
        ensure_ascii=False,
        temperature=0.1,
        max_tokens=2048,
    )

    print("Done:", json.dumps(stats, ensure_ascii=False))
    print("Saved to:", OUT)
