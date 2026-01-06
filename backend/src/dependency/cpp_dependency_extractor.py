import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from pathlib import Path
from typing import Dict, List, Tuple, Optional

from clang import cindex
cindex.Config.set_library_file(r"C:\Program Files\LLVM\bin\libclang.dll")

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


class CppDependencyExtractor:
    """
    Analyze a C++ repository using libclang and extract dependency graphs:
      - Include graph (file-level)
      - Class inheritance graph
      - Function call graph
      - Variable reference graph
      - Symbol index (USR → file, line range)
      - Aggregated dependency edges for all relationships

    This class helps identify relationships between files, classes, and functions.
    The resulting data can support issue impact analysis, dependency reasoning,
    and risk-based prioritization.
    """

    def __init__(
        self,
        repo_root: str,
        output_dir: str,
        compile_commands: Optional[str] = None,
        include_dirs: Optional[List[str]] = None,
        std: str = "c++17",
        max_files: Optional[int] = None
    ):
        self.repo_root = Path(repo_root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.compile_commands = compile_commands
        self.include_dirs = include_dirs or []
        self.std = std
        self.max_files = max_files

        # Graph containers
        self.include_edges: List[Tuple[str, str]] = []
        self.call_edges: List[Tuple[str, str]] = []
        self.class_edges: List[Tuple[str, str]] = []
        self.varref_edges: List[Tuple[str, str]] = []
        self.all_edges: List[Dict[str, str]] = []
        self.symbol_index: Dict[str, Dict] = {}

        self._compile_args_by_file: Dict[str, List[str]] = {}

    # ---------------------------------------------------------------------
    # Public entrypoint
    # ---------------------------------------------------------------------
    def run(self) -> Dict[str, int]:
        """
        Execute the dependency extraction pipeline.
        Returns summary statistics for the extracted graphs.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"[INFO] Starting dependency extraction under {self.repo_root}")

        if self.compile_commands and Path(self.compile_commands).exists():
            self._load_compile_commands(Path(self.compile_commands))

        src_files = self._collect_source_files()
        if self.max_files:
            src_files = src_files[:self.max_files]

        for i, fpath in enumerate(src_files, 1):
            print(f"[{i}/{len(src_files)}] Analyzing: {fpath}")
            try:
                self._analyze_file(fpath)
            except Exception as e:
                print(f"[WARN] Failed: {fpath} ({e})")

        # Flush results to disk
        self._flush_outputs()

        return {
            "includes": len(self.include_edges),
            "calls": len(self.call_edges),
            "inherits": len(self.class_edges),
            "var_refs": len(self.varref_edges),
            "symbols": len(self.symbol_index)
        }

    # ---------------------------------------------------------------------
    # Core: File Analysis
    # ---------------------------------------------------------------------
    def _analyze_file(self, file_path: Path) -> None:
        """
        Parse one file via libclang and extract relationships.
        """
        args = self._compile_args_by_file.get(str(file_path), [])
        for inc in self.include_dirs:
            args.append(f"-I{inc}")

        if self.std and not any(a.startswith("-std=") for a in args):
            args.append(f"-std={self.std}")

        index = cindex.Index.create()
        tu = index.parse(str(file_path), args=args)
        if not tu:
            return

        # Include edges
        for inc in tu.get_includes():
            src = str(file_path)
            tgt = str(inc.include.name) if inc.include else None
            if tgt:
                self.include_edges.append((src, tgt))
                self.all_edges.append({"src": src, "dst": tgt, "type": "include"})

        # Recursive AST walk
        self._walk_ast(tu.cursor, file_path)

    def _walk_ast(self, node, file_path: Path) -> None:
        """
        Recursively traverse the AST to extract functions, classes, and dependencies.
        """
        if not node.location.file or str(node.location.file) != str(file_path):
            for c in node.get_children():
                self._walk_ast(c, file_path)
            return

        usr = node.get_usr()
        if usr:
            self.symbol_index[usr] = {
                "kind": str(node.kind),
                "spelling": node.spelling,
                "file": str(file_path),
                "line": node.location.line,
                "extent": {
                    "start": node.extent.start.line,
                    "end": node.extent.end.line
                }
            }

        # Extract call relationships
        if node.kind == cindex.CursorKind.CALL_EXPR:
            parent = self._get_enclosing_symbol(node.semantic_parent)
            callee = node.displayname or node.spelling
            if parent and callee:
                self.call_edges.append((parent, callee))
                self.all_edges.append({"src": parent, "dst": callee, "type": "call"})

        # Extract class inheritance
        elif node.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
            parent = node.semantic_parent.spelling
            base = node.type.spelling
            if parent and base:
                self.class_edges.append((parent, base))
                self.all_edges.append({"src": parent, "dst": base, "type": "inherits"})

        # Variable reference
        elif node.kind == cindex.CursorKind.DECL_REF_EXPR:
            parent = self._get_enclosing_symbol(node.semantic_parent)
            ref = node.displayname or node.spelling
            if parent and ref:
                self.varref_edges.append((parent, ref))
                self.all_edges.append({"src": parent, "dst": ref, "type": "var_ref"})

        for c in node.get_children():
            self._walk_ast(c, file_path)

    def _get_enclosing_symbol(self, cursor) -> Optional[str]:
        """
        Try to extract a reasonable symbol name from a parent cursor.
        """
        if not cursor:
            return None
        if cursor.spelling:
            return cursor.spelling
        elif cursor.displayname:
            return cursor.displayname
        else:
            return str(cursor.kind)

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    def _collect_source_files(self) -> List[Path]:
        """
        Collect all .cpp/.cc/.c/.h/.hpp source files under repo_root.
        """
        exts = {".cpp", ".cc", ".c", ".h", ".hpp"}
        return [
            p for p in self.repo_root.rglob("*")
            if p.suffix.lower() in exts
        ]

    def _load_compile_commands(self, cc_path: Path) -> None:
        """
        Load compile_commands.json using FileReader.
        """
        data = FileReader.read_json(str(cc_path))
        for entry in data:
            f = entry.get("file") or entry.get("filename")
            if not f:
                continue
            f = str(Path(f).resolve())
            args = entry.get("arguments")
            if not args:
                cmd = entry.get("command", "")
                args = cmd.split()
                if args and (args[0].endswith("clang") or args[0].endswith("clang++") or args[0].endswith("gcc")):
                    args = args[1:]
            if self.std and not any(a.startswith("-std=") for a in args):
                args = args + [f"-std={self.std}"]
            self._compile_args_by_file[f] = args
        print(f"[INFO] Loaded compile args for {len(self._compile_args_by_file)} files.")

    def _flush_outputs(self) -> None:
        """
        Write all dependency graph outputs to JSON files using FileWriter.
        """
        out = self.output_dir
        FileWriter.write_json(self.include_edges, str(out / "include_graph.json"))
        FileWriter.write_json(self.call_edges, str(out / "call_graph.json"))
        FileWriter.write_json(self.class_edges, str(out / "class_graph.json"))
        FileWriter.write_json(self.varref_edges, str(out / "var_ref_graph.json"))
        FileWriter.write_json(self.symbol_index, str(out / "symbol_index.json"))
        FileWriter.write_json(self.all_edges, str(out / "all_edges.json"))
        print(f"[INFO] Dependency graphs written to {self.output_dir}")


if __name__ == "__main__":
    """
    Example standalone usage:
    Extracts dependency relationships from a given C++ repository folder.
    Adjust `REPO_ROOT` and `OUT_DIR` as needed.
    """

    REPO_ROOT = r"backend/src/outputs/HysysEngine.Engine"  # your C++ source tree
    OUT_DIR = r"backend/src/outputs/HysysEngine.Engine.dependency"

    extractor = CppDependencyExtractor(
        repo_root=REPO_ROOT,
        output_dir=OUT_DIR,
        include_dirs=[REPO_ROOT],
        std="c++17",
        max_files=None,  # set to a small number for testing
    )

    summary = extractor.run()
    print("\n=== Dependency Extraction Summary ===")
    for k, v in summary.items():
        print(f"{k:<12}: {v}")

    print(f"\n[OK] All dependency graphs saved under: {OUT_DIR}")

