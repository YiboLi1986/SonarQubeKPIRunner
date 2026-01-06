import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import json
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, Iterator, List, Optional, Tuple

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter
from backend.src.llm.copilot_client import CopilotClient


class SQIssueAdvisor:
    """
    Iterate issues-with-snippets JSONL, build prompts, call Copilot, and save augmented JSONL.

    Workflow:
      1) Load system/user prompt templates from files.
      2) Read JSONL issues (issue-per-line; page-per-line tolerated).
      3) (Optional) Filter by date window on creation/update/auto.
      4) Rank issues by configurable dimensions (severity/time).
      5) Build prompts per issue, call Copilot, and attach advice:
         copilot_advice = { explanation, code_update, raw, model }
      6) Stream-write updated records to an output JSONL (one record per line).

    User template placeholders supported:
      {issue_key} {severity} {type} {rule} {message}
      {file_path} {start_line} {end_line} {creation_date} {update_date}
      {code_lang} {code_snippet}
    """

    SEVERITY_WEIGHT = {
        "BLOCKER": 5,
        "CRITICAL": 4,
        "MAJOR": 3,
        "MINOR": 2,
        "INFO": 1,
    }

    def __init__(
        self,
        issues_jsonl_path: str,
        system_prompt_path: str,
        user_prompt_path: str,
        out_jsonl_path: str,
        client: Optional[CopilotClient] = None,
        default_code_lang: str = "cpp",
    ) -> None:
        """
        Args:
            issues_jsonl_path: Path to issues_with_snippets.jsonl.
            system_prompt_path: Path to system prompt template file.
            user_prompt_path: Path to user prompt template file.
            out_jsonl_path: Output JSONL path for augmented issues.
            client: Optional CopilotClient; if None, a default one will be created.
            default_code_lang: Fallback language label used in fenced code blocks.
        """
        self.issues_jsonl_path = issues_jsonl_path
        self.system_prompt_path = system_prompt_path
        self.user_prompt_path = user_prompt_path
        self.out_jsonl_path = out_jsonl_path
        self.client = client or CopilotClient()
        self.default_code_lang = default_code_lang

        self._system_tmpl: Optional[str] = None
        self._user_tmpl: Optional[str] = None

    # -------------------------
    # I/O helpers
    # -------------------------
    def load_prompts(self) -> Tuple[str, str]:
        """Load system and user prompt templates from files via FileReader."""
        if self._system_tmpl is None:
            self._system_tmpl = FileReader.read_text(self.system_prompt_path)
        if self._user_tmpl is None:
            self._user_tmpl = FileReader.read_text(self.user_prompt_path)
        return self._system_tmpl, self._user_tmpl

    def _iter_raw_lines(self) -> Iterator[str]:
        """Yield raw lines from the input JSONL (streaming)."""
        with open(self.issues_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if line:
                    yield line

    def iter_issues(self) -> Iterator[Dict[str, Any]]:
        """
        Iterate issues from JSONL. Normally it's one issue per line.
        If a line looks like a 'page' (has 'issues' list), yield each child issue.
        """
        for raw in self._iter_raw_lines():
            try:
                obj = json.loads(raw)
            except Exception as e:
                yield {"_raw": raw, "_parse_error": str(e)}
                continue

            # Issue-per-line (expected shape)
            if isinstance(obj, dict) and ("issue_key" in obj or "key" in obj or "file_path" in obj):
                yield obj
                continue

            # Page-per-line fallback
            if isinstance(obj, dict) and isinstance(obj.get("issues"), list):
                for it in obj["issues"]:
                    yield it
                continue

            # Unknown shape
            yield {"_raw": obj, "_parse_error": "unknown_jsonl_shape"}

    # -------------------------
    # Date/time utils
    # -------------------------
    @staticmethod
    def _parse_sonar_datetime(s: Optional[str]) -> Optional[datetime]:
        """Parse Sonar datetime like '2024-10-19T04:58:11+0000' into aware datetime."""
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            # Fallbacks
            if s.endswith("Z"):
                s = s.replace("Z", "+00:00")
            elif len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
                s = s[:-2] + ":" + s[-2:]
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

    def _normalize_dt_input(self, v: Optional[object]) -> Optional[datetime]:
        """
        Normalize a date/datetime input to an aware datetime in UTC.
        Supports:
          - None -> None
          - datetime -> if naive, assume UTC
          - 'YYYY-MM-DD' -> parsed as UTC midnight
          - ISO-ish strings -> best-effort parse via fromisoformat()
        """
        if v is None:
            return None
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            # 1) Pure date: YYYY-MM-DD
            try:
                d = datetime.strptime(s, "%Y-%m-%d")
                return d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
            # 2) ISO-ish fallback
            try:
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    def _get_issue_timestamp(self, issue: Dict[str, Any], date_field: str = "creation") -> float:
        """
        Return a timestamp for ranking/filtering:
          date_field in {"creation", "update", "auto"}.
          - "creation": use creation_date/creationDate only
          - "update":   use update_date/updateDate only
          - "auto":     prefer creation_date, fallback to update_date
        """
        dt = None
        if date_field == "creation":
            dt = self._parse_sonar_datetime(issue.get("creation_date") or issue.get("creationDate"))
        elif date_field == "update":
            dt = self._parse_sonar_datetime(issue.get("update_date") or issue.get("updateDate"))
        else:  # "auto"
            dt = self._parse_sonar_datetime(issue.get("creation_date") or issue.get("creationDate")) \
                 or self._parse_sonar_datetime(issue.get("update_date") or issue.get("updateDate"))
        return dt.timestamp() if dt else 0.0

    # -------------------------
    # Filtering & ranking
    # -------------------------
    def _severity_weight(self, sev: Optional[str]) -> int:
        return self.SEVERITY_WEIGHT.get((sev or "").upper(), 0)

    def filter_issues_by_date(
        self,
        issues: Iterable[Dict[str, Any]],
        date_since: Optional[object] = None,
        date_until: Optional[object] = None,
        date_on: str = "creation",  # "creation" | "update" | "auto"
    ) -> List[Dict[str, Any]]:
        """
        Filter issues by an inclusive date window on the chosen date field.
        - date_since: include issues with ts >= date_since
        - date_until: include issues with ts <= date_until
        """
        since_dt = self._normalize_dt_input(date_since)
        until_dt = self._normalize_dt_input(date_until)
        since_ts = since_dt.timestamp() if since_dt else None
        until_ts = until_dt.timestamp() if until_dt else None

        out: List[Dict[str, Any]] = []
        for it in issues:
            ts = self._get_issue_timestamp(it, date_on)
            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts > until_ts:
                continue
            out.append(it)
        return out

    def rank_issues(
        self,
        issues: Iterable[Dict[str, Any]],
        primary: str = "severity",            # "severity" | "time"
        secondary: Optional[str] = "time",     # None | "severity" | "time"
        recent_first: bool = True,
        date_on: str = "creation",             # "creation" | "update" | "auto"
    ) -> List[Dict[str, Any]]:
        """
        Rank issues by configurable keys:
          - primary:   "severity" or "time"
          - secondary: None, "severity", or "time"
          - recent_first: when time is used, newer issues rank higher if True
          - date_on: which date field to use for time dimension
        """
        def sev_score(it: Dict[str, Any]) -> int:
            return self._severity_weight(it.get("severity"))

        def time_score(it: Dict[str, Any]) -> float:
            ts = self._get_issue_timestamp(it, date_on)
            return ts if recent_first else -ts

        def make_key(it: Dict[str, Any]) -> tuple:
            keys = []
            if primary == "severity":
                keys.append(sev_score(it))
            elif primary == "time":
                keys.append(time_score(it))
            else:
                keys.append(0)

            if secondary:
                if secondary == "severity":
                    keys.append(sev_score(it))
                elif secondary == "time":
                    keys.append(time_score(it))
                else:
                    keys.append(0)
            return tuple(keys)

        return sorted(list(issues), key=make_key, reverse=True)

    # -------------------------
    # Prompt building
    # -------------------------
    @staticmethod
    def _detect_lang_from_path(path: Optional[str], default: str) -> str:
        if not path:
            return default
        ext = (os.path.splitext(path)[1] or "").lower()
        return {
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".cc": "cpp",
            ".c": "c",
            ".hpp": "cpp",
            ".hxx": "cpp",
            ".hh": "cpp",
            ".h": "c",
            ".cs": "csharp",
            ".java": "java",
            ".py": "python",
        }.get(ext, default)

    def _build_user_prompt_from_issue(self, user_tmpl: str, issue: Dict[str, Any]) -> str:
        """Render the user prompt from the provided template and a single issue dict."""
        code_snippet = issue.get("code_snippet") or ""
        file_path = issue.get("file_path") or issue.get("path") or ""
        code_lang = self._detect_lang_from_path(file_path, self.default_code_lang)

        kwargs = {
            "issue_key": issue.get("issue_key") or issue.get("key") or "",
            "severity": issue.get("severity") or "",
            "type": issue.get("type") or "",
            "rule": issue.get("rule") or "",
            "message": issue.get("message") or "",
            "file_path": file_path,
            "start_line": issue.get("start_line") or (issue.get("textRange") or {}).get("startLine"),
            "end_line": issue.get("end_line") or (issue.get("textRange") or {}).get("endLine"),
            "creation_date": issue.get("creation_date") or issue.get("creationDate") or "",
            "update_date": issue.get("update_date") or issue.get("updateDate") or "",
            "code_lang": code_lang,
            "code_snippet": code_snippet,
        }
        return user_tmpl.format(**kwargs)

    # -------------------------
    # Advice post-processing
    # -------------------------
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

        # Explanation is text before the first fence
        explanation = raw[:start].strip()

        # Find end of the first fence
        end = raw.find("```", start + 3)
        if end != -1:
            code_update = raw[start:end + 3].strip()
        else:
            code_update = raw[start:].strip()

        return {"explanation": explanation, "code_update": code_update, "raw": raw}

    # -------------------------
    # Main processing
    # -------------------------
    def process_and_save(
        self,
        stop_after: Optional[int] = None,
        # ranking config
        rank_before_process: bool = True,
        rank_primary: str = "severity",            # "severity" | "time"
        rank_secondary: Optional[str] = "time",    # None | "severity" | "time"
        recent_first: bool = True,
        date_on: str = "creation",                 # "creation" | "update" | "auto"
        # date filter
        date_since: Optional[object] = None,
        date_until: Optional[object] = None,
        # I/O / model overrides
        ensure_ascii: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Iterate issues, call Copilot, attach advice, and write to output JSONL.

        Args:
            stop_after: If provided, stop after N issues processed.
            rank_before_process: If True, sort by configured keys before processing.
            rank_primary: Primary ranking key ("severity" or "time").
            rank_secondary: Optional secondary key for tie-breaking.
            recent_first: When using time, newer-first if True.
            date_on: Which field to use for time ("creation" | "update" | "auto").
            date_since: Inclusive lower bound for date filter (str/datetime).
            date_until: Inclusive upper bound for date filter (str/datetime).
            ensure_ascii: Passed to writer (JSON escaping).
            temperature: Optional override for this run.
            max_tokens: Optional override for this run.

        Returns:
            Counters dict: {"read": X, "filtered": Y, "processed": Z, "written": W, "errors": E}
        """
        system_tmpl, user_tmpl = self.load_prompts()

        raw_iter = self.iter_issues()
        all_issues = list(raw_iter)

        # 1) Date window filter (inclusive)
        filtered = self.filter_issues_by_date(
            all_issues,
            date_since=date_since,
            date_until=date_until,
            date_on=date_on,
        )

        # 2) Ranking
        issues_list = self.rank_issues(
            filtered,
            primary=rank_primary,
            secondary=rank_secondary,
            recent_first=recent_first,
            date_on=date_on,
        ) if rank_before_process else filtered

        counters = {"read": len(all_issues), "filtered": len(filtered), "processed": 0, "written": 0, "errors": 0}

        overrides: Dict[str, Any] = {}
        if temperature is not None:
            overrides["temperature"] = float(temperature)
        if max_tokens is not None:
            overrides["max_tokens"] = int(max_tokens)

        with FileWriter.jsonl_writer(self.out_jsonl_path, mode="w", ensure_ascii=ensure_ascii) as write_one:
            for issue in issues_list:
                if stop_after is not None and counters["processed"] >= stop_after:
                    break

                # Build prompts
                try:
                    user_prompt = self._build_user_prompt_from_issue(user_tmpl, issue)
                    system_prompt = system_tmpl
                except Exception as e:
                    issue["copilot_advice"] = {
                        "error": f"prompt_build_error: {e}",
                        "model": self.client.model,
                    }
                    write_one(issue)
                    counters["errors"] += 1
                    counters["written"] += 1
                    continue

                # Call model
                try:
                    advice_text = self.client.chat_text(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        **overrides,
                    )
                    parts = self._extract_advice_parts(advice_text)

                    # Optional: attach a simple priority score (severity + creation time)
                    sev_w = self._severity_weight(issue.get("severity"))
                    ts = self._get_issue_timestamp(issue, date_field="creation")
                    priority_score = float(sev_w) * 1_000_000_000 + ts

                    issue["priority_score"] = priority_score
                    issue["copilot_advice"] = {
                        "model": self.client.model,
                        "explanation": parts.get("explanation", ""),
                        "code_update": parts.get("code_update", ""),
                        "raw": parts.get("raw", ""),
                    }
                except Exception as e:
                    issue["copilot_advice"] = {
                        "error": f"model_call_error: {e}",
                        "model": self.client.model,
                    }
                    counters["errors"] += 1

                counters["processed"] += 1
                write_one(issue)
                counters["written"] += 1

        return counters


if __name__ == "__main__":
    PROJECT_KEY = "HysysEngine.Engine"
    INPUT = "backend/src/outputs/HysysEngine.Engine.issues/issues_with_snippets.jsonl"
    SYS_T = "backend/src/prompts/system.sonar.review.txt"
    USR_T = "backend/src/prompts/user.sonar.review.txt"

    # Recommended: write to evaluations folder with timestamp+model
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = f"backend/src/outputs/evaluations/{PROJECT_KEY}/{ts}"
    os.makedirs(out_dir, exist_ok=True)
    OUT = f"{out_dir}/issues_with_advice.jsonl"

    advisor = SQIssueAdvisor(
        issues_jsonl_path=INPUT,
        system_prompt_path=SYS_T,
        user_prompt_path=USR_T,
        out_jsonl_path=OUT,
        client=CopilotClient(model="openai/gpt-4.1", max_tokens=2048, temperature=0.1),
    )

    stats = advisor.process_and_save(
        stop_after=100,                 # or None for all
        rank_before_process=True,
        rank_primary="severity",       # severity first
        rank_secondary=None,           # no tiebreaker (or "time")
        recent_first=True,             # only used if time is used in ranking
        date_on="creation",            # use creation_date for filtering
        date_since="2024-01-01",       # >= 2024-01-01
        date_until=None,               # no upper bound
        temperature=0.1,
        max_tokens=2048,
    )
    print("Done:", json.dumps(stats, ensure_ascii=False))
    print("Saved to:", OUT)
