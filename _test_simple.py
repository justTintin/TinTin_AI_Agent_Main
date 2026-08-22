import os
fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\studio\gui\storyboard_page.py'
out = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_dbg.txt'
# Simple test - does this file exist?
exists = os.path.isfile(fp)
with open(out, 'w') as f:
    f.write(f'File exists: {exists}\n')
    if exists:
        with open(fp, 'r', encoding='utf-8') as f2:
            content = f2.read()
        f.write(f'File size: {len(content)}\n')
        f.write(f'First 100 chars: {content[:100]}\n')
