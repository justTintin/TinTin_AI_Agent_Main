import sys

def replace_powershell(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    content = content.replace('```powershell', '```cmd')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    replace_powershell("d:/sophis-workspace/TinTin_AI_Agent/ai_skills/Automated_Listing_Skill/SKILL.md")
