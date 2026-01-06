import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
import pandas as pd
from contextlib import contextmanager
from typing import Iterable, Dict, Any, Callable

class FileWriter:
    """
    Utility class for writing files, especially JSONL output.
    """
    @staticmethod
    def write_json(data: Any, path: str, ensure_ascii: bool = False, pretty: bool = True) -> None:
        """
        Write any JSON-serializable object (dict or list) to a file.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            if pretty:
                json.dump(data, f, ensure_ascii=ensure_ascii, indent=2)
            else:
                json.dump(data, f, ensure_ascii=ensure_ascii)

    @staticmethod
    def write_jsonl(records: Iterable[Dict[str, Any]], path: str, ensure_ascii: bool = False) -> None:
        """
        Write an iterable of JSON-serializable dicts to a JSONL file.

        Args:
            records: Iterable of dicts (each dict = one training example).
            path: Output file path.
            ensure_ascii: If True, non-ASCII characters are escaped.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for obj in records:
                f.write(json.dumps(obj, ensure_ascii=ensure_ascii) + "\n")

    @staticmethod
    def write_json_obj(obj: Dict[str, Any], path: str, ensure_ascii: bool = False, pretty: bool = True) -> None:
        """
        Write a single JSON object to a file.

        Args:
            obj: A single dict (JSON-serializable).
            path: Output file path.
            ensure_ascii: If True, non-ASCII characters are escaped.
            pretty: If True, indent=2 for readability.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            if pretty:
                json.dump(obj, f, ensure_ascii=ensure_ascii, indent=2)
            else:
                json.dump(obj, f, ensure_ascii=ensure_ascii)

    @staticmethod
    def write_text(content: str, path: str, encoding: str = "utf-8") -> None:
        """
        Write plain text content to a file.

        Args:
            content (str): Text content to write.
            path (str): Output file path.
            encoding (str): Output encoding. Defaults to 'utf-8'.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(content)

    @staticmethod
    def write_csv(df: "pd.DataFrame", path: str, **kwargs) -> None:
        """
        Write a pandas DataFrame to a CSV file.

        Args:
            df: DataFrame to write.
            path: Output file path.
            **kwargs: Additional keyword arguments forwarded to pandas.DataFrame.to_csv
                (e.g., sep, encoding, index).

        Notes:
            - Ensures the parent directory exists.
            - Defaults to UTF-8 with BOM and index=False; users can override via kwargs.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Sensible defaults; can be overridden by caller
        kwargs.setdefault("index", False)
        kwargs.setdefault("encoding", "utf-8-sig")
        df.to_csv(path, **kwargs)

    @staticmethod
    def append_jsonl(record: Dict[str, Any], path: str, ensure_ascii: bool = False) -> None:
        """
        Append a single JSON-serializable dict to a JSONL file.

        Args:
            record: A single dict to be written as one line of JSON.
            path: Output file path.
            ensure_ascii: If True, non-ASCII characters are escaped.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")

    @staticmethod
    @contextmanager
    def jsonl_writer(path: str, mode: str = "w", ensure_ascii: bool = False) -> Callable[[Any], None]:
        """
        Context manager that opens a JSONL file once and yields a `write_one(obj)` function.
        Each call to `write_one(obj)` writes one JSON object per line.

        Usage:
            with FileWriter.jsonl_writer("out.jsonl") as write_one:
                for obj in objs:
                    write_one(obj)
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode, encoding="utf-8", newline="\n") as f:
            def _write_one(obj: Any) -> None:
                f.write(json.dumps(obj, ensure_ascii=ensure_ascii) + "\n")
            yield _write_one