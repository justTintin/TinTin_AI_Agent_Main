import os
import re
import zipfile
from pathlib import Path

def get_version(skill_md_path):
    with open(skill_md_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.match(r"^version:\s*(.+)$", line)
            if match:
                return match.group(1).strip()
    return "unknown"

def main():
    src_dir = Path(__file__).parent.absolute()
    skill_md = src_dir / "SKILL.md"
    version = get_version(skill_md)
    print(f"检测到版本号: {version}，准备打包...")

    zip_filename = src_dir / f"Automated_Listing_Skill_{version}.zip"
    
    exclude_dirs = {'chrome_user_data', 'chrome_user_data_debug', '__pycache__', 'results', 'erp_cache'}
    exclude_exts = {'.zip', '.pyc'}
    
    if zip_filename.exists():
        os.remove(zip_filename)
        
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(src_dir):
            # 过滤不需要的目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                # 过滤不需要的文件
                if any(file.endswith(ext) for ext in exclude_exts):
                    continue
                    
                file_path = Path(root) / file
                
                # 特殊过滤 data\results 和 data\erp_cache
                rel_path = file_path.relative_to(src_dir)
                rel_parts = rel_path.parts
                if len(rel_parts) > 1 and rel_parts[0] == 'data' and rel_parts[1] in ('results', 'erp_cache'):
                    continue
                    
                zipf.write(file_path, arcname=rel_path)

    size_mb = zip_filename.stat().st_size / (1024 * 1024)
    print(f"打包完成: {zip_filename}")
    print(f"文件大小: {size_mb:.2f} MB")

if __name__ == "__main__":
    main()
