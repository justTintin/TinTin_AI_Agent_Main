import sys
fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\studio\gui\storyboard_page.py'
result_file = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_result.txt'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

lines = []
if 'FeishuUploadWorker' in content:
    lines.append('FeishuUploadWorker IS in file')
else:
    lines.append('FeishuUploadWorker NOT in file')

if 'feishu_row' in content:
    lines.append('feishu_row IS in file')
else:
    lines.append('feishu_row NOT in file')

# File length
lines.append(f'File length: {len(content)} chars, {content.count(chr(10))} lines')

with open(result_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
