import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from backend.src.sonarqube.sonar_tools.sq_issue_snippet_extractor import SQIssueSnippetExtractor


if __name__ == "__main__":
    PROJECT_KEY = "HysysEngine.Engine"

    BUGS_RAW = f"backend/src/outputs/{PROJECT_KEY}.bugs/bugs_raw.jsonl"
    OUT_JSONL = f"backend/src/outputs/{PROJECT_KEY}.bugs/bugs_with_snippets.jsonl"

    REPO_ROOT = f"backend/src/outputs/{PROJECT_KEY}"

    extractor = SQIssueSnippetExtractor(
        repo_root=REPO_ROOT,
        context_lines=2,
        encoding="utf-8",
        max_chars=20000,
        normalize_tabs=False,
    )

    extractor.extract_file_to_jsonl(BUGS_RAW, OUT_JSONL)
    print(f"[OK] Wrote: {OUT_JSONL}")
