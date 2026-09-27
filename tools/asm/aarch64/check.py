#!/usr/bin/env python3
"""Check one ported aarch64 file on its own, before the whole engine links.

    tools/asm/aarch64/check.py asm/aarch64/engine/scene.s [more.s ...]

For each file: assembles it after ttfx.inc (GNU as, -march=armv8-a), then
  - lists undefined symbols that nothing in the x86 engine defines either
    (typos, or local labels not spelled parent.local), and
  - lists the x86 file's top-level labels the port does not define
    (functions or data left out).
The x86 counterpart is the same path under asm/ with .asm for .s.
Exit status 1 when anything is wrong.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
X86 = ROOT / "asm"
A64 = X86 / "aarch64"
LIBC = {"pow", "sin", "cos", "sincos", "exp2", "hypot", "getenv", "pthread_create",
        "pthread_join", "pthread_sigmask", "memset", "memcpy", "memmove", "fmod"}
LABEL = re.compile(r"^([A-Za-z_][\w.]*)\s*:")
LOCAL = re.compile(r"^\s*(\.[A-Za-z_][\w]*)\s*:")
STRDEF = re.compile(r"^\s*STR\s+([A-Za-z_]\w*)\s*,")


def x86_labels(path):
    """Top-level labels, and every label as parent.local, in one NASM file."""
    top, every = [], set()
    parent = None
    for line in path.read_text().splitlines():
        m = LABEL.match(line) or STRDEF.match(line)
        if m:
            name = m.group(1)
            if not name.startswith(".."):
                top.append(name)
                every.add(name)
                every.add(name + "_len")
                parent = name
            continue
        m = LOCAL.match(line)
        if m and parent:
            every.add(parent + m.group(1))
    return top, every


def all_x86():
    names = set()
    for p in X86.rglob("*.asm"):
        if A64 in p.parents:
            continue
        names |= x86_labels(p)[1]
    return names


def check(path, known):
    path = path.resolve()
    rel = path.relative_to(A64)
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "unit.s"
        obj = Path(tmp) / "unit.o"
        src.write_text(f'.include "ttfx.inc"\n.include "{path}"\n')
        r = subprocess.run(["as", "-march=armv8-a", "-I", str(A64), "-o", str(obj), str(src)],
                           capture_output=True, text=True)
        if r.returncode:
            print(f"{rel}: assembly failed")
            print(r.stderr.rstrip())
            return False
        und = subprocess.run(["nm", "-u", str(obj)], capture_output=True, text=True).stdout.split()
        und = [u for u in und if u != "U"]
        defined = set(subprocess.run(["nm", "--defined-only", str(obj)], capture_output=True,
                                     text=True).stdout.split()[2::3])
    unknown = sorted(u for u in und if u not in known and u not in LIBC)
    if unknown:
        ok = False
        print(f"{rel}: undefined and unknown to the x86 engine: {' '.join(unknown)}")
    x86 = X86 / rel.with_suffix(".asm")
    if x86.exists():
        top, _ = x86_labels(x86)
        # "// dropped: name ..." in the port marks x86 labels it leaves out
        # on purpose (say why on the same line or next to it)
        dropped = set()
        for line in path.read_text().splitlines():
            m = re.match(r"\s*//\s*dropped:\s*(.*)", line)
            if m:
                dropped |= set(re.findall(r"[A-Za-z_][\w.]*", m.group(1).split("(")[0]))
        missing = [t for t in top if t not in defined and t not in dropped]
        if missing:
            ok = False
            print(f"{rel}: x86 labels not defined here: {' '.join(missing)}")
    if ok:
        print(f"{rel}: ok ({len(defined)} symbols, {len(und)} external)")
    return ok


def main():
    known = all_x86()
    # ported files may define helpers of their own
    for p in A64.rglob("*.s"):
        known |= x86_labels(p)[1]
    results = [check(Path(a), known) for a in sys.argv[1:]]
    sys.exit(0 if all(results) else 1)


main()
