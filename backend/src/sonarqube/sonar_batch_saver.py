import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import pathlib
from typing import List, Dict, Any

from backend.src.sonarqube.url_builder import SonarKpiUrlBuilder
from backend.src.data_io.file_writer import FileWriter


class SonarBatchSaver:
    """
    Fetch measures / quality gate / severe issues for each project and
    save them as three separate JSON files under output_root/<project_key>/.
    """

    def __init__(self, base_url: str, project_keys: List[str], output_root: str = "outputs",
                 token: str | None = None, timeout: int = 30):
        """
        Args:
            base_url (str): SonarQube server base URL.
            project_keys (List[str]): List of project keys (names).
            output_root (str): Root directory to store per-project outputs.
            token (str | None): Optional token for private instances (Basic Auth).
            timeout (int): Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.project_keys = project_keys
        self.output_root = pathlib.Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.timeout = timeout

    def _project_dir(self, project_key: str) -> pathlib.Path:
        p = self.output_root / project_key
        p.mkdir(parents=True, exist_ok=True)
        return p

    def fetch_and_save_one(self, project_key: str) -> Dict[str, Any]:
        """
        Fetch three APIs for a single project and save to disk.

        Returns:
            Dict[str, Any]: Summary with file paths and basic info.
        """
        outdir = self._project_dir(project_key)

        # Reuse your existing builder with built-in fetch/getters
        builder = SonarKpiUrlBuilder(self.base_url, project_key)
        # If your builder supports auth/timeout, set them here:
        # e.g., builder.auth = (self.token, "") if self.token else None
        # and pass timeout when calling fetchers if needed.

        summary: Dict[str, Any] = {"project": project_key, "ok": True, "files": {}}

        try:
            measures = builder.get_measures()                       # /api/measures/component
            qgate = builder.get_quality_gate()                      # /api/qualitygates/project_status
            severe = builder.get_severe_issues()                    # /api/issues/search (total)

            FileWriter.write_json_obj(measures, str(outdir / "measures.json"))
            FileWriter.write_json_obj(qgate,    str(outdir / "quality_gate.json"))
            FileWriter.write_json_obj(severe,   str(outdir / "severe_issues.json"))

            summary["files"] = {
                "measures": str(outdir / "measures.json"),
                "quality_gate": str(outdir / "quality_gate.json"),
                "severe_issues": str(outdir / "severe_issues.json"),
            }
            summary["quality_gate_status"] = qgate.get("projectStatus", {}).get("status")
            summary["total_severe"] = severe.get("total", 0)

        except Exception as e:
            summary["ok"] = False
            summary["error"] = str(e)
            FileWriter.write_json_obj({"error": str(e)}, str(outdir / "error.json"))

        return summary

    def run(self) -> List[Dict[str, Any]]:
        """
        Loop over all projects, fetch and save three JSONs per project.
        """
        results: List[Dict[str, Any]] = []
        for key in self.project_keys:
            results.append(self.fetch_and_save_one(key))
        # Optional: write a batch summary
        FileWriter.write_json_obj({"results": results}, str(self.output_root / "batch_summary.json"))
        return results


if __name__ == "__main__":
    base_url = "http://sonarqube1.rnd.aspentech.com:9000"
    projects = ["HysysEngine.Engine"]

    project_keys = [
        "HysysEngine.Engine",
        "ABE.MainLicensing",
        "Hysys.EnergyAnalyzer",
        "HysysEngine.IFace",
        "HysysEngine.MainCSSExtern",
        "HysysEngine.Components",
        "HysysUI.Hysys",
        "ABE.Core.CSHARP",
        "ABE.Feed",
        "ABE.AspenONE",
        "HysysUI.ConceptualDesignBuilder",
        "ABE.Core.CPP",
    ]

    runner = SonarBatchSaver(base_url=base_url, project_keys=project_keys, output_root="backend/src/outputs")
    summaries = runner.run()
    from pprint import pprint
    pprint(summaries)
