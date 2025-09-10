import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import requests
import urllib.parse
from typing import Dict, List, Optional, Any


class SonarKpiUrlBuilder:
    """
    Build SonarQube Web API URLs for KPI extraction (coverage, duplication,
    quality gate status, severe issues, trends, etc.), without auth or I/O.
    """

    def __init__(self, base_url: str, project_key: str, token_env: str = "SONARQUBE_TOKEN"):
        """
        Initialize with server base URL and a single project's key (name).

        Args:
            base_url (str): SonarQube server base URL, e.g. "http://sonarqube1.rnd.aspentech.com:9000".
            project_key (str): Project key/name as seen in URLs.
            token_env (str): Environment variable name that stores the token.
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self._q = urllib.parse.quote
        token = os.getenv(token_env, "")
        self.auth = (token, "") if token else None

    # -----------------------------
    # Minimal set for the 6 core KPIs
    # -----------------------------
    def measures_url(
        self,
        metrics: Optional[List[str]] = None,
    ) -> str:
        """
        Build URL to fetch measures (coverage, duplication, code smells, etc.).

        Args:
            metrics (List[str], optional): Metric keys to query. If None, defaults to
                the minimal set for KPI judgment.

        Returns:
            str: Fully qualified URL for /api/measures/component.
        """
        if metrics is None:
            metrics = [
                # Coverage / Duplication (overall + new code)
                "coverage", "new_coverage",
                "duplicated_lines_density", "new_duplicated_lines_density",
                # Quality/defects/security snapshot
                "code_smells", "new_code_smells",
                "bugs", "vulnerabilities",
                # Technical debt & security grade (overall)
                "sqale_index", "security_rating",
            ]
        metric_keys = ",".join(metrics)
        return (
            f"{self.base_url}/api/measures/component"
            f"?component={self._q(self.project_key)}"
            f"&metricKeys={self._q(metric_keys)}"
        )

    def quality_gate_status_url(self) -> str:
        """
        Build URL to fetch quality gate status and failed conditions.

        Returns:
            str: URL for /api/qualitygates/project_status.
        """
        return (
            f"{self.base_url}/api/qualitygates/project_status"
            f"?projectKey={self._q(self.project_key)}"
        )

    def severe_issues_count_url(
        self,
        severities: str = "BLOCKER,CRITICAL",
        resolved: bool = False,
        created_after_iso: Optional[str] = None,
        page_size: int = 1,
    ) -> str:
        """
        Build URL to fetch (and count) severe issues (e.g., BLOCKER/CRITICAL).

        Args:
            severities (str): Comma-separated severities (e.g., "BLOCKER,CRITICAL").
            resolved (bool): Only unresolved by default (False => resolved=false).
            created_after_iso (str, optional): Filter by creation date (ISO8601).
            page_size (int): Page size (use 1 when you only need total count).

        Returns:
            str: URL for /api/issues/search with filters.
        """
        params = [
            f"componentKeys={self._q(self.project_key)}",
            f"severities={self._q(severities)}",
            f"resolved={'true' if resolved else 'false'}",
            f"ps={page_size}",
        ]
        if created_after_iso:
            params.append(f"createdAfter={self._q(created_after_iso)}")
        return f"{self.base_url}/api/issues/search?" + "&".join(params)

    def issues_facets_projects_url(self) -> str:
        """
        Build URL to enumerate visible projects via issues facets (fallback when projects/search is restricted).

        Returns:
            str: URL for /api/issues/search?facets=projects.
        """
        return f"{self.base_url}/api/issues/search?facets=projects&ps=1"

    # -----------------------------
    # One-stop bundles for your 6 KPI workflow
    # -----------------------------
    def minimal_kpi_urls(self) -> Dict[str, str]:
        """
        Return the minimal set of endpoints needed to judge the 6 KPIs for this project.

        Returns:
            Dict[str, str]: Dict with 'measures', 'quality_gate', and 'severe_issues' URLs.
        """
        return {
            "measures": self.measures_url(),
            "quality_gate": self.quality_gate_status_url(),
            "severe_issues": self.severe_issues_count_url(),
        }
    
    def fetch_json(self, url: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Fetch a SonarQube API endpoint and return parsed JSON.

        Args:
            url (str): Fully qualified SonarQube API URL.
            timeout (int): Timeout in seconds.

        Returns:
            Dict[str, Any]: Parsed JSON response.
        """
        r = requests.get(url, auth=self.auth, timeout=timeout)
        r.raise_for_status()
        return r.json()

    # Helper methods that directly fetch data
    # -----------------------------
    def get_measures(self, metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        return self.fetch_json(self.measures_url(metrics))

    def get_quality_gate(self) -> Dict[str, Any]:
        return self.fetch_json(self.quality_gate_status_url())

    def get_severe_issues(self) -> Dict[str, Any]:
        return self.fetch_json(self.severe_issues_count_url())


if __name__ == "__main__":
    base_url = "http://sonarqube1.rnd.aspentech.com:9000"
    project_key = "HysysEngine.Engine"

    builder = SonarKpiUrlBuilder(base_url, project_key)

    print("=== Minimal KPI URLs ===")
    urls = builder.minimal_kpi_urls()
    for k, v in urls.items():
        print(f"{k}: {v}")

    print("\n=== Facets Projects URL (for visible projects) ===")
    print(builder.issues_facets_projects_url())

    try:
        # 1) Measures
        print("=== Measures URL ===")
        print(builder.measures_url())
        measures = builder.fetch_json(builder.measures_url())
        print("Measures keys:", [m["metric"] for m in measures.get("component", {}).get("measures", [])])

        # 2) Quality Gate
        print("\n=== Quality Gate URL ===")
        print(builder.quality_gate_status_url())
        qgate = builder.fetch_json(builder.quality_gate_status_url())
        print("Quality Gate status:", qgate.get("projectStatus", {}).get("status"))

        # 3) Severe Issues
        print("\n=== Severe Issues URL ===")
        print(builder.severe_issues_count_url())
        severe = builder.fetch_json(builder.severe_issues_count_url())
        print("Severe issues total:", severe.get("total", 0))

    except Exception as e:
        print("Error during fetch:", str(e))
