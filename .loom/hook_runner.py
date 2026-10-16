import os
import sys
import json
import subprocess

log_file = "/Users/loom/lanes/quadseven.wow-overseer-1045/.loom/hook.log"

try:
    with open(log_file, "a") as f:
        f.write("Hook ran!\n")
        bin_path = "/Users/loom/.gemini/antigravity-cli/bin"
        if os.path.exists(bin_path):
            f.write(f"bin exists. islink: {os.path.islink(bin_path)}\n")
            f.write(f"stat: {os.stat(bin_path)}\n")
            if os.path.islink(bin_path):
                f.write(f"link target: {os.readlink(bin_path)}\n")
        else:
            f.write("bin does not exist\n")
except Exception as e:
    with open(log_file, "a") as f:
        f.write(f"Error: {e}\n")

# Output valid response to stdout
sys.stdout.write(json.dumps({"decision": "allow"}))
