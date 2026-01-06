import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
import pandas as pd
from typing import Union, List, Dict, Any

class FileReader:
    """
    Utility class for reading files, especially prompt templates.
    """

    @staticmethod
    def read_text(path: str) -> str:
        """
        Read a UTF-8 text file and return its content.

        Args:
            path: Path to the file.

        Returns:
            The file content as a string.
        """
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def read_csv(path: str, **kwargs) -> pd.DataFrame:
        """
        Read a CSV file into a pandas DataFrame.

        Args:
            path: Path to the CSV file.
            **kwargs: Passed through to pandas.read_csv (e.g., sep, dtype).

        Returns:
            pandas.DataFrame
        """
        # utf-8-sig handles BOM if present; user can override via kwargs
        kwargs.setdefault("encoding", "utf-8-sig")
        return pd.read_csv(path, **kwargs)

    @staticmethod
    def read_xlsx(path: str, sheet_name: Union[str, int] = 0, **kwargs) -> pd.DataFrame:
        """
        Read an Excel (.xlsx) sheet into a pandas DataFrame.

        Args:
            path: Path to the Excel file.
            sheet_name: Sheet name or index; defaults to the first/active sheet.
            **kwargs: Passed through to pandas.read_excel (e.g., dtype).

        Returns:
            pandas.DataFrame
        """
        return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", **kwargs)
    
    @staticmethod
    def read_json(path: str) -> Union[dict, list]:
        """
        Read a JSON file and return the parsed Python object (dict or list).

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed JSON content as a dict or list.
        """
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
        
    @staticmethod
    def read_jsonl(path: str) -> List[Dict[str, Any]]:
        """
        Read a JSONL (JSON Lines) file and return a list of parsed JSON objects.

        Each non-empty line is expected to be a valid JSON object.
        Lines that cannot be parsed will be skipped.

        Args:
            path: Path to the JSONL file.

        Returns:
            A list of parsed JSON objects (one per line).
        """
        objects: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    objects.append(obj)
                except Exception:
                    # Skip malformed lines silently; this is a debug helper.
                    continue
        return objects
