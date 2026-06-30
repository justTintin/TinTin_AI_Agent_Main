# -*- coding: utf-8 -*-
import os
import shutil
import json
import re

def import_and_adjust_configs():
    print("=== Starting Tintin AI Agent Configuration Import & Path Adaptation ===")
    
    # 1. Determine local (Linux) paths
    # The script is assumed to be run from: <workspace>/ubuntu_migration_bundle/import_configs.py
    # So workspace root is the parent directory of this script's parent
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.dirname(script_dir)
    studio_dir = os.path.join(workspace_root, "studio")
    legacy_crawler_dir = os.path.join(workspace_root, "legacy_crawler")
    
    print(f"Detected Linux Workspace Root: {workspace_root}")
    
    # 2. Define copy mappings: (src_relative_to_bundle, target_absolute)
    mappings = [
        ("studio_config/config.ini", os.path.join(studio_dir, "config.ini")),
        ("studio_config/ai_config.json", os.path.join(studio_dir, "config", "ai_config.json")),
        ("studio_config/erp_config.json", os.path.join(studio_dir, "config", "erp_config.json")),
        ("studio_config/material_index_config.json", os.path.join(studio_dir, "config", "material_index_config.json")),
        ("studio_data/hotspots.json", os.path.join(studio_dir, "data", "hotspots.json")),
        ("studio_data/knowledge_dir.json", os.path.join(studio_dir, "data", "knowledge_dir.json")),
        ("studio_data/media_library.json", os.path.join(studio_dir, "data", "media_library.json")),
        ("studio_data/my_knowledge.json", os.path.join(studio_dir, "data", "my_knowledge.json")),
        ("studio_data/product_library.json", os.path.join(studio_dir, "data", "product_library.json")),
        ("studio_data/tag_library.json", os.path.join(studio_dir, "data", "tag_library.json")),
        ("studio_data/video_predictions.json", os.path.join(studio_dir, "data", "video_predictions.json")),
        ("studio_accounts/accounts.json", os.path.join(studio_dir, "accounts", "accounts.json")),
        ("douyin_cookies.txt", os.path.join(studio_dir, "douyin_cookies.txt")),
        ("legacy_crawler_config/config.ini", os.path.join(legacy_crawler_dir, "config.ini"))
    ]
    
    # 3. Copy files
    for src_rel, dest_abs in mappings:
        src_abs = os.path.join(script_dir, src_rel)
        if not os.path.exists(src_abs):
            print(f"[SKIP] Source file '{src_rel}' not found in bundle.")
            continue
            
        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
        shutil.copy2(src_abs, dest_abs)
        print(f"[COPY] Imported: {src_rel} -> {dest_abs}")
        
    print("\n--- Starting Path Adaptation ---\n")
    
    # 4. Modify studio/config.ini
    studio_config_ini = os.path.join(studio_dir, "config.ini")
    if os.path.exists(studio_config_ini):
        with open(studio_config_ini, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace Windows workspace root paths (both double backslashes and single)
        # e.g., D:\code_workspace\TinTin_AI_Agent or D:\\code_workspace\\TinTin_AI_Agent
        pattern = r'[Dd]:\\+code_workspace\\+TinTin_AI_Agent'
        content = re.sub(pattern, workspace_root.replace('\\', '/'), content)
        # Convert remaining windows path separators
        content = content.replace('\\', '/')
        
        with open(studio_config_ini, 'w', encoding='utf-8') as f:
            f.write(content)
        print("[ADJUST] studio/config.ini updated with Linux path separators.")
        
    # 5. Modify studio/config/material_index_config.json
    material_config_path = os.path.join(studio_dir, "config", "material_index_config.json")
    if os.path.exists(material_config_path):
        try:
            with open(material_config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Update clip_model_dir
            old_clip_dir = config_data.get("clip_model_dir", "")
            if old_clip_dir:
                # Replace Windows workspace root
                new_clip_dir = re.sub(r'^[Dd]:\\+code_workspace\\+TinTin_AI_Agent', workspace_root, old_clip_dir)
                new_clip_dir = new_clip_dir.replace('\\', '/')
                config_data["clip_model_dir"] = new_clip_dir
                print(f"[ADJUST] clip_model_dir: '{old_clip_dir}' -> '{new_clip_dir}'")
                
            # Warn about NAS mount and index_directories
            print("\n[IMPORTANT NOTICE - NAS config]")
            print(f"  Current nas_root: '{config_data.get('nas_root')}'")
            print(f"  Current index_directories: {config_data.get('index_directories')}")
            print("  Please make sure to mount your NAS on Ubuntu (e.g. via mount -t cifs) and update these paths accordingly!")
            
            # Map index directories to Linux mounts if user chooses
            new_index_dirs = []
            for d in config_data.get("index_directories", []):
                # replace drive letter 'R:/' with '/mnt/r/'
                drive_match = re.match(r'^([A-Za-z]):/', d)
                if drive_match:
                    linux_mount = f"/mnt/{drive_match.group(1).lower()}/"
                    new_index_dirs.append(linux_mount)
                    print(f"  Suggested mount mapping: '{d}' -> '{linux_mount}'")
                else:
                    new_index_dirs.append(d)
            
            # Ask or just write back suggested mappings
            config_data["index_directories"] = new_index_dirs
            # Convert nas_root backslashes to forward slashes if applicable
            nas_root = config_data.get("nas_root", "")
            if nas_root.startswith("\\\\"):
                config_data["nas_root"] = "//" + nas_root[2:].replace('\\', '/')
            
            with open(material_config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            print("[ADJUST] studio/config/material_index_config.json updated.\n")
        except Exception as e:
            print(f"[ERROR] Failed to adapt material_index_config.json: {e}")

    # 6. Modify studio/accounts/accounts.json
    accounts_json_path = os.path.join(studio_dir, "accounts", "accounts.json")
    if os.path.exists(accounts_json_path):
        try:
            with open(accounts_json_path, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
                
            for acc in accounts:
                old_session_path = acc.get("session_path", "")
                if old_session_path:
                    # Resolve to new path in workspace
                    profile_id = acc.get("profile_id", "profile_default")
                    new_session_path = os.path.abspath(os.path.join(studio_dir, "accounts", "sessions", profile_id))
                    new_session_path = new_session_path.replace('\\', '/')
                    acc["session_path"] = new_session_path
                    print(f"[ADJUST] Account '{acc.get('nickname')}' session_path: '{old_session_path}' -> '{new_session_path}'")
                    
            with open(accounts_json_path, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, indent=4, ensure_ascii=False)
            print("[ADJUST] studio/accounts/accounts.json updated.")
        except Exception as e:
            print(f"[ERROR] Failed to adapt accounts.json: {e}")
            
    print("\n=== Adaptation Complete! Next, install python dependencies and run. ===")

if __name__ == "__main__":
    import_and_adjust_configs()
