import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import urllib.parse
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

import requests
from backend.src.data_io.file_writer import FileWriter


class SQIssuesLister:
    """
    Minimal raw fetcher for SonarQube issues.

    What it does:
      - Build /api/issues/search URL with filters (project + branch/PR).
      - Page through results (ps=page_size, p=1..N).
      - Save EACH raw page JSON to a JSONL file (one JSON object per line).

    Advanced:
      - fetch_all_sharded(): Bypasses SonarQube's 10,000 results cap by:
          * time-window splitting (createdAfter/createdBefore)
          * and, if even a tiny window still hits the cap, fallback partitioning by
            severities and/or types (e.g., BLOCKER..INFO, BUG/VULNERABILITY/CODE_SMELL).
      - Newest-first crawl via `newest_first=True` (right-half-first sharding).
      - `stop_after`: early stop after ~N issues (page granularity).

    Not included:
      - No normalization, no rule lookups, no joins. Raw only.
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
        sort_field: str = "CREATION_DATE",  # or "UPDATE_DATE"
        sort_asc: bool = True,              # True=oldest->newest, False=newest->oldest
    ):
        """
        Args:
            base_url: SonarQube base URL, e.g., "http://sonarqube:9000".
            project_key: Project key as shown in Sonar.
            token_env: Env var that stores the token (username=token, password="").
            branch: Optional branch name; if None, server default main is used.
            pull_request: Optional PR ID (mutually exclusive with branch).
            page_size: Per-page size (clamped to [1, 500]).
            timeout: HTTP request timeout in seconds.
            sort_field: Server-side sort ('CREATION_DATE' or 'UPDATE_DATE').
            sort_asc: Sort ascending (True) or descending (False).
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.branch = branch
        self.pull_request = pull_request
        self.page_size = max(1, min(int(page_size), 500))  # clamp to server max
        self.timeout = timeout
        self.sort_field = sort_field
        self.sort_asc = bool(sort_asc)

        token = os.getenv(token_env, "")
        self.auth = (token, "") if token else None
        self._q = urllib.parse.quote

    # -----------------------------
    # URL builder
    # -----------------------------
    def issues_url(
        self,
        page: int = 1,
        statuses: Optional[str] = None,
        resolved: Optional[bool] = None,
        severities: Optional[str] = None,
        types: Optional[str] = None,
        component_keys: Optional[str] = None,
        created_after_iso: Optional[str] = None,
        created_before_iso: Optional[str] = None,
        sort_field: Optional[str] = None,
        asc: Optional[bool] = None,
        additional: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Build the /api/issues/search URL scoped to project (+branch/PR) with filters.
        """
        params: List[Tuple[str, str]] = [
            ("projects", self.project_key),
            ("ps", str(self.page_size)),
            ("p", str(page)),
        ]
        if self.branch:
            params.append(("branch", self.branch))
        if self.pull_request:
            params.append(("pullRequest", self.pull_request))
        if statuses:
            params.append(("statuses", statuses))
        if resolved is not None:
            params.append(("resolved", "true" if resolved else "false"))
        if severities:
            params.append(("severities", severities))
        if types:
            params.append(("types", types))
        if component_keys:
            params.append(("componentKeys", component_keys))
        if created_after_iso:
            params.append(("createdAfter", created_after_iso))
        if created_before_iso:
            params.append(("createdBefore", created_before_iso))

        # Sorting
        s_field = sort_field if sort_field is not None else self.sort_field
        s_asc = asc if asc is not None else self.sort_asc
        if s_field:
            params.append(("s", s_field))
            params.append(("asc", "true" if s_asc else "false"))

        if additional:
            for k, v in additional.items():
                # override if exists
                for i, (ek, _) in enumerate(params):
                    if ek == k:
                        params[i] = (k, str(v))
                        break
                else:
                    params.append((k, str(v)))

        return f"{self.base_url}/api/issues/search?" + urllib.parse.urlencode(params)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _iso_utc(dt: datetime) -> str:
        """Format datetime as Sonar-compatible UTC string: YYYY-MM-DDTHH:MM:SS+0000"""
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")

    # -----------------------------
    # Raw fetch & save (simple pagination, no sharding)
    # -----------------------------
    def fetch_and_save_raw(
        self,
        out_jsonl: str,
        max_pages: int = 9999,
        ensure_ascii: bool = False,
        stop_after: Optional[int] = None,
        **filters: Any,
    ) -> Dict[str, int]:
        """
        Fetch paged raw JSON and write ONE PAGE PER LINE to JSONL.

        Use this when the total results are below SonarQube's 10k cap.

        Args:
            out_jsonl: Output path for JSONL (one JSON page per line).
            max_pages: Safety cap on pages (default 9999).
            ensure_ascii: Whether to escape non-ASCII in JSON.
            stop_after: Early stop after ~N issues (page granularity).
            **filters: Any issues_url() filters (statuses, severities, types, etc).

        Returns:
            dict counters with: pages, issues_in_last_page, issues_total, total_reported
        """
        counters = {"pages": 0, "issues_in_last_page": 0, "issues_total": 0, "total_reported": 0}
        with FileWriter.jsonl_writer(out_jsonl, mode="w", ensure_ascii=ensure_ascii) as write_one:
            p = 1
            while p <= max_pages:
                url = self.issues_url(page=p, **filters)
                r = requests.get(url, auth=self.auth, timeout=self.timeout)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")

                payload = r.json()
                issues = payload.get("issues", []) or []
                paging = payload.get("paging", {}) or {}
                total = int(paging.get("total", 0) or 0)
                page_size = int(paging.get("pageSize", self.page_size) or self.page_size)
                page_index = int(paging.get("pageIndex", p) or p)

                write_one(payload)  # page-per-line
                counters["pages"] += 1
                counters["issues_in_last_page"] = len(issues)
                counters["issues_total"] += len(issues)
                counters["total_reported"] = total

                if stop_after is not None and counters["issues_total"] >= stop_after:
                    break
                if not issues or page_index * page_size >= total:
                    break
                p += 1
        return counters

    # -----------------------------
    # Raw fetch with automatic sharding (handle 10k cap)
    # -----------------------------
    def fetch_all_sharded(
        self,
        out_jsonl: str,
        start_dt: datetime,
        end_dt: datetime,
        ensure_ascii: bool = False,
        min_window_seconds: int = 1,
        stop_after: Optional[int] = None,
        newest_first: bool = False,
        # Fallback partitions if a tiny window still hits 10k:
        fallback_severities: Optional[List[str]] = ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"),
        fallback_types: Optional[List[str]] = ("BUG", "VULNERABILITY", "CODE_SMELL"),
        **filters: Any,
    ) -> Dict[str, int]:
        """
        Fetch ALL issues across a time range. Primary sharding by time window; if a tiny
        window still hits the 10k cap (e.g., mass-created at the same second), fallback
        to severity/type partitions inside that window.

        Output: ONE PAGE PER LINE JSONL (same format as fetch_and_save_raw).

        Args:
            out_jsonl: Output JSONL path.
            start_dt: Start datetime (inclusive); converted to UTC.
            end_dt: End datetime (exclusive); converted to UTC.
            ensure_ascii: Whether to escape non-ASCII in output.
            min_window_seconds: Minimal shard size to avoid infinite recursion.
            stop_after: Early stop after ~N issues (page granularity).
            newest_first: If True, crawl newer half first (right-half-first sharding) and
                          per-shard pages sorted newest->oldest.
            fallback_severities: Sequence of severity buckets for fallback partitioning.
                                 Set to None/() to disable severity fallback.
            fallback_types: Sequence of type buckets for fallback partitioning.
                            Set to None/() to disable type fallback.
            **filters: Base filters (statuses, severities, types...). If you already pass
                       'severities' or 'types' here, the corresponding fallback will be skipped.

        Returns:
            dict: {"pages": ..., "issues_total": ..., "windows": ..., "shard_splits": ...}
        """
        counters = {"pages": 0, "issues_total": 0, "windows": 0, "shard_splits": 0}
        stop_flag = False

        # Determine page sort direction inside each shard
        per_shard_asc = not newest_first

        # If user already fixed severities/types in base filters, skip that fallback layer
        base_has_sev = ("severities" in filters and bool(filters["severities"]))
        base_has_typ = ("types" in filters and bool(filters["types"]))

        def _loop_pages(sdt: datetime, edt: datetime, write_one, extra_filters: Optional[Dict[str, str]] = None) -> bool:
            """
            Loop pages for [sdt, edt). Return True if all pages done; False if we hit 10k cap.
            """
            nonlocal stop_flag
            p = 1
            first_page_in_window = True
            merged_filters = dict(filters)
            if extra_filters:
                # merge, but don't overwrite existing keys in a surprising way
                for k, v in extra_filters.items():
                    if k in merged_filters and merged_filters[k]:
                        # already constrained by caller; keep it
                        continue
                    merged_filters[k] = v

            while not stop_flag:
                url = self.issues_url(
                    page=p,
                    created_after_iso=self._iso_utc(sdt),
                    created_before_iso=self._iso_utc(edt),
                    sort_field=self.sort_field,
                    asc=per_shard_asc,
                    **merged_filters,
                )
                r = requests.get(url, auth=self.auth, timeout=self.timeout)

                if r.status_code == 400 and "Can return only the first 10000 results" in r.text:
                    return False  # signal to caller to fallback/split

                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")

                payload = r.json()
                issues = payload.get("issues", []) or []
                paging = payload.get("paging", {}) or {}
                total = int(paging.get("total", 0) or 0)
                page_size = int(paging.get("pageSize", self.page_size) or self.page_size)
                page_index = int(paging.get("pageIndex", p) or p)

                write_one(payload)
                counters["pages"] += 1
                counters["issues_total"] += len(issues)

                if first_page_in_window:
                    counters["windows"] += 1
                    first_page_in_window = False

                if stop_after is not None and counters["issues_total"] >= stop_after:
                    stop_flag = True
                    break

                if not issues or page_index * page_size >= total:
                    break
                p += 1
            return True

        def _process_window(sdt: datetime, edt: datetime, write_one) -> None:
            nonlocal stop_flag
            if stop_flag or edt <= sdt:
                return

            # First, try the whole window
            ok = _loop_pages(sdt, edt, write_one, extra_filters=None)
            if ok or stop_flag:
                return

            # If the whole window still hits 10k, split by time (binary)
            mid = sdt + (edt - sdt) / 2
            counters["shard_splits"] += 1

            halves = ((mid, edt), (sdt, mid)) if newest_first else ((sdt, mid), (mid, edt))
            for hs, he in halves:
                # Before going deeper in time, try fallback partitioning on this (smaller) window
                # 1) severity buckets (unless user already constrained severities)
                if not base_has_sev and fallback_severities:
                    sev_ok = True
                    for sev in fallback_severities:
                        if stop_flag:
                            break
                        sev_ok = _loop_pages(hs, he, write_one, extra_filters={"severities": sev}) and sev_ok
                    if sev_ok or stop_flag:
                        continue  # this half finished via severity buckets

                # 2) type buckets (unless user already constrained types)
                if not base_has_typ and fallback_types:
                    typ_ok = True
                    for ty in fallback_types:
                        if stop_flag:
                            break
                        typ_ok = _loop_pages(hs, he, write_one, extra_filters={"types": ty}) and typ_ok
                    if typ_ok or stop_flag:
                        continue  # finished via type buckets

                # 3) If still too many (extreme), recurse time again
                if stop_flag:
                    break

                # Minimal-window guard
                if (he - hs).total_seconds() <= max(1, min_window_seconds):
                    raise RuntimeError(
                        "Reached 10k cap on a minimal time window, and fallback partitions still overflow. "
                        "Consider adding additional filters (e.g., statuses/componentKeys) or post-fallback batching."
                    )
                _process_window(hs, he, write_one)
                if stop_flag:
                    break

        with FileWriter.jsonl_writer(out_jsonl, mode="w", ensure_ascii=ensure_ascii) as write_one:
            _process_window(start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), write_one)

        return counters


if __name__ == "__main__":
    BASE_URL = "http://sonarqube1.rnd.aspentech.com:9000"
    PROJECT_KEY = "HysysEngine.Engine"

    lister = SQIssuesLister(
        base_url=BASE_URL,
        project_key=PROJECT_KEY,
        branch=None,       # keep consistent with path/source snapshot scope
        page_size=500,     # throughput-friendly
        sort_field="CREATION_DATE",
        sort_asc=False,    # newest -> oldest within a shard
    )

    out_file = f"backend/src/outputs/{PROJECT_KEY}.issues/issues_raw.jsonl"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    print("Fetching issues newest-first with sharding + fallback (one page per line)...")

    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    end   = datetime.now(timezone.utc)

    summary = lister.fetch_all_sharded(
        out_jsonl=out_file,
        start_dt=start,
        end_dt=end,
        ensure_ascii=False,
        newest_first=True,      # newest -> oldest
        stop_after=None,        # e.g., 20000 to take ~20k newest and stop
        # Optional: narrow scope up-front to speed up
        # statuses="OPEN,REOPENED,CONFIRMED",
        # severities="BLOCKER,CRITICAL,MAJOR",   # if you set this, severity fallback is skipped
        # types="BUG,VULNERABILITY,CODE_SMELL",  # if you set this, type fallback is skipped
    )

    print(
        f"Done. pages written: {summary['pages']}, "
        f"issues (counted): {summary['issues_total']}, "
        f"windows used: {summary['windows']}, "
        f"shard splits: {summary['shard_splits']}. "
        f"Saved to: {out_file}"
    )
