# -*- coding: utf-8 -*-
import sys
fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\studio\gui\storyboard_page.py'
result_fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_sb_result.txt'

try:
    with open(fp, 'r', encoding='utf-8') as f:
        c = f.read()
    
    msg = []
    msg.append(f'File size: {len(c)} bytes')
    
    # Check if import already has FeishuUploadWorker
    if 'FeishuUploadWorker' in c:
        msg.append('FeishuUploadWorker ALREADY in file')
    else:
        msg.append('FeishuUploadWorker NOT in file - will add')
        # Fix import
        c = c.replace(
            'from gui.ai_script_page import LLMWorker, WebSearchWorker',
            'from gui.ai_script_page import LLMWorker, FeishuUploadWorker, WebSearchWorker'
        )
    
    # Check feishu_row
    if 'feishu_row' in c:
        msg.append('feishu_row ALREADY in file')
    else:
        msg.append('feishu_row NOT in file - will add')
        # Add feishu_row
        old_block = '        sb.addWidget(self.sb_scroll, 1)\n\n        # 底部操作行\n        bottom_row = QHBoxLayout()\n        btn_save = QPushButton("💾 保存分镜脚本")\n        btn_save.setObjectName("secondary_button")\n        btn_save.setToolTip("将分镜脚本（JSON + 文本）保存到素材管理目录")\n        btn_save.clicked.connect(self._save_storyboard)\n        bottom_row.addWidget(btn_save)\n        bottom_row.addStretch()\n        sb.addLayout(bottom_row)'
        
        if old_block in c:
            new_block = '''        sb.addWidget(self.sb_scroll, 1)

        # 飞书同步行（已隐藏按钮，代码保留）
        feishu_row = QHBoxLayout()
        self.lbl_feishu_info = QLabel("飞书关联：无")
        self.lbl_feishu_info.setObjectName("muted_text")
        self.lbl_feishu_info.hide()
        feishu_row.addWidget(self.lbl_feishu_info)
        feishu_row.addStretch()
        self.btn_sync_bitable = QPushButton("📊 同步到多维表格")
        self.btn_sync_bitable.setObjectName("secondary_button")
        self.btn_sync_bitable.setEnabled(False)
        self.btn_sync_bitable.clicked.connect(lambda: self._upload_to_feishu("bitable"))
        self.btn_sync_bitable.hide()
        feishu_row.addWidget(self.btn_sync_bitable)
        self.btn_sync_docx = QPushButton("📝 创建飞书文档")
        self.btn_sync_docx.setObjectName("secondary_button")
        self.btn_sync_docx.setEnabled(False)
        self.btn_sync_docx.clicked.connect(lambda: self._upload_to_feishu("docx"))
        self.btn_sync_docx.hide()
        feishu_row.addWidget(self.btn_sync_docx)
        sb.addLayout(feishu_row)

        appid, appsecret, *_ = self._get_feishu_config()
        if appid and appsecret:
            self.btn_sync_docx.setEnabled(True)

        # 底部操作行
        bottom_row = QHBoxLayout()
        btn_save = QPushButton("💾 保存分镜脚本")
        btn_save.setObjectName("secondary_button")
        btn_save.setToolTip("将分镜脚本（JSON + 文本）保存到素材管理目录")
        btn_save.clicked.connect(self._save_storyboard)
        bottom_row.addWidget(btn_save)
        bottom_row.addStretch()
        sb.addLayout(bottom_row)'''
            c = c.replace(old_block, new_block)
            msg.append('feishu_row added successfully')
        else:
            msg.append('ERROR: old block not found!')
            # Find what's around line 674
            lines = c.split('\n')
            for i, line in enumerate(lines):
                if 'sb.addWidget(self.sb_scroll' in line:
                    msg.append(f'Line {i+1}: {line}')
                    if i+1 < len(lines):
                        msg.append(f'Line {i+2}: {lines[i+1]}')
                        msg.append(f'Line {i+3}: {lines[i+2]}')
    
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(c)
    
    # Verify
    with open(fp, 'r', encoding='utf-8') as f:
        c2 = f.read()
    msg.append(f'After write - FeishuUploadWorker: {"YES" if "FeishuUploadWorker" in c2 else "NO"}')
    msg.append(f'After write - feishu_row: {"YES" if "feishu_row" in c2 else "NO"}')
    msg.append(f'After write - btn_sync_bitable: {"YES" if "btn_sync_bitable" in c2 else "NO"}')
    
    with open(result_fp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(msg))
except Exception as e:
    with open(result_fp, 'w', encoding='utf-8') as f:
        f.write(f'ERROR: {e}')
