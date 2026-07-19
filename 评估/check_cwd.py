import subprocess

# 完全照 cron backend 的方式模拟 (line 1942-1949)
out = subprocess.run(
    [r"C:\Users\Admin\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe",
     r"C:\Users\Admin\AppData\Local\hermes\scripts\push_mcp_report.py"],
    capture_output=True, text=True, timeout=30,
    cwd=r"C:\Users\Admin\AppData\Local\hermes\scripts",
)
print('---STDOUT---')
print('len raw:', len(out.stdout))
print('len stripped:', len(out.stdout.strip()))
print('first 200:', repr(out.stdout[:200]))
print('last 200:', repr(out.stdout[-200:]))
print('---STDERR---')
print(out.stderr)
