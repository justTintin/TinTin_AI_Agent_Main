# -*- coding: utf-8 -*-
import os
import shutil
import zipfile

def export_configurations():
    print("=== Starting 螺丝钉-电商智能体矩阵 Configuration Export ===")
    
    # Define source paths
    src_paths = {
        "studio_config/config.ini": "studio/config.ini",
        "studio_config/ai_config.json": "studio/config/ai_config.json",
        "studio_config/erp_config.json": "studio/config/erp_config.json",
        "studio_config/material_index_config.json": "studio/config/material_index_config.json",
        "studio_data/hotspots.json": "studio/data/hotspots.json",
        "studio_data/knowledge_dir.json": "studio/data/knowledge_dir.json",
        "studio_data/media_library.json": "studio/data/media_library.json",
        "studio_data/my_knowledge.json": "studio/data/my_knowledge.json",
        "studio_data/product_library.json": "studio/data/product_library.json",
        "studio_data/tag_library.json": "studio/data/tag_library.json",
        "studio_data/video_predictions.json": "studio/data/video_predictions.json",
        "studio_accounts/accounts.json": "studio/accounts/accounts.json",
        "douyin_cookies.txt": "studio/douyin_cookies.txt",
    }
    
    bundle_dir = "ubuntu_migration_bundle"
    if not os.path.exists(bundle_dir):
        os.makedirs(bundle_dir)
        print(f"Created migration bundle directory: '{bundle_dir}'")
        
    copied_count = 0
    for target_rel, src_rel in src_paths.items():
        src_abs = os.path.abspath(src_rel)
        target_abs = os.path.abspath(os.path.join(bundle_dir, target_rel))
        
        # Ensure target subdirectories exist
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        
        if os.path.exists(src_abs):
            shutil.copy2(src_abs, target_abs)
            print(f"[OK] Exported: {src_rel} -> {os.path.join(bundle_dir, target_rel)}")
            copied_count += 1
        else:
            print(f"[WARNING] File not found: {src_rel} (Skipped)")
            
    print(f"\nExported {copied_count} files to '{bundle_dir}/'")
    
    # Zip the entire migration bundle folder
    zip_filename = "ubuntu_migration_bundle.zip"
    print(f"\nPackaging '{bundle_dir}/' into '{zip_filename}'...")
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(bundle_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, os.path.dirname(bundle_dir))
                    zipf.write(file_path, arcname)
        print(f"[OK] Created archive: '{zip_filename}'")
    except Exception as e:
        print(f"[ERROR] Failed to create zip file: {e}")
        
    print("=== Export execution completed ===")

if __name__ == "__main__":
    export_configurations()

