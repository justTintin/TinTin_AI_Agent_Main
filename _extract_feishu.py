# -*- coding: utf-8 -*-
# Extract feishu methods from orig file
import sys

orig_path = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_orig_sb_utf8.txt'
output_path = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_feishu_methods.txt'

with open(orig_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

import re

output = []

# 1. _get_feishu_config
m = re.search(r'    def _get_feishu_config.*?(?=\n    def )', content, re.DOTALL)
if m:
    output.append("# === _get_feishu_config ===")
    output.append(m.group())

# 2. _get_script_table_as_text
m = re.search(r'    def _get_script_table_as_text.*?(?=\n    def )', content, re.DOTALL)
if m:
    output.append("# === _get_script_table_as_text ===")
    output.append(m.group())

# 3. _upload_to_feishu
m = re.search(r'    def _upload_to_feishu.*?(?=\n    def )', content, re.DOTALL)
if m:
    output.append("# === _upload_to_feishu ===")
    output.append(m.group())

# 4. _default_storyboard_name (original with feishu priority)
m = re.search(r'    def _default_storyboard_name.*?(?=\n    def )', content, re.DOTALL)
if m:
    output.append("# === _default_storyboard_name (orig) ===")
    output.append(m.group())

# 5. _save_storyboard (full)
sidx = content.find('def _save_storyboard')
if sidx >= 0:
    eidx = content.find('\n    def ', sidx + 5)
    save_section = content[sidx:eidx] if eidx > 0 else content[sidx:]
    output.append("# === _save_storyboard (full) ===")
    output.append(save_section)

with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(output))

print(f"Extracted {len(output)//2} methods to {output_path}")
