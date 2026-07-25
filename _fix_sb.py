# -*- coding: utf-8 -*-
import sys
fp = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\studio\gui\storyboard_page.py'
with open(fp, 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Fix import
c = c.replace(
    'from gui.ai_script_page import LLMWorker, WebSearchWorker',
    'from gui.ai_script_page import LLMWorker, FeishuUploadWorker, WebSearchWorker'
)

# 2. Add feishu_row after sb.addWidget(self.sb_scroll, 1)
old = '''        sb.addWidget(self.sb_scroll, 1)

        # 底部操作行
        bottom_row = QHBoxLayout()
        btn_save = QPushButton("💾 保存分镜脚本")
        btn_save.setObjectName("secondary_button")
        btn_save.setToolTip("将分镜脚本（JSON + 文本）保存到素材管理目录")
        btn_save.clicked.connect(self._save_storyboard)
        bottom_row.addWidget(btn_save)
        bottom_row.addStretch()
        sb.addLayout(bottom_row)

        col.addWidget(card_sb, 1)
        return panel'''

new = '''        sb.addWidget(self.sb_scroll, 1)

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
        sb.addLayout(bottom_row)

        col.addWidget(card_sb, 1)
        return panel'''

if old not in c:
    print("ERROR: old text not found!")
    sys.exit(1)
c = c.replace(old, new)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(c)
print("OK - storyboard_page.py updated")
