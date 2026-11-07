import hashlib, itertools, sys
src = open(sys.argv[1], 'rb').read().decode()
TARGET = "a933df4ef5c5922184b156ccaa5647f40156b40208b0a1bd79df3dff9778b6ea"
old_try = '''    try:
        rev = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
                                      stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        rev = (repo / "COMMIT").read_text().strip()   # bundled copy without .git
'''
assert old_try in src
revs = [
 '    rev = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()\n',
 '    rev = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,\n                                  stderr=subprocess.DEVNULL).strip()\n',
]
usage_variants = [
 ("Usage: python -I scripts/build_dataset.py <repo_dir> <out_dir>\n", "Usage: python -I scripts/build_dataset.py <repo_dir> <out_dir>\n"),
 ("Usage: python -I scripts/build_dataset.py <repo_dir> <out_dir>\n", "Usage: python -I scripts/build_dataset.py <repo_dir> <out_dir> <extracted_dir>\n"),
]
found = False
for r in revs:
    for imp_sub in [False, True]:
        for u_old, u_new in usage_variants:
            s = src.replace(old_try, r).replace(u_old, u_new)
            if imp_sub:
                s = s.replace("    import subprocess\n", "")
                s = s.replace("import json\nimport sys\n", "import json\nimport subprocess\nimport sys\n")
            h = hashlib.sha256(s.encode()).hexdigest()
            if h == TARGET:
                open("build_dataset.a933df4e.py", "w").write(s); print("MATCH", r[:60], imp_sub, u_new.strip()); found = True
print("found" if found else "no match")
