import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import requests
from typing import Dict, Any, List

class PowerBIAutomation:
    """
    Manage Power BI authentication and dataset creation (step 2 of the pipeline).

    This class focuses ONLY on:
        - Obtaining an access token (client credentials)
        - Ensuring a Push Dataset exists with 3 tables:
          measures, quality_gate, severe_issues

    Notes:
        - Visuals/pages and data push are handled in later steps.
        - Table schemas MUST match your PBIX template and CSV outputs.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 workspace_id: str, dataset_name: str = "SonarQubeMetricsAuto") -> None:
        """
        Initialize the automation client with credentials and workspace info.

        Args:
            tenant_id: Azure AD tenant ID.
            client_id: Azure AD application (client) ID.
            client_secret: Azure AD application secret.
            workspace_id: Power BI workspace (group) ID.
            dataset_name: Name of the dataset to create or reuse.
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.workspace_id = workspace_id
        self.dataset_name = dataset_name
        self.scope = "https://analysis.windows.net/powerbi/api/.default"

    # =========================
    # Auth
    # =========================
    def get_access_token(self) -> str:
        """
        Acquire an Azure AD access token (client credentials) for Power BI API.

        Returns:
            The OAuth2 access token string to be used as Bearer token.
        """
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": self.scope,
        }
        r = requests.post(url, data=data, timeout=30)
        r.raise_for_status()
        return r.json()["access_token"]

    # =========================
    # Dataset
    # =========================
    def ensure_dataset(self, token: str) -> str:
        """
        Ensure the target dataset exists in the workspace; create it if missing.

        Args:
            token: Bearer access token.

        Returns:
            The dataset ID (existing or newly created).
        """
        base = f"https://api.powerbi.com/v1.0/myorg/groups/{self.workspace_id}"
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1) Check existing datasets by name
        r = requests.get(f"{base}/datasets", headers=h, timeout=30)
        r.raise_for_status()
        for ds in r.json().get("value", []):
            if ds.get("name") == self.dataset_name:
                return ds["id"]

        # 2) Create a new Push dataset with 3 tables
        payload = {
            "name": self.dataset_name,
            "defaultMode": "Push",
            "tables": self._tables_schema(),
        }
        r = requests.post(f"{base}/datasets", headers=h, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["id"]

    # =========================
    # Schema helpers (private)
    # =========================
    def _tables_schema(self) -> List[Dict[str, Any]]:
        """
        Build the schema for the 3 Power BI tables.

        Returns:
            A list of table definitions (name + columns with dataType).
        """
        def col(name: str, dt: str) -> Dict[str, str]:
            return {"name": name, "dataType": dt}

        return [
            {
                "name": "measures",
                "columns": [
                    col("project_key", "string"),
                    col("metric", "string"),
                    col("value", "double"),
                    col("date", "string"),
                    col("period_index", "Int64"),
                ],
            },
            {
                "name": "quality_gate",
                "columns": [
                    col("project_key", "string"),
                    col("gate_status", "string"),
                    col("ignored_conditions", "bool"),
                    col("condition_status", "string"),
                    col("metric_key", "string"),
                    col("comparator", "string"),
                    col("period_index", "Int64"),
                    col("error_threshold", "double"),
                    col("actual_value", "double"),
                    col("period_mode", "string"),
                    col("period_date", "string"),
                ],
            },
            {
                "name": "severe_issues",
                "columns": [
                    col("issue_key", "string"),
                    col("rule", "string"),
                    col("severity", "string"),
                    col("component", "string"),
                    col("project", "string"),
                    col("line", "Int64"),
                    col("message", "string"),
                    col("effort_min", "Int64"),
                    col("creation_date", "string"),
                    col("update_date", "string"),
                    col("type", "string"),
                    col("scope", "string"),
                    col("startLine", "Int64"),
                    col("endLine", "Int64"),
                    col("startOffset", "Int64"),
                    col("endOffset", "Int64"),
                    col("component_name", "string"),
                    col("component_qualifier", "string"),
                    col("component_path", "string"),
                    col("component_enabled", "bool"),
                ],
            },
        ]


if __name__ == "__main__":
    # Minimal example for step 2 (create or get dataset)
    TENANT_ID = "<your-tenant-id>"
    CLIENT_ID = "<your-client-id>"
    CLIENT_SECRET = "<your-client-secret>"
    WORKSPACE_ID = "<your-workspace-id>"
    DATASET_NAME = "SonarQubeMetricsAuto"  # change if needed

    client = PowerBIAutomation(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        workspace_id=WORKSPACE_ID,
        dataset_name=DATASET_NAME,
    )

    token = client.get_access_token()
    dataset_id = client.ensure_dataset(token)
    print("Dataset ID:", dataset_id)
