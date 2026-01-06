import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from datetime import datetime, timezone
from typing import Optional, Any, Dict

from backend.src.sonarqube.sonar_tools.sq_issues_lister import SQIssuesLister


class SQBugsLister:
    """
    Thin wrapper around SQIssuesLister to fetch ONLY SonarQube BUG issues.

    Purpose:
      - Provide a dedicated high-level interface for bug extraction.
      - Automatically sets types="BUG".
      - Handles output directory naming: <project_key>.bugs/
      - Keeps all the advanced sharding / paging logic from SQIssuesLister.

    This class does NOT modify or duplicate SQIssuesLister logic.
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
        sort_field: str = "CREATION_DATE",
        sort_asc: bool = False,
    ):
        """
        Args:
            base_url: SonarQube server URL.
            project_key: Project key in SonarQube.
            token_env: Environment variable storing SQ token.
            branch: Optional branch for scoping.
            pull_request: Optional PR ID for scoping.
            page_size: Page size per API call.
            timeout: HTTP timeout.
            sort_field: Sort by creation/update date.
            sort_asc: Ascending sort. Default: newest-first (False).
        """
        self.project_key = project_key

        # Underlying generic issues lister
        self.lister = SQIssuesLister(
            base_url=base_url,
            project_key=project_key,
            token_env=token_env,
            branch=branch,
            pull_request=pull_request,
            page_size=page_size,
            timeout=timeout,
            sort_field=sort_field,
            sort_asc=sort_asc,
        )

    def fetch_bugs(
        self,
        out_jsonl: str,
        start_dt: datetime,
        end_dt: datetime,
        ensure_ascii: bool = False,
        newest_first: bool = True,
        stop_after: Optional[int] = None,
        **additional_filters: Any,
    ) -> Dict[str, int]:
        """
        Fetch BUG issues ONLY, using the full sharding logic from SQIssuesLister.

        Args:
            out_jsonl: Output JSONL file path.
            start_dt: Start datetime (inclusive).
            end_dt: End datetime (exclusive).
            ensure_ascii: Whether to escape non-ASCII.
            newest_first: Fetch newest windows first.
            stop_after: Optional early stop counter.
            additional_filters: Additional filters like statuses="OPEN,...".

        Returns:
            Dictionary with counters: pages, issues_total, windows, shard_splits.
        """
        # Always enforce types="BUG" so callers don't need to remember it
        filters = dict(additional_filters)
        filters["types"] = "BUG"

        return self.lister.fetch_all_sharded(
            out_jsonl=out_jsonl,
            start_dt=start_dt,
            end_dt=end_dt,
            ensure_ascii=ensure_ascii,
            newest_first=newest_first,
            stop_after=stop_after,
            **filters,
        )


if __name__ == "__main__":
    BASE_URL = "http://sonarqube1.rnd.aspentech.com:9000"
    PROJECT_KEY = "HysysEngine.Engine"

    # Output root folder: *.bugs/
    output_root = f"backend/src/outputs/{PROJECT_KEY}.bugs"
    os.makedirs(output_root, exist_ok=True)

    out_file = os.path.join(output_root, "bugs_raw.jsonl")

    print(f"[SQBugsLister] Fetching BUG issues for project {PROJECT_KEY} ...")

    start = datetime(2000, 8, 1, tzinfo=timezone.utc)
    end   = datetime.now(timezone.utc)

    bugs_lister = SQBugsLister(
        base_url=BASE_URL,
        project_key=PROJECT_KEY,
        sort_asc=False,  # newest -> oldest
    )

    summary = bugs_lister.fetch_bugs(
        out_jsonl=out_file,
        start_dt=start,
        end_dt=end,
        ensure_ascii=False,
        newest_first=True,
        stop_after=None,
        # Optionally:
        # statuses="OPEN,REOPENED,CONFIRMED",
    )

    print(
        f"Done. pages={summary['pages']}, "
        f"bugs={summary['issues_total']}, "
        f"windows={summary['windows']}, "
        f"shard_splits={summary['shard_splits']}.\n"
        f"Saved to: {out_file}"
    )
