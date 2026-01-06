import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from typing import Iterable, Dict, Any, List, Optional, Union

import pandas as pd

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class JsonlToCsvExporter:
    """
    A small utility class to convert JSONL issues into a flat CSV for Power BI.

    Workflow:
      1) Read JSONL text using FileReader.read_text(path)
      2) Parse each line as JSON (dict)
      3) Normalize/flatten nested objects (e.g., copilot_advice.*)
      4) Coerce lists/dicts to JSON strings for CSV compatibility
      5) Save to CSV using FileWriter.write_csv(df, path)

    Notes:
      - Designed for SonarQube issue JSONL lines similar to the provided example.
      - By default, nested fields are flattened with dot-separated keys (e.g., "copilot_advice.model").
      - Lists/dicts that remain after normalization are serialized to JSON strings to preserve information.
      - Columns are alphabetically sorted to keep schema stable across runs.
    """

    def __init__(
        self,
        jsonl_path: str,
        csv_out_path: str,
        *,
        flatten: bool = True,
        max_level: Optional[int] = None,
        prefer_columns: Optional[List[str]] = None,
        extra_text_fields: Optional[List[str]] = None
    ) -> None:
        """
        Initialize the exporter.

        Args:
            jsonl_path: Path to the input JSONL file.
            csv_out_path: Path to the output CSV file.
            flatten: Whether to flatten nested objects via pandas.json_normalize.
            max_level: Max depth for flattening; None = unlimited (pandas default).
            prefer_columns: Optional explicit column ordering placed first if present.
            extra_text_fields: Optional list of fields to force-serialize as text even if they are structured
                               (e.g., ["copilot_advice.raw", "copilot_advice.code_update"]).
        """
        self.jsonl_path = jsonl_path
        self.csv_out_path = csv_out_path
        self.flatten = flatten
        self.max_level = max_level
        self.prefer_columns = prefer_columns or [
            "issue_key",
            "project",
            "component",
            "file_path",
            "type",
            "severity",
            "rule",
            "rule_name",
            "message",
            "effort",
            "start_line",
            "end_line",
            "creation_date",
            "update_date",
            "priority_score",
        ]
        self.extra_text_fields = set(extra_text_fields or [
            "copilot_advice.raw",
            "copilot_advice.explanation",
            "copilot_advice.code_update"
        ])

    # ----------------------------- core pipeline -----------------------------

    def _read_records(self) -> List[Dict[str, Any]]:
        """
        Read the JSONL file and return a list of dict records.

        We call FileReader.read_text to keep parity with your utilities, then split lines.
        Lines that fail JSON parsing are skipped with a minimal fallback.
        """
        text = FileReader.read_text(self.jsonl_path)
        records: List[Dict[str, Any]] = []
        for i, line in enumerate(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Best-effort fallback to keep the pipeline robust
                obj = {"_parse_error": True, "_raw_line": line, "_line_no": i + 1}
            records.append(obj)
        return records

    def _normalize(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Normalize/flatten nested structures.

        If flatten=True, we use pandas.json_normalize to expand nested dicts with dot-separated keys.
        Otherwise we build a DataFrame directly and let downstream coercion handle complex types.
        """
        if not records:
            return pd.DataFrame()

        if self.flatten:
            df = pd.json_normalize(
                records,
                sep=".",
                max_level=self.max_level  # None means unlimited in pandas
            )
        else:
            df = pd.DataFrame(records)

        # Ensure extra text fields exist even if missing in some rows
        for col in self.extra_text_fields:
            if col not in df.columns:
                df[col] = pd.NA

        return df

    @staticmethod
    def _coerce_scalar(x: Any) -> Any:
        """
        Convert non-scalar objects (lists/dicts) to compact JSON strings for CSV.
        Leave scalars (None, str, int, float, bool) as-is.
        """
        if isinstance(x, (dict, list)):
            try:
                return json.dumps(x, ensure_ascii=False)
            except Exception:
                return str(x)
        return x

    def _finalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply final shaping:
          - Coerce complex objects to text
          - Stable column ordering (prefer_columns first, then the rest sorted)
          - Fill NaN with empty strings for consistent CSV output
        """
        if df.empty:
            return df

        # Coerce complex objects column-wise
        for c in df.columns:
            df[c] = df[c].map(self._coerce_scalar)

        # Build stable column order
        all_cols = list(df.columns)
        preferred = [c for c in self.prefer_columns if c in all_cols]
        remaining = sorted([c for c in all_cols if c not in preferred])
        ordered = preferred + remaining
        df = df.reindex(columns=ordered)

        # Fill NA to avoid "nan" text in CSVs
        df = df.fillna("")

        return df

    def convert(self) -> pd.DataFrame:
        """
        Execute the conversion pipeline and return the resulting DataFrame.
        """
        records = self._read_records()
        df = self._normalize(records)
        df = self._finalize_df(df)
        return df

    def save(self) -> str:
        """
        Convert and save the CSV via FileWriter.write_csv.

        Returns:
            The output CSV path for convenience.
        """
        df = self.convert()
        # UTF-8 with BOM is friendly for Excel/Power BI auto-detection
        FileWriter.write_csv(df, self.csv_out_path, encoding="utf-8-sig", index=False)
        return self.csv_out_path

    def run(self) -> str:
        """
        Convenience alias for save(); kept for semantic clarity.
        """
        return self.save()


if __name__ == "__main__":
    JSONL = "backend/src/outputs/evaluations/HysysEngine.Engine/2025-10-23_144830/issues_with_advice.jsonl"
    CSV   = "backend/src/outputs/evaluations/HysysEngine.Engine/2025-10-23_144830/issues_with_advice.csv"

    exporter = JsonlToCsvExporter(
        jsonl_path=JSONL,
        csv_out_path=CSV,
        flatten=True,  
        max_level=None, 
        prefer_columns=[
            "issue_key","project","component","file_path",
            "type","severity","rule","rule_name","message","effort",
            "start_line","end_line","creation_date","update_date","priority_score",
            "copilot_advice.model","copilot_advice.explanation","copilot_advice.code_update"
        ],
        extra_text_fields=["copilot_advice.raw","copilot_advice.code_update"]
    )
    out_csv = exporter.run()
    print(f"CSV saved to: {out_csv}")
