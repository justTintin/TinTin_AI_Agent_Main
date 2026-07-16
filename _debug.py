import subprocess
import re

out = []

# Try to read orig file with different encodings
for enc in ['utf-8', 'utf-16', 'gbk', 'latin-1']:
    try:
        with open(r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\orig_storyboard_page.py', 'r', encoding=enc) as f:
            content = f.read()
            out.append(f"Encoding {enc}: {len(content)} chars")
            if len(content) > 10:
                out.append(f"Sample: {content[:50]}")
                break
    except:
        out.append(f"Encoding {enc}: FAILED")

# Try git directly through os
r = subprocess.run(['git', '-C', r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main', 'show', 'HEAD:studio/gui/storyboard_page.py'], capture_output=True)
out.append(f"\ngit raw stdout (first 20 bytes): {r.stdout[:20]}")
out.append(f"git stderr: {r.stderr[:200]}")
out.append(f"git returncode: {r.returncode}")

with open(r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_debug_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
