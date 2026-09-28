#!/usr/bin/env python3
"""Tiny dependency-free lint: reports (a) names that are loaded but never defined anywhere
in the file and (b) imports that are never used. It is a stand-in for `ruff --select E9,F`
in environments where ruff is unavailable; it is less precise (scope-insensitive), so
treat hits as leads. Usage: python scripts/static_name_check.py FILE [FILE...]"""

import ast
import builtins
import sys


def check(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    defined = set(dir(builtins)) | {"__file__", "__name__"}
    imported = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                nm = (a.asname or a.name).split(".")[0]
                defined.add(nm)
                imported[nm] = n.lineno
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
            if not isinstance(n, ast.ClassDef):
                for a in n.args.args + n.args.kwonlyargs + n.args.posonlyargs:
                    defined.add(a.arg)
                if n.args.vararg:
                    defined.add(n.args.vararg.arg)
                if n.args.kwarg:
                    defined.add(n.args.kwarg.arg)
        elif isinstance(n, ast.Lambda):
            for a in n.args.args:
                defined.add(a.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            defined.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, ast.Global):
            defined.update(n.names)
    used = set()
    problems = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            used.add(n.id)
            if n.id not in defined:
                problems.append(f"{path}:{n.lineno}: undefined name {n.id!r}")
        elif isinstance(n, ast.Attribute):
            pass
    # names used only inside string annotations / __all__
    text_uses = src
    for nm, ln in imported.items():
        if nm not in used and nm != "annotations" and text_uses.count(nm) < 2:
            problems.append(f"{path}:{ln}: unused import {nm!r}")
    return problems


if __name__ == "__main__":
    out = []
    for p in sys.argv[1:]:
        out += check(p)
    print("\n".join(out) or "no problems found")
    sys.exit(1 if out else 0)
