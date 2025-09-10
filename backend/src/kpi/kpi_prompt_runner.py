import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from typing import Dict, Any, List, Optional

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter
from backend.src.llm.llm_handler import LLMCoderHandler


class KPIPromptRunner:
    """
    Run LLM-backed KPI analysis for each project directory under a given root.

    For every project folder (folder name is the project key), this runner:
      1) reads three SonarQube JSON files (measures.json, severe_issues.json|issues.json, quality_gate.json)
         using FileReader,
      2) loads external system/user prompts (TXT files) via FileReader,
      3) invokes the LLM three times (measures / issues / quality gate),
      4) writes human-readable text outputs back to each project folder as .txt files via FileWriter.
    """

    # Input filenames (change if your naming differs)
    MEASURES_FILE = "measures.json"
    ISSUES_FILE_PRIMARY = "severe_issues.json"
    QUALITY_GATE_FILE = "quality_gate.json"

    # Output filenames (text)
    OUT_MEASURES = "measures_analysis.txt"
    OUT_ISSUES = "issues_analysis.txt"
    OUT_QG = "quality_gate_analysis.txt"

    # Required prompt keys
    REQUIRED_PROMPT_KEYS = [
        "system_measures_kpi_audit",
        "user_measures_kpi_audit",
        "system_issues_kpi_audit",
        "user_issues_kpi_audit",
        "system_quality_gate_audit",
        "user_quality_gate_audit",
    ]

    def __init__(
        self,
        root_dir: str,
        prompt_paths: Dict[str, str],
        llm: Optional[LLMCoderHandler] = None,
        max_tokens: int = 1024,
        compact_json_in_prompt: bool = True,
    ) -> None:
        """
        Initialize the KPI prompt runner.

        Args:
            root_dir (str): Root directory containing per-project subfolders.
            prompt_paths (Dict[str, str]): Mapping from prompt key to TXT file path.
                Must include all keys listed in REQUIRED_PROMPT_KEYS.
            llm (LLMCoderHandler | None): Optional LLM handler instance. If None, a default
                LLMCoderHandler will be created.
            max_tokens (int): Maximum tokens per response. Typical range: 512–1024 for text output.
            compact_json_in_prompt (bool): If True, dump JSON with compact separators to reduce tokens.

        Returns:
            None
        """
        self.root_dir = root_dir
        self.llm = LLMCoderHandler()
        self.max_tokens = max_tokens
        self.compact_json_in_prompt = compact_json_in_prompt

        self.prompts: Dict[str, str] = {}
        self._load_prompts(prompt_paths)

    # --------------------------- public API ---------------------------
    def run_one(self, project_name: str) -> List[str]:
        """
        Process exactly one project by name (folder name under root_dir).

        This method does NOT call `run()`. It performs the full flow on a single
        project:
        1) resolve input file paths (with fallback for issues),
        2) read measures/issues/quality_gate JSON files,
        3) invoke the LLM three times (measures / issues / quality gate),
        4) write three .txt outputs to the same project folder.

        Args:
            project_name (str): The project folder name to process.

        Returns:
            List[str]: Paths of the three written analysis files for this project,
            or an empty list if the project or required files were not found.

        Raises:
            NotADirectoryError: If `root_dir` is not a valid directory.
        """
        if not os.path.isdir(self.root_dir):
            raise NotADirectoryError(f"Root not found: {self.root_dir}")

        proj_dir = os.path.join(self.root_dir, project_name)
        if not os.path.isdir(proj_dir):
            return []

        # Resolve input paths
        m_path = os.path.join(proj_dir, self.MEASURES_FILE)
        qg_path = os.path.join(proj_dir, self.QUALITY_GATE_FILE)

        # Prefer severe_issues.json; fallback to issues.json if present
        i_primary = os.path.join(proj_dir, getattr(self, "ISSUES_FILE_PRIMARY", "severe_issues.json"))
        i_fallback = os.path.join(proj_dir, "issues.json")
        i_path = i_primary if os.path.exists(i_primary) else i_fallback

        # Require all three inputs
        if not (os.path.exists(m_path) and os.path.exists(i_path) and os.path.exists(qg_path)):
            return []

        # Read JSONs
        measures = FileReader.read_json(m_path)
        issues = FileReader.read_json(i_path)
        qgate = FileReader.read_json(qg_path)

        # LLM calls (plain-text outputs)
        m_text = self._call_llm(
            sys_key="system_measures_kpi_audit",
            usr_key="user_measures_kpi_audit",
            project=project_name,
            json_obj=measures,
        )
        i_text = self._call_llm(
            sys_key="system_issues_kpi_audit",
            usr_key="user_issues_kpi_audit",
            project=project_name,
            json_obj=issues,
        )
        q_text = self._call_llm(
            sys_key="system_quality_gate_audit",
            usr_key="user_quality_gate_audit",
            project=project_name,
            json_obj=qgate,
        )

        # Write outputs
        out_measures = os.path.join(proj_dir, self.OUT_MEASURES)
        out_issues = os.path.join(proj_dir, self.OUT_ISSUES)
        out_qg = os.path.join(proj_dir, self.OUT_QG)

        FileWriter.write_text(m_text, out_measures)
        FileWriter.write_text(i_text, out_issues)
        FileWriter.write_text(q_text, out_qg)

        return [out_measures, out_issues, out_qg]

    def run(self) -> List[str]:
        """
        Traverse all project subfolders, call the LLM three times per project,
        and write three .txt analysis files next to the inputs.

        Args:
            None

        Returns:
            List[str]: Absolute or relative file paths of all written text outputs.

        Raises:
            NotADirectoryError: If the provided root_dir does not exist or is not a directory.
        """
        if not os.path.isdir(self.root_dir):
            raise NotADirectoryError(f"Root not found: {self.root_dir}")

        written: List[str] = []
        for name in sorted(os.listdir(self.root_dir)):
            proj_dir = os.path.join(self.root_dir, name)
            if not os.path.isdir(proj_dir):
                continue

            m_path = os.path.join(proj_dir, self.MEASURES_FILE)
            i_path = os.path.join(proj_dir, self.ISSUES_FILE_PRIMARY)
            qg_path = os.path.join(proj_dir, self.QUALITY_GATE_FILE)

            # Only process when all three files exist
            if not (os.path.exists(m_path) and os.path.exists(i_path) and os.path.exists(qg_path)):
                continue

            # Read JSONs
            measures = FileReader.read_json(m_path)
            issues = FileReader.read_json(i_path)
            qgate = FileReader.read_json(qg_path)

            # Invoke LLM (plain text outputs)
            m_text = self._call_llm(
                sys_key="system_measures_kpi_audit",
                usr_key="user_measures_kpi_audit",
                project=name,
                json_obj=measures,
            )
            i_text = self._call_llm(
                sys_key="system_issues_kpi_audit",
                usr_key="user_issues_kpi_audit",
                project=name,
                json_obj=issues,
            )
            q_text = self._call_llm(
                sys_key="system_quality_gate_audit",
                usr_key="user_quality_gate_audit",
                project=name,
                json_obj=qgate,
            )

            # Write .txt outputs via FileWriter
            FileWriter.write_text(m_text, os.path.join(proj_dir, self.OUT_MEASURES))
            FileWriter.write_text(i_text, os.path.join(proj_dir, self.OUT_ISSUES))
            FileWriter.write_text(q_text, os.path.join(proj_dir, self.OUT_QG))

            written.extend([
                os.path.join(proj_dir, self.OUT_MEASURES),
                os.path.join(proj_dir, self.OUT_ISSUES),
                os.path.join(proj_dir, self.OUT_QG),
            ])

        return written

    # --------------------------- internals ---------------------------
    def _load_prompts(self, prompt_paths: Dict[str, str]) -> None:
        """
        Load all required prompt files (TXT) into memory.

        Args:
            prompt_paths (Dict[str, str]): Mapping from prompt key to TXT file path.

        Returns:
            None

        Raises:
            KeyError: If any required prompt key is missing from the mapping.
        """
        missing = [k for k in self.REQUIRED_PROMPT_KEYS if k not in prompt_paths]
        if missing:
            raise KeyError(f"Missing prompt paths for keys: {missing}")

        for k, path in prompt_paths.items():
            self.prompts[k] = FileReader.read_text(path)

    def _call_llm(self, sys_key: str, usr_key: str, project: str, json_obj: Any) -> str:
        """
        Build the final user prompt by injecting {project} and {json}, then call the LLM.

        Args:
            sys_key (str): Prompt key for the system prompt.
            usr_key (str): Prompt key for the user prompt template.
            project (str): Project key/name injected into the user prompt.
            json_obj (Any): JSON object to embed into the user prompt (measures/issues/quality gate).

        Returns:
            str: Plain-text analysis generated by the LLM (code fences stripped if present).
        """
        system_prompt = self.prompts[sys_key]

        if self.compact_json_in_prompt:
            json_str = json.dumps(json_obj, ensure_ascii=False, separators=(",", ":"))
        else:
            json_str = json.dumps(json_obj, ensure_ascii=False, indent=2)

        user_template = self.prompts[usr_key]
        user_prompt = user_template.format(project=project, json=json_str)

        text = self.llm.handle_chat(system_prompt, user_prompt, max_tokens=self.max_tokens)
        return self._strip_code_fence(text)

    @staticmethod
    def _strip_code_fence(s: str) -> str:
        """
        Remove leading/trailing Markdown code fences (```...```) if present.

        Args:
            s (str): Raw model output that may contain Markdown code fences.

        Returns:
            str: Cleaned plain text with surrounding fences removed (if any).
        """ 
        t = s.strip()
        if t.startswith("```"):
            parts = t.split("```")
            if len(parts) >= 3:
                return parts[1].strip()
        return t


