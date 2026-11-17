#!/usr/bin/env python3
"""Garcar read-only release preflight. No builds, writes, migrations or deployments."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

MANIFEST = Path(__file__).resolve().parents[1] / "registry" / "stack_release_staging.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
REPO = re.compile(r"Garrettc123/[A-Za-z0-9_.-]+\Z")
BRANCH = re.compile(r"[A-Za-z0-9._/-]+\Z")


class PreflightError(ValueError):
    pass


def ordered_services(data: dict) -> list[dict]:
    if data.get("schema_version") != 1 or data.get("release_mode") != "read_only_preflight":
        raise PreflightError("Invalid or unsafe release manifest")
    if data.get("environment") != "staging":
        raise PreflightError("Unapproved deployment environment")
    for key in ("project_id", "environment_id"):
        if not UUID.fullmatch(str(data.get(key, ""))):
            raise PreflightError("Invalid " + key)
    services = data.get("services")
    prerequisites = data.get("external_prerequisites", [])
    if not isinstance(services, list) or not services or not isinstance(prerequisites, list):
        raise PreflightError("Missing service inventory")
    external = set()
    for item in prerequisites:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not UUID.fullmatch(str(item.get("service_id", ""))):
            raise PreflightError("Invalid external prerequisite")
        if item["id"] in external:
            raise PreflightError("Duplicate external prerequisite")
        external.add(item["id"])

    index = {}
    service_ids = set()
    for item in services:
        if not isinstance(item, dict):
            raise PreflightError("Invalid service row")
        key = item.get("id")
        sid = item.get("service_id")
        if not isinstance(key, str) or not key or key in index or key in external:
            raise PreflightError("Duplicate or invalid service name")
        if not UUID.fullmatch(str(sid)) or sid in service_ids:
            raise PreflightError("Duplicate or invalid service ID")
        if not REPO.fullmatch(str(item.get("repo", ""))):
            raise PreflightError("Unapproved GitHub repository")
        branch = item.get("branch")
        if not isinstance(branch, str) or not BRANCH.fullmatch(branch) or ".." in branch or branch.startswith("/"):
            raise PreflightError("Invalid Git branch")
        if not SHA.fullmatch(str(item.get("sha", ""))):
            raise PreflightError("Missing exact SHA")
        reviewed_head = item.get("reviewed_ci_head_sha")
        reviewed_paths = item.get("reviewed_ci_paths")
        if reviewed_head is not None or reviewed_paths is not None:
            # Exception is narrowly limited to one independently inspected
            # CI-only commit. It cannot approve application source changes.
            if (
                item["repo"] != "Garrettc123/garcar-payments"
                or item["sha"] != "ea4de1f55275e18d52c3742f543eebfce4093e28"
                or reviewed_head != "cb87ff7a1c7ef2e1a1c4d8f23590d2fb6d48b2fa"
                or reviewed_paths != [".github/workflows/ci.yml"]
            ):
                raise PreflightError("Unreviewed CI-only source exception")
        tier = item.get("tier")
        if type(tier) is not int or tier not in (1, 2, 3, 4):
            raise PreflightError("Invalid tier")
        deps = item.get("depends_on")
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise PreflightError("Invalid dependency list")
        index[key] = item
        service_ids.add(sid)

    for key, item in index.items():
        for dependency in item["depends_on"]:
            if dependency == key or dependency not in index.keys() | external:
                raise PreflightError("Unresolved dependency: " + key + " -> " + dependency)
            if dependency in index and index[dependency]["tier"] > item["tier"]:
                raise PreflightError("Later-tier dependency: " + key)
    done = set(external)
    visiting = set()
    ordered = []

    def visit(key: str):
        if key in done:
            return
        if key in visiting:
            raise PreflightError("Dependency cycle: " + key)
        visiting.add(key)
        for dep in index[key]["depends_on"]:
            if dep in index:
                visit(dep)
        visiting.remove(key)
        done.add(key)
        ordered.append(index[key])

    for item in sorted(services, key=lambda x: (x["tier"], x["id"])):
        visit(item["id"])
    return ordered


def _github_json(url: str) -> dict:
    # Scoped Actions tokens only see this repo and public resources.
    # Private repo lookups remain unavailable, never silently accepted.
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "garcar-release-read-only"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def get_public_head(repo: str, branch: str) -> str:
    url = "https://api.github.com/repos/" + repo + "/git/ref/heads/" + quote(branch, safe="/")
    return str(_github_json(url).get("object", {}).get("sha") or "")


def get_public_compare(repo: str, base: str, head: str) -> dict:
    # Both full SHAs and repository identities were validated in the manifest.
    url = "https://api.github.com/repos/" + repo + "/compare/" + base + "..." + head
    return _github_json(url)


def _reviewed_ci_only_change(item: dict, head: str, compare_resolver) -> bool:
    if head != item.get("reviewed_ci_head_sha"):
        return False
    delta = compare_resolver(item["repo"], item["sha"], head)
    if not isinstance(delta, dict):
        return False
    files = delta.get("files")
    base = delta.get("merge_base_commit")
    return (
        delta.get("status") == "ahead"
        and delta.get("ahead_by") == 1
        and delta.get("behind_by") == 0
        and delta.get("total_commits") == 1
        and isinstance(base, dict)
        and base.get("sha") == item["sha"]
        and isinstance(files, list)
        and len(files) == 1
        and isinstance(files[0], dict)
        and files[0].get("filename") == ".github/workflows/ci.yml"
        and files[0].get("status") == "modified"
        and item.get("reviewed_ci_paths") == [".github/workflows/ci.yml"]
    )


def preflight(
    data: dict, *, verify_github: bool = False,
    resolver=get_public_head, compare_resolver=get_public_compare,
) -> tuple[dict, bool]:
    records = []
    good = True
    for item in ordered_services(data):
        result = {
            "tier": item["tier"], "id": item["id"], "service_name": item["service_name"],
            "service_id": item["service_id"], "repo": item["repo"], "branch": item["branch"],
            "expected_deployed_sha": item["sha"], "depends_on": item["depends_on"],
            "github_head_matches_pin": None, "github_check_status": "not_checked",
            "runtime_ready": False,
        }
        if verify_github:
            try:
                head = resolver(item["repo"], item["branch"])
                result["current_github_head"] = head if SHA.fullmatch(head) else None
                result["github_head_matches_pin"] = head == item["sha"]
                if head == item["sha"]:
                    result["github_check_status"] = "verified"
                elif _reviewed_ci_only_change(item, head, compare_resolver):
                    # Deployed application SHA stays unchanged; the reviewed
                    # branch descendant changes only CI trigger configuration.
                    result["github_check_status"] = "reviewed_ci_only"
                    result["reviewed_ci_head_sha"] = head
                else:
                    result["github_check_status"] = "drift"
            except urllib.error.HTTPError as exc:
                # HTTP 404 for a private repo means this scoped CI token cannot
                # inspect it; do not falsely label the revision a mismatch.
                result["github_check_status"] = "unavailable"
                result["github_error_type"] = "HTTPError"
                result["github_http_status"] = int(exc.code)
            except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
                result["github_check_status"] = "unavailable"
                result["github_error_type"] = type(exc).__name__
            good = good and result["github_check_status"] in ("verified", "reviewed_ci_only")
        records.append(result)
    report = {
        "schema_version": 1, "project_id": data["project_id"],
        "environment_id": data["environment_id"], "environment": data["environment"],
        "release_action": "NONE", "deployment_performed": False,
        "github_checked": verify_github,
        "all_heads_match_pinned_sha": (
            all(x["github_head_matches_pin"] is True for x in records) if verify_github else None
        ),
        "source_review_policy_satisfied": good if verify_github else None,
        "ready_to_promote": False, "services": records,
        "external_prerequisites": data["external_prerequisites"],
        "unverified_tiers": data["unverified_tiers"],
        "block_reason": "Application probes, signed grants, migrations and rollback evidence still required",
    }
    evidence = json.dumps(report, sort_keys=True, indent=2) + "\n"
    report["report_sha256"] = hashlib.sha256(evidence.encode()).hexdigest()
    return report, good


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fail-closed Garcar staging preflight; no production or deployment actions")
    p.add_argument("--manifest", type=Path, default=MANIFEST)
    p.add_argument("--verify-github", action="store_true")
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result, passed = preflight(data, verify_github=args.verify_github)
        output = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0 if passed else 2
    except (PreflightError, ValueError, OSError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
