#!/usr/bin/env python3
"""V25.6 - static API route inventory (AST based, no imports of app code).

Walks app/api/*.py and, for every ``@router.<method>("path")`` handler, records
the dependency callables named in ``Depends(...)`` (function parameters and
decorator ``dependencies=[...]``), plus router-level ``dependencies=`` passed to
``APIRouter(...)``. Each route is then classified:

  PUBLIC          no authentication-like dependency found
  AUTHENTICATED   a session/JWT dependency (current_user, require_*, ...)
  ADMIN           admin/permission gate (guard, require_admin, require_permission*, ...)
  ORG-SCOPED      organization membership/role dependency
  RECRUITER       require_recruiter

This is *static* analysis: it proves a dependency is declared on the handler, not
that the dependency is correct, and it cannot see checks performed inside the
handler body. Every route flagged PUBLIC must be reviewed by a human.

Usage:  python scripts/security_route_inventory.py [--markdown] [--json]
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

ADMIN_DEPS = {
    "guard", "require_admin", "require_super_admin", "require_admin_access",
    "require_permission", "require_permission_dual", "require_platform_admin",
    "require_platform_permission",
    # local aliases used in this codebase (``from app.api.admin import guard as admin_guard``)
    "admin_guard", "partner_guard",
}
ORG_DEPS = {
    "require_organization_membership", "require_organization_role",
    "require_organization_admin", "require_organization_owner",
}
AUTH_DEPS = {"current_user", "current_active_user"}
RECRUITER_DEPS = {"require_recruiter"}
OPTIONAL_DEPS = {"optional_user"}


def _dep_name(node: ast.AST) -> str | None:
    """Name of the callable inside Depends(<callable>(...)) if any."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "Depends":
        if node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Call):
                arg = arg.func
            if isinstance(arg, ast.Name):
                return arg.id
            if isinstance(arg, ast.Attribute):
                return arg.attr
    return None


def _collect_deps(nodes) -> set[str]:
    found: set[str] = set()
    for n in nodes:
        for sub in ast.walk(n):
            name = _dep_name(sub)
            if name:
                found.add(name)
    return found


def _router_level_deps(tree: ast.Module) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if getattr(fn, "id", None) == "APIRouter":
                deps: set[str] = set()
                for kw in node.value.keywords:
                    if kw.arg == "dependencies":
                        deps |= _collect_deps([kw.value])
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        result[t.id] = deps
    return result


def _mount_prefixes() -> dict[str, str]:
    """file stem -> URL prefix it is mounted under, read from app/api/routes.py."""
    import re

    text = (API_DIR / "routes.py").read_text(encoding="utf-8")
    alias_to_file = dict((alias, stem) for stem, alias in re.findall(r"from app\.api\.(\w+) import router as (\w+)", text))
    prefixes: dict[str, str] = {}
    for alias, prefix in re.findall(r"include_router\((\w+)(?:,\s*prefix=\"([^\"]*)\")?", text):
        if alias in alias_to_file:
            prefixes[alias_to_file[alias]] = prefix or ""
    return prefixes


def _router_prefix(tree: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "APIRouter":
            for kw in node.value.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            result[t.id] = str(kw.value.value)
    return result


def classify(deps: set[str]) -> str:
    if deps & ADMIN_DEPS:
        return "ADMIN"
    if deps & ORG_DEPS:
        return "ORG-SCOPED"
    if deps & RECRUITER_DEPS:
        return "RECRUITER"
    if deps & AUTH_DEPS:
        return "AUTHENTICATED"
    if deps & OPTIONAL_DEPS:
        return "OPTIONAL-AUTH"
    return "PUBLIC"


def inventory() -> list[dict]:
    rows: list[dict] = []
    mounts = _mount_prefixes()
    for path in sorted(API_DIR.glob("*.py")):
        if path.name in {"__init__.py", "routes.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        router_deps = _router_level_deps(tree)
        router_prefixes = _router_prefix(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                method = dec.func.attr
                if method not in HTTP_METHODS:
                    continue
                router_name = getattr(dec.func.value, "id", "router")
                route_path = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    route_path = str(dec.args[0].value)
                deps = set(router_deps.get(router_name, set()))
                for kw in dec.keywords:
                    if kw.arg == "dependencies":
                        deps |= _collect_deps([kw.value])
                # parameter defaults: Depends(...)
                defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                deps |= _collect_deps(defaults)
                full_path = "/api/v1" + mounts.get(path.stem, "") + router_prefixes.get(router_name, "") + route_path
                rows.append(
                    {
                        "file": path.name,
                        "method": method.upper(),
                        "path": route_path,
                        "full_path": full_path,
                        "handler": node.name,
                        "router": router_name,
                        "dependencies": sorted(deps),
                        "class": classify(deps),
                    }
                )
    return rows


def main() -> int:
    rows = inventory()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
        return 0
    if "--markdown" in sys.argv:
        print("| Method | Path | Auth class | Dependencies (excl. get_db) | Handler |")
        print("|---|---|---|---|---|")
        for r in rows:
            deps = ", ".join(d for d in r["dependencies"] if d != "get_db")
            print(f"| {r['method']} | `{r['full_path']}` | {r['class']} | {deps or '—'} | {r['file']}::{r['handler']} |")
        return 0
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    print(f"routes: {len(rows)}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print("\nPUBLIC / OPTIONAL-AUTH routes (review each):")
    for r in rows:
        if r["class"] in {"PUBLIC", "OPTIONAL-AUTH"}:
            print(f"  {r['method']:6} {r['full_path']}  [{r['file']}::{r['handler']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
