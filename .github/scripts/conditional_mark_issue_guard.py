#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ISSUE_URL_RE = re.compile(r"https://github\.com/[^/]+/[^/]+/issues/(\d+)")
ENTRY_TYPES = {"skip", "xfail"}
TARGET_KEYS = {"testdir", "testpath"}
MARK_FILE_GLOB = "**/test_mark_conditions*.yaml"


def extract_issue_numbers(value: Any) -> set[int]:
    issues: set[int] = set()

    if isinstance(value, str):
        issues.update(int(match) for match in ISSUE_URL_RE.findall(value))
        return issues

    if isinstance(value, list):
        for item in value:
            issues.update(extract_issue_numbers(item))
        return issues

    if isinstance(value, dict):
        for item in value.values():
            issues.update(extract_issue_numbers(item))

    return issues


def collect_from_mark_entry(entry: Any) -> set[int]:
    if not isinstance(entry, dict):
        return set()

    issues: set[int] = set()
    for entry_type in ENTRY_TYPES:
        mark_config = entry.get(entry_type)
        if isinstance(mark_config, dict):
            issues.update(extract_issue_numbers(mark_config.get("conditions", [])))

    return issues


def collect_from_test_mapping(test_mapping: Any) -> set[int]:
    if not isinstance(test_mapping, dict):
        return set()

    issues: set[int] = set()
    for entry in test_mapping.values():
        issues.update(collect_from_mark_entry(entry))

    return issues


def collect_issues_from_document(document: Any) -> set[int]:
    if not isinstance(document, dict):
        return set()

    issues: set[int] = set()
    saw_target_key = False

    for key, value in document.items():
        if key in TARGET_KEYS:
            saw_target_key = True
            issues.update(collect_from_test_mapping(value))

    if saw_target_key:
        return issues

    for value in document.values():
        issues.update(collect_from_mark_entry(value))

    return issues


def load_issue_set(search_root: Path) -> set[int]:
    issues: set[int] = set()
    pattern = str(search_root / MARK_FILE_GLOB)

    for file_name in glob.glob(pattern, recursive=True):
        file_path = Path(file_name)
        with file_path.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
        issues.update(collect_issues_from_document(document))

    return issues


def split_branches(branches_arg: str) -> list[str]:
    branches = re.split(r"[\s,]+", branches_arg.strip())
    return [branch for branch in branches if branch]


def list_branch_mark_files(ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        path
        for path in result.stdout.splitlines()
        if fnmatch.fnmatch(path, MARK_FILE_GLOB)
    ]


def load_issue_set_from_branch(ref: str) -> set[int]:
    issues: set[int] = set()

    for file_path in list_branch_mark_files(ref):
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            check=True,
            capture_output=True,
            text=True,
        )
        document = yaml.safe_load(result.stdout) or {}
        issues.update(collect_issues_from_document(document))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--search-root", default=".")
    parser.add_argument("--output-json", action="store_true")
    parser.add_argument(
        "--branches",
        default="",
        help="Whitespace- or comma-separated git refs to scan in addition to the current checkout.",
    )
    args = parser.parse_args()

    issues = load_issue_set(Path(args.search_root).resolve())
    branches_examined: list[str] = []

    for branch in split_branches(args.branches):
        issues.update(load_issue_set_from_branch(branch))
        branches_examined.append(branch)

    blocked = args.issue_number in issues

    result = {
        "blocked": blocked,
        "checked_issue": args.issue_number,
        "all_conditional_mark_issues": sorted(issues),
        "branches_examined": branches_examined,
    }

    if args.output_json:
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"blocked={str(blocked).lower()}")
        print("issues=" + ",".join(str(issue) for issue in sorted(issues)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())