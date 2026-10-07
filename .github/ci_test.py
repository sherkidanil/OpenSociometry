"""Run tests and surface platform failures in public check annotations."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
)
print(result.stdout, end="")
if result.returncode:
    details = result.stdout[-9000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error::" + details)
sys.exit(result.returncode)
