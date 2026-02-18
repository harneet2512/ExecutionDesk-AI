#!/usr/bin/env python3
"""
Lint script to detect em dashes in user-visible strings.

Em dashes (U+2014) should not be used in user-facing text.
Use regular hyphens (-) or periods instead.

Exit codes:
- 0: No em dashes found
- 1: Em dashes found (lists files and lines)
"""

import sys
import os
from pathlib import Path

EM_DASH = "\u2014"  # Unicode em dash character

# Directories and files to check
SEARCH_PATHS = [
    # Backend response templates and routes
    "backend/agents/response_templates.py",
    "backend/api/routes/chat.py",
    "backend/api/routes/confirmations.py",
    # Frontend components and pages
    "frontend/app",
    "frontend/components",
    "frontend/lib",
]

# File extensions to check
EXTENSIONS = {".py", ".tsx", ".ts", ".jsx", ".js"}

# Directories to skip
SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".git", "dist", "build"}


def find_em_dashes(base_path: Path) -> list:
    """Find all em dashes in the specified paths."""
    found = []

    for search_path in SEARCH_PATHS:
        full_path = base_path / search_path
        if not full_path.exists():
            continue

        if full_path.is_file():
            # Check single file
            results = check_file(full_path)
            found.extend(results)
        else:
            # Check directory recursively
            for root, dirs, files in os.walk(full_path):
                # Skip certain directories
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

                for filename in files:
                    file_path = Path(root) / filename
                    if file_path.suffix in EXTENSIONS:
                        results = check_file(file_path)
                        found.extend(results)

    return found


def check_file(file_path: Path) -> list:
    """Check a single file for em dashes."""
    results = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if EM_DASH in line:
                    # Find all occurrences in the line
                    col = 0
                    while True:
                        col = line.find(EM_DASH, col)
                        if col == -1:
                            break
                        results.append({
                            "file": str(file_path),
                            "line": line_num,
                            "column": col + 1,
                            "content": line.strip()[:80]
                        })
                        col += 1
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return results


def main():
    # Determine base path (project root)
    script_dir = Path(__file__).parent
    base_path = script_dir.parent  # Go up from scripts/ to project root

    print(f"Checking for em dashes in: {base_path}")
    print(f"Search paths: {SEARCH_PATHS}")
    print()

    found = find_em_dashes(base_path)

    if found:
        print(f"Found {len(found)} em dash(es) in user-visible strings:")
        print()
        for item in found:
            print(f"  {item['file']}:{item['line']}:{item['column']}")
            print(f"    {item['content']}")
            print()
        print("Please replace em dashes with hyphens (-) or periods.")
        sys.exit(1)
    else:
        print("No em dashes found. All clear!")
        sys.exit(0)


if __name__ == "__main__":
    main()
