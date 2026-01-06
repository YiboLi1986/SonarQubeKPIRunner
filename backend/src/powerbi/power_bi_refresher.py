import os
import sys
import time
import requests
from typing import Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))


class PowerBIRefresher:
    """
    Trigger a dataset refresh in Power BI Service via REST API.

    This class is designed to be used *after* your CSV has been synced to OneDrive
    (or any other Power BI-connected source). It uses Azure AD / MSAL client credentials
    to authenticate as a service principal or registered app.

    Typical workflow:
      1) Register an Azure AD app with Power BI API permissions (Dataset.ReadWrite.All).
      2) Store the tenant, client ID, and secret securely (e.g., environment variables).
      3) Initialize this class with workspace_id and dataset_id.
      4) Call trigger_refresh() after publishing a CSV to OneDrive.

    Notes:
      - This class performs a simple POST to
            https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/refreshes
      - Optionally, you can poll until the refresh is completed.
      - Does NOT upload or modify any data files; it only instructs Power BI Service
        to re-import from connected sources (e.g., OneDrive or SharePoint).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        workspace_id: str,
        dataset_id: str,
        *,
        notify_option: str = "MailOnFailure",
        api_base: str = "https://api.powerbi.com/v1.0/myorg"
    ) -> None:
        """
        Args:
            tenant_id: Azure Active Directory tenant ID.
            client_id: Application (client) ID of the registered Azure app.
            client_secret: Client secret (store securely, e.g., env var or key vault).
            workspace_id: Target Power BI workspace (also known as groupId).
            dataset_id: Power BI dataset to trigger refresh on.
            notify_option: Power BI notification preference. Options:
                "MailOnCompletion", "MailOnFailure", "NoNotification".
            api_base: Base URL for Power BI REST API.
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.workspace_id = workspace_id
        self.dataset_id = dataset_id
        self.notify_option = notify_option
        self.api_base = api_base.rstrip("/")

        # You may later extend with MSAL caching or token re-use
        self._access_token: Optional[str] = None

    # --------------------------- helper methods ---------------------------

    def _get_access_token(self) -> str:
        """
        Obtain an access token from Azure AD using client credentials flow.

        Replace this simple requests call with MSAL library if you need caching or refresh.

        Returns:
            str: OAuth 2.0 bearer token to call Power BI REST API.

        Raises:
            RuntimeError: if unable to get token.
        """
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://analysis.windows.net/powerbi/api/.default",
        }
        resp = requests.post(url, data=data)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to obtain token: {resp.status_code} {resp.text}")

        self._access_token = resp.json().get("access_token")
        return self._access_token

    # ------------------------------ public API ----------------------------

    def trigger_refresh(self, wait_for_completion: bool = False, poll_interval: int = 10) -> dict:
        """
        Trigger a refresh for the given dataset in Power BI.

        Args:
            wait_for_completion: If True, poll the refresh status until completed.
            poll_interval: Seconds between polling attempts.

        Returns:
            dict: Response from Power BI API for the refresh trigger or final status.

        Raises:
            RuntimeError: if API request fails.
        """
        token = self._access_token or self._get_access_token()
        url = f"{self.api_base}/groups/{self.workspace_id}/datasets/{self.dataset_id}/refreshes"

        headers = {"Authorization": f"Bearer {token}"}
        payload = {"notifyOption": self.notify_option}

        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Failed to trigger refresh: {resp.status_code} {resp.text}")

        result = resp.json() if resp.text else {"status": "Triggered"}
        if not wait_for_completion:
            return result

        # --- Optional polling section (placeholder logic) ---
        while True:
            status_url = f"{url}?$top=1"
            status_resp = requests.get(status_url, headers=headers)
            if status_resp.status_code != 200:
                raise RuntimeError(f"Failed to check refresh status: {status_resp.status_code} {status_resp.text}")

            value = status_resp.json().get("value", [])
            if value:
                last_status = value[0].get("status")
                if last_status in ("Completed", "Failed", "Cancelled"):
                    return value[0]
            time.sleep(poll_interval)

    # ------------------------------- utilities ----------------------------

    @classmethod
    def from_env(cls) -> "PowerBIRefresher":
        """
        Convenience constructor that reads credentials and IDs from environment variables.

        Expected variables:
            PBI_TENANT_ID, PBI_CLIENT_ID, PBI_CLIENT_SECRET, PBI_WORKSPACE_ID, PBI_DATASET_ID

        Returns:
            PowerBIRefresher: Initialized instance.
        """
        return cls(
            tenant_id=os.getenv("PBI_TENANT_ID", ""),
            client_id=os.getenv("PBI_CLIENT_ID", ""),
            client_secret=os.getenv("PBI_CLIENT_SECRET", ""),
            workspace_id=os.getenv("PBI_WORKSPACE_ID", ""),
            dataset_id=os.getenv("PBI_DATASET_ID", ""),
        )


if __name__ == "__main__":
    refresher = PowerBIRefresher.from_env()
    try:
        resp = refresher.trigger_refresh(wait_for_completion=False)
        print("Triggered Power BI dataset refresh:", resp)
    except Exception as e:
        print("Error:", e)
