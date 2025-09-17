import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from typing import Any, Dict, List, Optional
import os
import pandas as pd

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class PBIJsonPreprocessor:
    """
    Convert three input JSON files into three flat CSV tables for Power BI.

    Mapping (1 → 1):
        measures.json      → df_measures      (long format)
        quality_gate.json  → df_quality       (one row per condition)
        severe_issues.json → df_issues_all    (one row per issue with component fields)

    Notes:
        - This class ONLY handles JSON → pandas DataFrame → CSV export.
        - JSON loading is done via FileReader.read_json from your codebase.
        - CSV writing is done via FileWriter.write_csv from your codebase.
    """

    def __init__(self, project_key: str) -> None:
        """
        Initialize the preprocessor with a project key.

        Args:
            project_key: Logical project identifier to stamp on output rows.
        """
        self.project_key = project_key
        self.df_measures: pd.DataFrame = pd.DataFrame()
        self.df_quality: pd.DataFrame = pd.DataFrame()
        self.df_issues_all: pd.DataFrame = pd.DataFrame()

    def load_all(self, measures_path: str, quality_gate_path: str, issues_path: str) -> None:
        """
        Load and parse three JSON files into internal DataFrames.

        Args:
            measures_path: Path to measures.json.
            quality_gate_path: Path to quality_gate.json.
            issues_path: Path to severe_issues.json.
        """
        js_measures = FileReader.read_json(measures_path)
        js_qg = FileReader.read_json(quality_gate_path)
        js_issues = FileReader.read_json(issues_path)

        self._parse_measures(js_measures)
        self._parse_quality_gate(js_qg)
        self._parse_issues(js_issues)

    def write_csv(self, out_dir: str) -> Dict[str, str]:
        """
        Write the three DataFrames to CSV files in a target directory.

        Args:
            out_dir: Output directory where CSV files will be written.

        Returns:
            A dict mapping logical table name to the created CSV path.
        """
        os.makedirs(out_dir, exist_ok=True)
        outputs: Dict[str, str] = {}

        def _emit(df: pd.DataFrame, name: str) -> None:
            if df is not None and not df.empty:
                path = os.path.join(out_dir, f"{name}.csv")
                FileWriter.write_csv(df, path)
                outputs[name] = path

        _emit(self.df_measures, "measures")
        _emit(self.df_quality, "quality_gate")
        _emit(self.df_issues_all, "severe_issues")
        return outputs

    def write_csv_to(self, measures_out: str, quality_out: str, issues_out: str) -> Dict[str, str]:
        """
        Write the three DataFrames to explicitly specified CSV paths.

        Args:
            measures_out: Output path for measures.csv.
            quality_out: Output path for quality_gate.csv.
            issues_out: Output path for severe_issues.csv.

        Returns:
            A dict mapping logical table name to the created CSV path.
        """
        outputs: Dict[str, str] = {}
        if self.df_measures is not None and not self.df_measures.empty:
            FileWriter.write_csv(self.df_measures, measures_out)
            outputs["measures"] = measures_out
        if self.df_quality is not None and not self.df_quality.empty:
            FileWriter.write_csv(self.df_quality, quality_out)
            outputs["quality_gate"] = quality_out
        if self.df_issues_all is not None and not self.df_issues_all.empty:
            FileWriter.write_csv(self.df_issues_all, issues_out)
            outputs["severe_issues"] = issues_out
        return outputs

    # =========================
    # Parsers
    # =========================
    def _parse_quality_gate(self, js: Dict[str, Any]) -> None:
        """
        Parse quality_gate.json into a single flat table (one row per condition).

        Output schema (df_quality):
            - project_key (str)
            - gate_status (str)
            - ignored_conditions (bool)
            - condition_status (str)
            - metric_key (str)
            - comparator (str)
            - period_index (int)
            - error_threshold (float)
            - actual_value (float)
            - period_mode (str)
            - period_date (str, ISO 8601 with timezone)
        """
        ps = js.get("projectStatus", {})
        gate_status = ps.get("status")
        ignored = bool(ps.get("ignoredConditions", False))

        # Build period index → (mode, date)
        periods = ps.get("periods") or ([] if not ps.get("period") else [ps.get("period")])
        idx2period: Dict[Optional[int], Dict[str, Optional[str]]] = {}
        for p in periods:
            idx = self._to_int(p.get("index"))
            idx2period[idx] = {
                "mode": p.get("mode"),
                "date": self._fix_iso_z(p.get("date")),
            }

        rows: List[Dict[str, Any]] = []
        for c in ps.get("conditions", []):
            pi = self._to_int(c.get("periodIndex"))
            per = idx2period.get(pi, {"mode": None, "date": None})
            rows.append({
                "project_key": self.project_key,
                "gate_status": gate_status,
                "ignored_conditions": ignored,
                "condition_status": c.get("status"),
                "metric_key": c.get("metricKey"),
                "comparator": c.get("comparator"),
                "period_index": pi,
                "error_threshold": self._to_float(c.get("errorThreshold")),
                "actual_value": self._to_float(c.get("actualValue")),
                "period_mode": per.get("mode"),
                "period_date": per.get("date"),
            })
        self.df_quality = pd.DataFrame(rows)

    def _parse_issues(self, js: Dict[str, Any]) -> None:
        """
        Parse severe_issues.json into a flat table (one row per issue) joined with component fields.

        Output schema (df_issues_all):
            - issue_key, rule, severity, component, project, line, message,
              effort_min, creation_date, update_date, type, scope,
              startLine, endLine, startOffset, endOffset,
              component_name, component_qualifier, component_path, component_enabled
        """
        issues = js.get("issues", [])
        components = js.get("components", [])
        comp_map: Dict[str, Dict[str, Any]] = {c.get("key"): c for c in components if c.get("key")}

        def _safe_tr(tr: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
            if not tr:
                return {"startLine": None, "endLine": None, "startOffset": None, "endOffset": None}
            return {
                "startLine": self._to_int(tr.get("startLine")),
                "endLine": self._to_int(tr.get("endLine")),
                "startOffset": self._to_int(tr.get("startOffset")),
                "endOffset": self._to_int(tr.get("endOffset")),
            }

        rows: List[Dict[str, Any]] = []
        for it in issues:
            comp_key = it.get("component")
            c = comp_map.get(comp_key, {})
            rows.append({
                "issue_key": it.get("key"),
                "rule": it.get("rule"),
                "severity": it.get("severity"),
                "component": comp_key,
                "project": it.get("project"),
                "line": self._to_int(it.get("line")),
                "message": it.get("message"),
                "effort_min": self._parse_effort_to_min(it.get("effort") or it.get("debt")),
                "creation_date": self._fix_iso_z(it.get("creationDate")),
                "update_date": self._fix_iso_z(it.get("updateDate")),
                "type": it.get("type"),
                "scope": it.get("scope"),
                **_safe_tr(it.get("textRange")),
                # component join
                "component_name": c.get("name"),
                "component_qualifier": c.get("qualifier"),
                "component_path": c.get("path"),
                "component_enabled": bool(c.get("enabled")) if c.get("enabled") is not None else None,
            })
        self.df_issues_all = pd.DataFrame(rows)

    def _parse_measures(self, js: Dict[str, Any]) -> None:
        """
        Parse measures.json into a long table (one row per metric/time/value).

        Output schema (df_measures):
            - project_key (str)
            - metric (str)
            - value (float)
            - date (str, ISO 8601 with timezone)  # may be None if snapshot only
            - period_index (int)                  # optional period index
        """
        comp = js.get("component") or {}
        measures = js.get("measures") or comp.get("measures") or []

        rows: List[Dict[str, Any]] = []
        for m in measures:
            metric = m.get("metric") or m.get("key")
            if not metric:
                continue

            hist = m.get("history")
            if isinstance(hist, list) and hist:
                for h in hist:
                    rows.append({
                        "project_key": self.project_key,
                        "metric": metric,
                        "value": self._to_float(h.get("value")),
                        "date": self._fix_iso_z(h.get("date")),
                        "period_index": None,
                    })
                continue

            value = m.get("value")
            if value is not None:
                rows.append({
                    "project_key": self.project_key,
                    "metric": metric,
                    "value": self._to_float(value),
                    "date": None,
                    "period_index": self._to_int(m.get("period")) or self._to_int(m.get("periodIndex")),
                })

            if isinstance(m.get("periods"), list):
                for p in m["periods"]:
                    rows.append({
                        "project_key": self.project_key,
                        "metric": metric,
                        "value": self._to_float(p.get("value")),
                        "date": self._fix_iso_z(p.get("date")),
                        "period_index": self._to_int(p.get("index")),
                    })

        self.df_measures = pd.DataFrame(rows)

    # =========================
    # Helpers (kept inside class)
    # =========================
    @staticmethod
    def _to_int(v: Any) -> Optional[int]:
        """
        Safely convert a value to int.

        Args:
            v: Input value.

        Returns:
            Integer value or None if conversion fails.
        """
        try:
            if v is None or v == "":
                return None
            return int(v)
        except Exception:
            return None

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        """
        Safely convert a value to float (accepts comma decimal separators).

        Args:
            v: Input value.

        Returns:
            Float value or None if conversion fails.
        """
        try:
            if v is None or v == "":
                return None
            return float(str(v).replace(",", "."))
        except Exception:
            return None

    @staticmethod
    def _fix_iso_z(s: Optional[str]) -> Optional[str]:
        """
        Normalize timezone suffix like '+0000' to '+00:00' for ISO 8601 compliance.

        Args:
            s: Timestamp string.

        Returns:
            Normalized timestamp string or None if input is falsy.
        """
        if not s:
            return s
        if len(s) >= 5 and (s[-5] in ['+', '-']) and s[-3] != ':':
            return s[:-2] + ":" + s[-2:]
        return s

    @staticmethod
    def _parse_effort_to_min(val: Optional[str]) -> Optional[int]:
        """
        Convert effort string like '2h 30min' to total minutes.

        Args:
            val: Effort string.

        Returns:
            Total minutes as integer, or None if parsing fails.
        """
        if not val:
            return None
        s = str(val).strip().lower()
        total = 0

        def flush(num: str, unit: str) -> int:
            if not num:
                return 0
            n = int(num)
            if unit.startswith('d'):
                return n * 24 * 60
            if unit.startswith('h'):
                return n * 60
            return n  # assume minutes

        num, unit = "", ""
        for ch in s:
            if ch.isdigit():
                if unit:
                    total += flush(num, unit)
                    num, unit = ch, ""
                else:
                    num += ch
            elif ch.isalpha():
                unit += ch
            else:
                total += flush(num, unit)
                num, unit = "", ""
        total += flush(num, unit)
        return total or None


if __name__ == "__main__":
    # Minimal runnable example (replace paths with your real ones)
    pre = PBIJsonPreprocessor(project_key="ABE.AspenONE")
    pre.load_all(
        measures_path="backend/src/outputs/ABE.AspenONE/measures.json",
        quality_gate_path="backend/src/outputs/ABE.AspenONE/quality_gate.json",
        issues_path="backend/src/outputs/ABE.AspenONE/severe_issues.json",
    )
    paths = pre.write_csv("backend/src/outputs/ABE.AspenONE")
    print(paths)
