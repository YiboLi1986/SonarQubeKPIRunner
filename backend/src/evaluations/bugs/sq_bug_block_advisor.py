import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import json
from datetime import datetime
from typing import Dict, Any, Iterator, Optional, Tuple

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter
from backend.src.llm.copilot_client import CopilotClient


class SQBugBlockAdvisor:
    """
    Iterate bugs-with-blocks JSON/JSONL, build prompts, call Copilot/LLM, and save augmented JSONL.

    Typical workflow:
      1) Input is the output of BugBlockExtractor, e.g. bugs_blocks.json or bugs_blocks.jsonl.
      2) Each bug record contains:
           - rule, message, type, severity, code_snippet, file_path, ...
           - blocks: [ { level, indent, start, end, code }, ... ]
      3) For each bug:
           - Extract metadata: rule, message, code_snippet
           - Extract context: the second-to-last block (fallback to last block if only one)
           - Build user prompt from template
           - Call Copilot/LLM and parse the reply into:
                bug_block_advice = { explanation, code_update, raw, model }
      4) Stream-write augmented bug records into an output JSONL file.

    User template placeholders supported:
      {issue_key} {severity} {type} {rule} {message}
      {file_path} {start_line} {end_line}
      {code_snippet}
      {context_block}
    """

    def __init__(
        self,
        bugs_path: str,
        system_prompt_path: str,
        user_prompt_path: str,
        out_jsonl_path: str,
        client: Optional[CopilotClient] = None,
    ) -> None:
        """
        Args:
            bugs_path: Path to bugs_blocks.json or bugs_blocks.jsonl.
            system_prompt_path: Path to system prompt template file.
            user_prompt_path: Path to user prompt template file.
            out_jsonl_path: Output JSONL path for augmented bugs.
            client: Optional CopilotClient; if None, a default one will be created.
        """
        self.bugs_path = bugs_path
        self.system_prompt_path = system_prompt_path
        self.user_prompt_path = user_prompt_path
        self.out_jsonl_path = out_jsonl_path
        self.client = client or CopilotClient()

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

    def _build_user_prompt_from_bug(self, user_tmpl: str, bug: Dict[str, Any]) -> str:
        """
        Render the user prompt from the provided template and a single bug-with-blocks dict.

        Template placeholders supported:
          {issue_key} {severity} {type} {rule} {message}
          {file_path} {start_line} {end_line}
          {code_snippet}
          {context_block}
        """
        code_snippet = bug.get("code_snippet") or ""
        context_block = self._get_context_block_text(bug)

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
        }

        return user_tmpl.format(**kwargs)

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
        Iterate bugs-with-blocks, call the LLM client, attach advice, and write
        to output JSONL.

        Important:
            - Input bug objects contain a "blocks" field (potentially large).
            - Output records WILL NOT include "blocks".
              Only the original non-block metadata is preserved,
              plus the generated advice under "bug_block_advice".
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

        overrides: Dict[str, Any] = {}
        if temperature is not None:
            overrides["temperature"] = float(temperature)
        if max_tokens is not None:
            overrides["max_tokens"] = int(max_tokens)

        with FileWriter.jsonl_writer(self.out_jsonl_path, mode="w", ensure_ascii=ensure_ascii) as write_one:
            for bug in bugs_list:
                if stop_after is not None and counters["processed"] >= stop_after:
                    break

                # -------------------------------------------------------------
                # Build prompts (using blocks internally for context)
                # -------------------------------------------------------------
                try:
                    user_prompt = self._build_user_prompt_from_bug(user_tmpl, bug)
                    system_prompt = system_tmpl
                except Exception as e:
                    # Prepare output object WITHOUT blocks
                    clean_bug = {k: v for k, v in bug.items() if k != "blocks"}
                    clean_bug["bug_block_advice"] = {
                        "error": f"prompt_build_error: {e}",
                        "model": self.client.model,
                    }
                    write_one(clean_bug)
                    counters["errors"] += 1
                    counters["written"] += 1
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
                    clean_bug["bug_block_advice"] = {
                        "model": self.client.model,
                        "explanation": parts.get("explanation", ""),
                        "code_update": parts.get("code_update", ""),
                        "raw": parts.get("raw", ""),
                    }

                except Exception as e:
                    clean_bug = {k: v for k, v in bug.items() if k != "blocks"}
                    clean_bug["bug_block_advice"] = {
                        "error": f"model_call_error: {e}",
                        "model": self.client.model,
                    }
                    counters["errors"] += 1

                # -------------------------------------------------------------
                # Write output record
                # -------------------------------------------------------------
                counters["processed"] += 1
                write_one(clean_bug)
                counters["written"] += 1

        return counters


if __name__ == "__main__":
    PROJECT_KEY = "HysysEngine.Engine"

    BUGS_IN = r"backend/src/outputs/HysysEngine.Engine.bugs/bugs_blocks.json"
    SYS_T = r"backend/src/prompts/system.bug_block.review.txt"
    USR_T = r"backend/src/prompts/user.bug_block.review.txt"

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = f"backend/src/outputs/evaluations/{PROJECT_KEY}/bug_blocks/{ts}"
    os.makedirs(out_dir, exist_ok=True)
    OUT = f"{out_dir}/bugs_with_bug_block_advice.jsonl"

    advisor = SQBugBlockAdvisor(
        bugs_path=BUGS_IN,
        system_prompt_path=SYS_T,
        user_prompt_path=USR_T,
        out_jsonl_path=OUT,
        client=CopilotClient(model="openai/gpt-4.1", max_tokens=2048, temperature=0.1),
    )

    stats = advisor.process_and_save(
        stop_after=10,        # or e.g. 100 for testing
        ensure_ascii=False,
        temperature=0.1,
        max_tokens=2048,
    )

    print("Done:", json.dumps(stats, ensure_ascii=False))
    print("Saved to:", OUT)
