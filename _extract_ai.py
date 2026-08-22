import subprocess
import re

result = subprocess.run(['git', 'show', 'HEAD:studio/gui/ai_script_page.py'], capture_output=True, text=True, encoding='utf-8')
content = result.stdout
idx = content.find('class AIScriptPage')
out = []
if idx > 0:
    page = content[idx:]
    out.append("=== AIScriptPage (full) ===")
    out.append(page)

with open(r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_orig_ai_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("DONE")
