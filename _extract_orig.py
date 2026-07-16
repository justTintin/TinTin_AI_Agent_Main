import subprocess, re, os

# Read with git directly - binary mode
r = subprocess.run(['git', '-C', r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main', 'show', 'HEAD:studio/gui/storyboard_page.py'], capture_output=True)
content = r.stdout.decode('utf-8')

out_parts = []

# _get_feishu_config
m = re.search(r'def _get_feishu_config.*?(?=\ndef )', content, re.DOTALL)
if m: out_parts.append('===_get_feishu_config===\n' + m.group())

# _get_script_table_as_text
m = re.search(r'def _get_script_table_as_text.*?(?=\ndef )', content, re.DOTALL)
if m: out_parts.append('===_get_script_table_as_text===\n' + m.group())

# _upload_to_feishu
m = re.search(r'def _upload_to_feishu.*?(?=\ndef )', content, re.DOTALL)
if m: out_parts.append('===_upload_to_feishu===\n' + m.group())

# _default_storyboard_name (original)
m = re.search(r'def _default_storyboard_name.*?(?=\ndef )', content, re.DOTALL)
if m: out_parts.append('===_default_storyboard_name===\n' + m.group())

# _save_storyboard with feishu part
sidx = content.find('def _save_storyboard')
if sidx >= 0:
    eidx = content.find('def ', sidx + 20)
    save_text = content[sidx:eidx] if eidx > 0 else content[sidx:]
    # Only extract the feishu part (checkboxes, upload)
    # Find the feishu-specific section
    feishu_idx = save_text.find('飞书')
    if feishu_idx >= 0:
        out_parts.append('===_save_storyboard_feishu_part===\n' + save_text[max(0, feishu_idx-200):])

out_path = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_orig_feishu_code.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(out_parts))
print('OK', len(out_parts), 'parts')
