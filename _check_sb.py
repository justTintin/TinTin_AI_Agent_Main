import sys
fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\studio\gui\storyboard_page.py'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()
# Just check if the old text still exists
if 'from gui.ai_script_page import LLMWorker, WebSearchWorker' in content:
    print("Old import FOUND - needs replacement")
else:
    print("Old import NOT found - already replaced or different")

if 'FeishuUploadWorker' in content:
    print("FeishuUploadWorker IS in file")
else:
    print("FeishuUploadWorker NOT in file")
