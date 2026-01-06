import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import re
import html
import json
import urllib.parse
from typing import Dict, List, Optional, Any, Iterable

import requests
from backend.src.data_io.file_writer import FileWriter


class SonarIssueExtractor:
    """
    Extract and export minimal-but-meaningful issues for a SonarQube project.

    For each issue, this class writes/returns:
      - file path (repository-relative)
      - start/end line (or single line)
      - code snippet (plain text; best-effort 'core' slice for single-line issues using offsets)
      - rule information:
          * rule_key
          * rule_message (per-issue short message)
          * rule_name (rule title)
          * rule_description (plain-text explanation of what the rule says)

    It supports:
      - Latest snapshot (all open/unresolved)
      - Delta since previous analysis (i.e., newly introduced issues)
      - Arbitrary time windows via createdAfter/createdBefore
      - Severity/type filters
      - Optional code snippet fetching for speed
      - Streaming export to JSONL (append-per-record) via your FileWriter
    """

    def __init__(
        self,
        base_url: str,
        project_key: str,
        token_env: str = "SONARQUBE_TOKEN",
        branch: Optional[str] = None,
        pull_request: Optional[str] = None,
        page_size: int = 500,
        timeout: int = 30,
    ):
        """
        Initialize with server base URL and project key.

        Args:
            base_url (str): SonarQube server base URL, e.g. "http://sonarqube:9000".
            project_key (str): Project key/name as used in Sonar URLs.
            token_env (str): Env var name holding the token (default "SONARQUBE_TOKEN").
            branch (str, optional): Branch name to scope queries (e.g., "master").
            pull_request (str, optional): Pull Request ID to scope queries.
            page_size (int): Page size for issues pagination (default 500).
            timeout (int): Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.branch = branch
        self.pull_request = pull_request
        self.page_size = page_size
        self.timeout = timeout

        token = os.getenv(token_env, "")
        self.auth = (token, "") if token else None

        # Caches
        self._component_path_cache: Dict[str, str] = {}  # component key -> path
        self._rule_cache: Dict[str, Dict[str, str]] = {}  # rule key -> dict with name/description

        self._q = urllib.parse.quote  # alias

    # -----------------------------
    # URL builders
    # -----------------------------
    def issues_url(
        self,
        page: int = 1,
        created_after_iso: Optional[str] = None,
        created_before_iso: Optional[str] = None,
        statuses: str = "OPEN",
        resolved: bool = False,
        severities: Optional[str] = None,
        types: Optional[str] = None,
    ) -> str:
        """
        Build URL for /api/issues/search scoped to the project (and branch/PR if set).
        """
        params = [
            ("componentKeys", self.project_key),
            ("ps", str(self.page_size)),
            ("p", str(page)),
            ("resolved", "true" if resolved else "false"),
        ]
        if statuses:
            params.append(("statuses", statuses))
        if self.branch:
            params.append(("branch", self.branch))
        if self.pull_request:
            params.append(("pullRequest", self.pull_request))
        if created_after_iso:
            params.append(("createdAfter", created_after_iso))
        if created_before_iso:
            params.append(("createdBefore", created_before_iso))
        if severities:
            params.append(("severities", severities))
        if types:
            params.append(("types", types))
        return f"{self.base_url}/api/issues/search?" + urllib.parse.urlencode(params)

    def components_show_url(self, component_key: str) -> str:
        """
        Build URL for /api/components/show to resolve component key to path.
        """
        return f"{self.base_url}/api/components/show?component={self._q(component_key)}"

    def sources_lines_url(self, component_key: str, start_line: int, end_line: int) -> str:
        """
        Build URL for /api/sources/lines to fetch selected lines of code.
        """
        return (
            f"{self.base_url}/api/sources/lines"
            f"?key={self._q(component_key)}&from={start_line}&to={end_line}&format=txt"
        )

    def project_analyses_url(self, ps: int = 2) -> str:
        """
        Build URL for /api/project_analyses/search to get recent analysis timestamps.
        """
        params = [("project", self.project_key), ("ps", str(ps))]
        if self.branch:
            params.append(("branch", self.branch))
        return f"{self.base_url}/api/project_analyses/search?" + urllib.parse.urlencode(params)

    def rules_show_url(self, rule_key: str) -> str:
        """
        Build URL for /api/rules/show to fetch rule details.
        """
        return f"{self.base_url}/api/rules/show?key={self._q(rule_key)}"

    # -----------------------------
    # HTTP helpers
    # -----------------------------
    def _get_json(self, url: str) -> Dict[str, Any]:
        """
        GET a JSON endpoint and parse the payload.
        """
        r = requests.get(url, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # -----------------------------
    # Cleaning helpers
    # -----------------------------
    def _strip_html(self, text: str) -> str:
        """
        Remove HTML tags and unescape entities from a snippet/description.
        """
        cleaned = re.sub(r"<[^>]+>", "", text or "")
        cleaned = html.unescape(cleaned)
        return cleaned.strip("\n\r ")

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _fill_component_paths_from_envelope(self, envelope: Dict[str, Any]) -> None:
        """
        Populate component key -> path cache using the 'components' section of issues envelope.
        """
        for comp in envelope.get("components", []):
            key = comp.get("key")
            path = comp.get("path") or comp.get("name")
            if key and path:
                self._component_path_cache[key] = path

    def _get_path_for_component(self, component_key: str) -> Optional[str]:
        """
        Resolve a component key to repository-relative path.
        """
        if component_key in self._component_path_cache:
            return self._component_path_cache[component_key]
        try:
            data = self._get_json(self.components_show_url(component_key))
            path = data.get("component", {}).get("path")
            if path:
                self._component_path_cache[key] = path
            return path
        except Exception:
            return None

    def _iter_issues_pages(
        self,
        created_after_iso: Optional[str],
        created_before_iso: Optional[str],
        statuses: str,
        resolved: bool,
        severities: Optional[str],
        types: Optional[str],
    ) -> Iterable[Dict[str, Any]]:
        """
        Iterate issues across pages with the given filters.
        """
        page = 1
        total = None
        seen = 0
        while True:
            url = self.issues_url(
                page=page,
                created_after_iso=created_after_iso,
                created_before_iso=created_before_iso,
                statuses=statuses,
                resolved=resolved,
                severities=severities,
                types=types,
            )
            envelope = self._get_json(url)
            self._fill_component_paths_from_envelope(envelope)

            issues = envelope.get("issues", [])
            for it in issues:
                yield it

            if total is None:
                total = envelope.get("total", 0)
            seen += len(issues)
            if seen >= total or not issues:
                break
            page += 1

    def _fetch_lines_raw(self, component_key: str, start_line: int, end_line: int) -> Optional[str]:
        """
        Fetch selected lines from /api/sources/lines; handle JSON or plain text or HTML.
        """
        try:
            url = self.sources_lines_url(component_key, start_line, end_line)
            r = requests.get(url, auth=self.auth, timeout=self.timeout)
            r.raise_for_status()
            text = r.text
            ct = (r.headers.get("Content-Type", "") or "").lower()
            looks_json = text.lstrip().startswith("{") or text.lstrip().startswith("[")

            if "application/json" in ct or looks_json:
                try:
                    data = r.json()
                    lines = [row.get("code", "") for row in data.get("sources", [])]
                    return "\n".join(lines).rstrip("\n\r")
                except json.JSONDecodeError:
                    # Fallback: retry without format=txt
                    alt = url.replace("&format=txt", "")
                    r2 = requests.get(alt, auth=self.auth, timeout=self.timeout)
                    r2.raise_for_status()
                    return r2.text.strip("\n\r")

            return text.strip("\n\r")
        except Exception:
            return None

    def _build_snippet(
        self,
        component_key: str,
        start_line: int,
        end_line: int,
        start_offset: Optional[int],
        end_offset: Optional[int],
    ) -> Optional[str]:
        """
        Build a clean code snippet. If single-line with offsets, try to return the 'core' slice.
        """
        raw = self._fetch_lines_raw(component_key, start_line, end_line)
        if raw is None:
            return None
        cleaned = self._strip_html(raw)

        # Single line with offsets: try to cut the core substring
        if start_line == end_line and start_offset is not None and end_offset is not None:
            line_text = cleaned.splitlines()[0] if "\n" in cleaned else cleaned
            try:
                if 0 <= start_offset < end_offset <= len(line_text):
                    core = line_text[start_offset:end_offset]
                    return core if core.strip() else line_text
                return line_text
            except Exception:
                return line_text

        # Multi-line or no offsets: return cleaned block
        return cleaned

    def _get_rule_details(self, rule_key: Optional[str]) -> Dict[str, str]:
        """
        Fetch and cache rule details: rule_key, rule_name, rule_description (plain text).
        """
        out = {"rule_key": rule_key or "", "rule_name": "", "rule_description": ""}
        if not rule_key:
            return out
        if rule_key in self._rule_cache:
            return self._rule_cache[rule_key]

        try:
            data = self._get_json(self.rules_show_url(rule_key)).get("rule", {}) or {}
            name = data.get("name") or ""
            desc_html = data.get("htmlDesc") or data.get("mdDesc") or ""
            desc_plain = self._strip_html(desc_html)
            rec = {"rule_key": rule_key, "rule_name": name, "rule_description": desc_plain}
            self._rule_cache[rule_key] = rec
            return rec
        except Exception:
            self._rule_cache[rule_key] = out
            return out

    def _previous_analysis_iso(self) -> Optional[str]:
        """
        Return the ISO8601 timestamp of the previous analysis for the project/branch.
        """
        try:
            data = self._get_json(self.project_analyses_url(ps=2))
            analyses = data.get("analyses", [])
            if len(analyses) >= 2:
                return analyses[1].get("date")
            return None
        except Exception:
            return None

    # -----------------------------
    # Public: iteration & collection
    # -----------------------------
    def iter_minimal_records(
        self,
        created_after_iso: Optional[str] = None,
        created_before_iso: Optional[str] = None,
        since_previous_analysis: bool = False,
        statuses: str = "OPEN",
        resolved: bool = False,
        severities: Optional[str] = None,
        types: Optional[str] = None,
        include_extras: bool = False,
        fetch_snippet: bool = True,
        max_items: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        """
        Yield minimal records (one per issue), honoring filters and max_items.
        """
        if since_previous_analysis and not created_after_iso:
            prev = self._previous_analysis_iso()
            if prev:
                created_after_iso = prev

        count = 0
        for issue in self._iter_issues_pages(
            created_after_iso=created_after_iso,
            created_before_iso=created_before_iso,
            statuses=statuses,
            resolved=resolved,
            severities=severities,
            types=types,
        ):
            component_key = issue.get("component")
            if not component_key:
                continue

            tr = issue.get("textRange") or {}
            start_line = tr.get("startLine") or issue.get("line")
            end_line = tr.get("endLine") or start_line
            start_offset = tr.get("startOffset") if tr else None
            end_offset = tr.get("endOffset") if tr else None

            if not start_line:
                continue  # skip file-level issues for this minimal extractor

            path = self._get_path_for_component(component_key) or component_key

            code_snippet = None
            if fetch_snippet:
                code_snippet = self._build_snippet(
                    component_key=component_key,
                    start_line=int(start_line),
                    end_line=int(end_line),
                    start_offset=start_offset if isinstance(start_offset, int) else None,
                    end_offset=end_offset if isinstance(end_offset, int) else None,
                )

            rule_key = issue.get("rule")
            rule_meta = self._get_rule_details(rule_key)

            rec = {
                "path": path,
                "start_line": int(start_line),
                "end_line": int(end_line),
                "code_snippet": code_snippet,
                "rule_key": rule_meta.get("rule_key", rule_key or ""),
                "rule_message": issue.get("message"),
                "rule_name": rule_meta.get("rule_name", ""),
                "rule_description": rule_meta.get("rule_description", ""),
            }
            if include_extras:
                rec.update(
                    {
                        "severity": issue.get("severity"),
                        "type": issue.get("type"),
                        "issue_key": issue.get("key"),
                    }
                )

            yield rec
            count += 1
            if max_items is not None and count >= max_items:
                break

    def extract_minimal_issues(
        self,
        created_after_iso: Optional[str] = None,
        created_before_iso: Optional[str] = None,
        since_previous_analysis: bool = False,
        statuses: str = "OPEN",
        resolved: bool = False,
        severities: Optional[str] = None,
        types: Optional[str] = None,
        include_extras: bool = False,
        fetch_snippet: bool = True,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Collect minimal issues into a list (useful for quick in-memory experiments).
        """
        return list(
            self.iter_minimal_records(
                created_after_iso=created_after_iso,
                created_before_iso=created_before_iso,
                since_previous_analysis=since_previous_analysis,
                statuses=statuses,
                resolved=resolved,
                severities=severities,
                types=types,
                include_extras=include_extras,
                fetch_snippet=fetch_snippet,
                max_items=max_items,
            )
        )

    # -----------------------------
    # Public: streaming export to JSONL using FileWriter
    # -----------------------------
    def export_to_jsonl(
        self,
        output_path: str,
        created_after_iso: Optional[str] = None,
        created_before_iso: Optional[str] = None,
        since_previous_analysis: bool = False,
        statuses: str = "OPEN",
        resolved: bool = False,
        severities: Optional[str] = None,
        types: Optional[str] = None,
        include_extras: bool = False,
        fetch_snippet: bool = True,
        max_items: Optional[int] = None,
        print_every: int = 20,
        ensure_ascii: bool = False,
        overwrite: bool = True,
        create_empty: bool = True,
    ) -> int:
        """
        Stream issues and append one JSON object per line into `output_path`,
        delegating file I/O to your FileWriter.

        Notes:
            - If overwrite=True, an existing file will be removed first.
            - If create_empty=True, an empty file will be created even if 0 issues match.
        Returns:
            int: Number of records written.
        """
        # Determine createdAfter from previous analysis if requested
        if since_previous_analysis and not created_after_iso:
            prev = self._previous_analysis_iso()
            if prev:
                created_after_iso = prev

        # Prepare output file via FileWriter
        dirpath = os.path.dirname(output_path) or "."
        os.makedirs(dirpath, exist_ok=True)
        if overwrite and os.path.exists(output_path):
            os.remove(output_path)
        if create_empty:
            # Use your FileWriter to create/clear the file
            FileWriter.write_text("", output_path)

        written = 0
        for rec in self.iter_minimal_records(
            created_after_iso=created_after_iso,
            created_before_iso=created_before_iso,
            since_previous_analysis=False,  # already handled above
            statuses=statuses,
            resolved=resolved,
            severities=severities,
            types=types,
            include_extras=include_extras,
            fetch_snippet=fetch_snippet,
            max_items=max_items,
        ):
            # Preferred: use FileWriter.append_jsonl if you added it
            try:
                FileWriter.append_jsonl(rec, output_path, ensure_ascii=ensure_ascii)  # type: ignore[attr-defined]
            except AttributeError:
                # Fallback for when append_jsonl is not present: manual append
                with open(output_path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(rec, ensure_ascii=ensure_ascii) + "\n")

            written += 1
            if print_every and written % print_every == 0:
                print(f"[progress] written: {written}  last: {rec['path']}:{rec['start_line']}-{rec['end_line']}")

        return written


