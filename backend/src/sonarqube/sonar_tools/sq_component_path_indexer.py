import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

import pprint
import fnmatch
import urllib.parse
from typing import Dict, List, Optional, Any, Tuple

import requests
import pandas as pd  # for optional CSV export in save_index
from backend.src.data_io.file_writer import FileWriter


class SQComponentPathIndexer:
    """
    Index and materialize repository file paths from the SonarQube components API.

    Focus:
      - FILE-level components (qualifier=FIL), i.e., actual source files (leaves).
      - Build a repo-like local skeleton, optionally filled with sources via /api/sources/raw.

    Key capabilities:
      1) Fetch paginated components (project + optional branch/PR).
      2) Extract repo-relative paths and metadata (name/language/module/ext).
      3) Materialize local directory tree and (optionally) write sources.
      4) Persist raw pages and/or the derived index (JSONL/CSV).

    Important notes:
      - Token-based auth: username=<token>, password="" (env var SONARQUBE_TOKEN by default).
      - Local filters (include_languages / exclude_globs) only affect *index rows*, not server responses.
      - /api/components/tree only returns files known to and included in the Sonar analysis. Files excluded
        by sonar.exclusions, unrecognized languages, etc., will not appear.
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
        include_languages: Optional[Tuple[str, ...]] = None,
        exclude_globs: Optional[Tuple[str, ...]] = (
            "**/obj/**",
            "**/bin/**",
            "**/x64/**",
            "**/.vs/**",
            "**/packages/**",
            "**/.NETFramework,Version=*/**",
        ),
    ):
        """
        Args:
            base_url: SonarQube base URL, e.g. "http://sonarqube:9000".
            project_key: Project key as shown in SonarQube.
            token_env: Env var holding the token (default "SONARQUBE_TOKEN").
            branch: Optional branch name (None = server-configured main branch).
            pull_request: Optional PR ID (mutually exclusive with branch).
            page_size: Pagination size (server usually caps at 500).
            timeout: HTTP timeout in seconds.
            include_languages: If None, no language filter; otherwise keep rows with language in the tuple.
            exclude_globs: Local path patterns to exclude (build outputs, etc.).
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.branch = branch
        self.pull_request = pull_request
        self.page_size = page_size
        self.timeout = timeout

        token = os.getenv(token_env, "")
        self.auth = (token, "") if token else None

        self.include_languages = include_languages
        self.exclude_globs = exclude_globs or tuple()

        # caches
        self._last_raw_pages: List[Dict[str, Any]] = []
        self._index_rows: List[Dict[str, Any]] = []

        self._q = urllib.parse.quote  # alias

    # -----------------------------
    # URL builders
    # -----------------------------
    def components_tree_url(self, page: int = 1, extra_params: Optional[Dict[str, Any]] = None) -> str:
        """
        Build URL for /api/components/tree to list FILE-level components for the project.

        Defaults intentionally request *leaf files* to mirror what you click through with "Load more":
          - qualifiers=FIL
          - strategy=leaves
          - ps=page_size
          - p=page

        Callers can override via `extra_params`.
        """
        params = [
            ("component", self.project_key),
            ("qualifiers", "FIL"),
            ("strategy", "leaves"),         # <--- ensure leaf files
            ("ps", str(self.page_size)),
            ("p", str(page)),
        ]
        if self.branch:
            params.append(("branch", self.branch))
        if self.pull_request:
            params.append(("pullRequest", self.pull_request))

        if extra_params:
            # merge/override: later items win
            for k, v in extra_params.items():
                for i, (ek, _) in enumerate(params):
                    if ek == k:
                        params[i] = (k, str(v))
                        break
                else:
                    params.append((k, str(v)))

        return f"{self.base_url}/api/components/tree?" + urllib.parse.urlencode(params)

    def _build_source_url(self, component_key: str) -> str:
        """
        Build /api/sources/raw URL for a given component key with current branch/PR scope.
        """
        url = f"{self.base_url}/api/sources/raw?key={self._q(component_key)}"
        if self.branch:
            url += f"&branch={self._q(self.branch)}"
        if self.pull_request:
            url += f"&pullRequest={self._q(self.pull_request)}"
        return url

    # -----------------------------
    # Core HTTP & helpers
    # -----------------------------
    def _get_json(self, url: str) -> Dict[str, Any]:
        r = requests.get(url, auth=self.auth, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
        return r.json()

    def resolve_main_branch(self) -> Optional[str]:
        """
        Query SonarQube for the project's branches and return the main branch name.
        Returns None if request fails or no branches found.
        """
        url = f"{self.base_url}/api/project_branches/list?project={self._q(self.project_key)}"
        try:
            data = self._get_json(url)
            for b in data.get("branches", []):
                if b.get("isMain"):
                    return b.get("name")
        except Exception:
            return None
        return None

    # -----------------------------
    # Public methods
    # -----------------------------
    def fetch_components_pages(
        self,
        max_pages: int = 9999,
        extra_params: Optional[Dict[str, Any]] = None,
        persist_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch paginated results from /api/components/tree until all pages are covered or `max_pages` is hit.

        Args:
            max_pages: Maximum pages to fetch (safety cap).
            extra_params: Extra query parameters to merge/override.
            persist_to: If provided, append each raw page JSON to a JSONL file (one page per line).

        Returns:
            List of raw page JSON objects (each includes 'components', 'paging', etc.)
        """
        pages: List[Dict[str, Any]] = []
        page = 1

        writer_cm = FileWriter.jsonl_writer(persist_to, mode="w") if persist_to else None
        write_one = writer_cm.__enter__() if writer_cm else None

        try:
            while page <= max_pages:
                url = self.components_tree_url(page=page, extra_params=extra_params)
                try:
                    payload = self._get_json(url)
                except RuntimeError as e:
                    msg = str(e)
                    # If branch is set and server says "not found" for that branch, auto-resolve main and retry once.
                    if self.branch and ("not found" in msg and "on branch" in msg):
                        main_name = self.resolve_main_branch()
                        self.branch = main_name or None  # switch to detected main or drop branch
                        url = self.components_tree_url(page=page, extra_params=extra_params)
                        payload = self._get_json(url)
                    else:
                        raise

                comps = payload.get("components", []) or []
                pages.append(payload)
                if write_one:
                    write_one(payload)  # one JSON object per line

                if not comps:
                    break

                paging = payload.get("paging", {}) or {}
                total = int(paging.get("total", 0) or 0)
                page_size = int(paging.get("pageSize", self.page_size) or self.page_size)
                page_index = int(paging.get("pageIndex", page) or page)

                # continue until we've covered the reported total
                if page_index * page_size >= total:
                    break
                page += 1
        finally:
            if writer_cm:
                writer_cm.__exit__(None, None, None)

        self._last_raw_pages = pages
        return pages

    def extract_paths_from_pages(self, pages: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        From raw pages, extract a deduplicated list of component rows and apply local filters.

        Each returned row has fields:
          - component_key
          - rel_path
          - name
          - language
          - module
          - ext
          - filtered_reason (optional, only if dropped)

        Returns:
            The filtered list of component rows.
        """
        if pages is None:
            pages = self._last_raw_pages

        rows: List[Dict[str, Any]] = []
        seen_keys = set()

        for page in pages:
            for c in page.get("components", []):
                comp_key = c.get("key", "")
                if not comp_key or comp_key in seen_keys:
                    continue

                lang = c.get("language")  # may be None
                rel_path = c.get("path") or ""
                if not rel_path:
                    continue

                name = c.get("name") or ""
                module = rel_path.split("/", 1)[0] if "/" in rel_path else rel_path
                ext = f".{name.split('.')[-1]}" if "." in name else ""

                # Language filter (optional)
                if self.include_languages and (lang not in self.include_languages):
                    # skip silently or record a reason; pick one strategy
                    # row["filtered_reason"] = f"language:{lang}"
                    continue

                # Exclude by glob patterns (optional)
                if rel_path and self._matches_any_glob(rel_path, self.exclude_globs):
                    continue

                rows.append({
                    "component_key": comp_key,
                    "rel_path": rel_path,
                    "name": name,
                    "language": lang,
                    "module": module,
                    "ext": ext,
                })
                seen_keys.add(comp_key)

        self._index_rows = rows
        return rows

    def get_all_paths(self) -> List[str]:
        """
        Return repo-relative paths from the current index (call extract_paths_from_pages first).
        Example: "cpp/oper/EmissionsTank.cpp"
        """
        if not self._index_rows:
            return []
        return [r["rel_path"] for r in self._index_rows if r.get("rel_path")]

    def materialize_repo_skeleton(
        self,
        root_dir: str,
        index_rows: Optional[List[Dict[str, Any]]] = None,
        create_empty_files: bool = True,
        fill_with_source: bool = False,
        overwrite: bool = True,
        fetch_retries: int = 2,
    ) -> List[str]:
        """
        Create local directory structure and optionally fill files with source code.

        Args:
            root_dir: Local folder to create the skeleton in.
            index_rows: If None, use the internal index rows.
            create_empty_files: If True, create files even when source fetch fails (recommended for completeness).
            fill_with_source: If True, fetch /api/sources/raw and write content.
            overwrite: If True, overwrite files if they already exist.
            fetch_retries: Number of retries for /api/sources/raw fetch.

        Returns:
            List[str]: Absolute paths created or filled.
        """
        rows = index_rows or self._index_rows
        created: List[str] = []
        if not rows:
            return created

        for r in rows:
            rel_path = r.get("rel_path")
            comp_key = r.get("component_key")
            if not rel_path:
                continue

            abs_path = os.path.join(root_dir, rel_path)
            abs_dir = os.path.dirname(abs_path)
            os.makedirs(abs_dir, exist_ok=True)

            content = None
            if fill_with_source and comp_key:
                for _ in range(max(1, fetch_retries)):
                    try:
                        resp = requests.get(self._build_source_url(comp_key), auth=self.auth, timeout=self.timeout)
                        if resp.status_code == 200:
                            content = resp.text
                            break
                    except Exception:
                        # swallow and retry
                        pass

            if content is not None:
                if overwrite or not os.path.exists(abs_path):
                    # use errors="replace" to avoid crashes on odd encodings
                    with open(abs_path, "w", encoding="utf-8", errors="replace") as f:
                        f.write(content)
                created.append(abs_path)
            elif create_empty_files:
                if overwrite or not os.path.exists(abs_path):
                    with open(abs_path, "w", encoding="utf-8") as f:
                        f.write("")  # empty placeholder
                created.append(abs_path)

        return created

    def save_index(self, out_jsonl: Optional[str] = None, out_csv: Optional[str] = None) -> None:
        """
        Persist current index rows to JSONL or CSV via FileWriter.

        Args:
            out_jsonl: Path to JSONL file (one row per line).
            out_csv: Path to CSV file (optional).
        """
        if not self._index_rows:
            return

        if out_jsonl:
            # FileWriter.write_jsonl expects an Iterable[dict]
            FileWriter.write_jsonl(self._index_rows, out_jsonl)

        if out_csv:
            # Build a small DataFrame then delegate to FileWriter.write_csv
            df = pd.DataFrame(self._index_rows)
            FileWriter.write_csv(df, out_csv)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _matches_any_glob(path: str, patterns: Tuple[str, ...]) -> bool:
        if not patterns:
            return False
        return any(fnmatch.fnmatch(path, pat) for pat in patterns)


if __name__ == "__main__":
    BASE_URL    = "http://sonarqube1.rnd.aspentech.com:9000"
    PROJECT_KEY = "HysysEngine.Engine"
    BRANCH      = None  # IMPORTANT: use same branch/PR as your issues fetch

    # First full-run: disable local filters to ensure completeness
    indexer = SQComponentPathIndexer(
        base_url=BASE_URL,
        project_key=PROJECT_KEY,
        branch=BRANCH,
        include_languages=None,  # no language filter
        exclude_globs=(),        # disable local exclusions; re-enable later if needed
        page_size=500,
    )

    print("Fetching FILE leaves from SonarQube (paged)...")
    pages = indexer.fetch_components_pages(
        extra_params={"qualifiers": "FIL", "strategy": "leaves"},
        # persist_to="backend/src/outputs/HysysEngine.Engine.components.raw.jsonl",  # optional for auditing
    )

    # Server-reported total (approx; from paging)
    server_total = 0
    for p in pages:
        pg = p.get("paging") or {}
        if "total" in pg:
            try:
                server_total = max(server_total, int(pg.get("total") or 0))
            except Exception:
                pass

    rows = indexer.extract_paths_from_pages(pages)
    all_paths = indexer.get_all_paths()

    print(f"Server-reported total files: ~{server_total}")
    print(f"Indexed (deduped) files:     {len(all_paths)}")
    print("Sample paths:")
    pprint.pp(all_paths[:10])

    outdir = f"backend/src/outputs/{PROJECT_KEY}"
    created = indexer.materialize_repo_skeleton(
        root_dir=outdir,
        index_rows=rows,
        create_empty_files=True,   # build full skeleton for visibility
        fill_with_source=True,     # fill when /api/sources/raw is available
        overwrite=True,
        fetch_retries=2,
    )
    print(f"Snapshot written under: {outdir}")
    print(f"Files created/filled:   {len(created)}")
