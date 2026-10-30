import os, shutil, tempfile, glob
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "x"), exist_ok=True)
shutil.copytree(os.path.join(d, "x"), os.path.join(d, "y"), dirs_exist_ok=True)
print(sorted(os.listdir(d)), os.environ.get("HOME", ""), glob.glob(os.path.join(d, "*"), recursive=True), os.getcwd())
shutil.rmtree(d, ignore_errors=True)