if __name__ == "__main__":
    # ===== Configure your target here =====
    BASE = "http://sonarqube1.rnd.aspentech.com:9000"
    PROJECT = "HysysEngine.Engine"
    BRANCH = "master"          # Set to your target branch; or set None and use pull_request

    OUT = "backend/src/outputs/sonar_issues_with_rules.jsonl"

    extractor = SonarIssueExtractor(
        base_url=BASE,
        project_key=PROJECT,
        branch=BRANCH,
        pull_request=None,     # e.g., "1234" for PR-scoped issues
        page_size=500,
        timeout=30,
    )

    print("=== QUICK EXPORT: newly introduced issues (max 30) ===")
    try:
        n = extractor.export_to_jsonl(
            output_path=OUT,
            since_previous_analysis=True,   # latest delta
            include_extras=True,
            fetch_snippet=True,             # set False for speed if needed
            max_items=30,                   # quick validation cap
            print_every=10,
            overwrite=True,
            create_empty=True,
        )
        print(f"Exported {n} records to {OUT}")

        # Show a few lines so you can eyeball the result quickly
        with open(OUT, "r", encoding="utf-8") as f:
            for _ in range(3):
                line = f.readline()
                if not line:
                    break
                print(line.rstrip())
    except Exception as e:
        print("Error during quick export:", str(e))

    print("\n=== LIST API: latest snapshot, first 3 (no snippet for speed) ===")
    try:
        items = extractor.extract_minimal_issues(
            include_extras=True,
            fetch_snippet=False,
            max_items=3,
        )
        print(f"In-memory records: {len(items)}")
        if items:
            print(json.dumps(items[0], ensure_ascii=False, indent=2))
    except Exception as e:
        print("Error during list extraction:", str(e))
