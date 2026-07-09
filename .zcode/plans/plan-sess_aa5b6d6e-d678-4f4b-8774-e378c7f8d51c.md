## PRD 实施计划：P0 双项

---

### P0.1: 试用白名单机制

**原理**：机器码 + 手动激活码双重验证

**涉及文件：**

| 文件 | 操作 |
|------|------|
| `studio/config/trial_whitelist.json` | **新建** — 白名单配置（gitignored），含 `machine_ids` 数组 |
| `studio/utils/license.py` | **修改** — 新增激活码验证、白名单检查 |
| `studio/gui/dialogs.py` | **修改** — 新增 `ActivationDialog` 激活码输入弹窗 |
| `studio/gui_main.py` | **修改** — 启动流程：白名单 → 激活码 → License 三级检查 |
| `.gitignore` | **修改** — 添加 `trial_whitelist.json` 忽略规则 |

**启动流程图：**
```
启动
 └→ _LICENSE_CHECK_DISABLED=True？ → 是 → 跳过（开发模式）
 └→ 机器码在白名单里？ → 是 → 放行
 └→ 有有效 license.dat？ → 是 → 放行
 └→ 弹出激活码输入对话框
      ├→ 用户输入激活码 → 验证通过 → 保存本地缓存 → 放行
      └→ 用户关闭 → 退出程序
```

**激活码生成**：开发者用 `python license.py sign <machine_id> <客户名> <天数>` 签发一个短期 License 作为激活码，用户粘贴进去即可。

---

### P0.2: 整体工程加密

**方案**：PyInstaller `--key` AES256 字节码加密（内置，免费）

**涉及文件：**

| 文件 | 操作 |
|------|------|
| `build.py` | **修改** — Windows/Linux 构建命令均加上 `--key` 参数 |
| `build.py` | **修改** — 加密密钥从环境变量 `BUILD_KEY` 读取（避免硬编码在代码里） |

**密钥管理：**
- 密钥不硬编码在 `build.py` 中，通过环境变量 `BUILD_KEY` 传入：
  ```bash
  BUILD_KEY="your-32-char-key" python build.py win
  ```
- 若环境变量未设置，则使用降级密钥（至少保证构建不中断）

---

### 不涉及范围（移至 P1）
- License 在线激活、试用机制、续费提醒、离线宽容
- 用户系统（手机号/数据库/API）
- 多平台分发
- 数据看板
