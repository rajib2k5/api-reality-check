import subprocess, sys
r = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True, check=True, timeout=10)
out = subprocess.check_output([sys.executable, "-c", "print(2)"], stderr=subprocess.STDOUT, text=True)
p = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
p.communicate(timeout=5)
print(r.stdout, out, p.returncode)