if __name__ == "__main__":
    PROMPTS_DIR = "backend/src/prompts"
    prompt_paths = {
        "system_measures_kpi_audit": os.path.join(PROMPTS_DIR, "system_measures_kpi_audit.txt"),
        "user_measures_kpi_audit": os.path.join(PROMPTS_DIR, "user_measures_kpi_audit.txt"),
        "system_issues_kpi_audit": os.path.join(PROMPTS_DIR, "system_issues_kpi_audit.txt"),
        "user_issues_kpi_audit": os.path.join(PROMPTS_DIR, "user_issues_kpi_audit.txt"),
        "system_quality_gate_audit": os.path.join(PROMPTS_DIR, "system_quality_gate_audit.txt"),
        "user_quality_gate_audit": os.path.join(PROMPTS_DIR, "user_quality_gate_audit.txt"),
    }

    ROOT = "backend/src/outputs"

    runner = KPIPromptRunner(
        root_dir=os.path.abspath(ROOT),
        prompt_paths=prompt_paths,
        llm=None,                 # defaults to LLMCoderHandler()
        max_tokens=1024,
        compact_json_in_prompt=True,
    )

    # Pick the first project (by name) and run exactly one
    projects = sorted(
        d for d in os.listdir(ROOT)
        if os.path.isdir(os.path.join(ROOT, d))
    )

    if not projects:
        print(f"No project folders found under: {ROOT}")
    else:
        first = projects[0]
        written = runner.run_one(first)
        print(f"Processed project: {first}")
        for p in written:
            print("Written:", p)


#    for p in runner.run():
#        print("Written:", p)
