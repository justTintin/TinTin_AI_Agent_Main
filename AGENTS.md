# AGENTS.md — 客户端（TinTin 桌面端）开发规范

> 本规范与服务端 `AGENTS.md` 对齐，针对 PySide6 桌面客户端制定。修改客户端代码前必读。

## 项目结构

- `studio/gui/` — UI 页面与组件（纯界面/事件处理，不写业务核心逻辑）
- `studio/utils/` — 工具函数与外部 API 客户端（HTTP、文件、配置等）
- `studio/core/` — 业务核心与领域逻辑
- `studio/config/` — 配置文件与常量
- `tests/unit/` — 单元测试（离线、可独立运行）
- `tests/lib/testutil.py` — 测试公共工具
- `python_embeded/` — 工程自带 Python 运行时，所有检查命令必须用它执行

## 接口契约

客户端是服务端的消费者。**新增或改动任何服务端接口调用前，必须先确认服务端 `server/API-GUIDE.md`。**

- 服务端地址：`http://192.168.111.31:8000`
- 服务端 API 指南页面：`http://192.168.111.31:8000/guide`
- 不允许在客户端臆造字段名、路径或返回值结构。如有疑问，以 API-GUIDE.md 为准。

## 编译验证

改完任何 `.py` 文件后必须跑语法检查：

```powershell
python_embeded\python.exe -m py_compile <改动的文件>
```

## 测试门禁（必跑）

Python 没有编译器，单元测试就是客户端的“编译期检查”。**提交前必须跑通全量单元测试**：

```powershell
python_embeded\python.exe -m unittest discover tests/unit
```

如果改动触及核心链路（如数字人提交、智能混剪、一键成片、素材下载等），而现有测试未覆盖，必须同步补充测试。

### 新增测试的原则

- 把可独立验证的逻辑拆成纯函数/类，优先在 `tests/unit/` 测试。
- UI 层只做薄封装；复杂判断逻辑下沉到可测试模块。
- 测试文件命名：`test_<模块名>.py`。

## 静态检查

项目已配置 `ruff` 与 `mypy`（见 `pyproject.toml` / `.pre-commit-config.yaml`）。提交前应跑：

```powershell
python_embeded\python.exe -m ruff check <改动的文件>
python_embeded\python.exe -m mypy <改动的文件>   # 渐进覆盖
```

如已安装 pre-commit hook（`pre-commit install`），`git commit` 会自动跑 `ruff + py_compile`；语法错误、未定义变量、重复键等会直接拒绝提交。

## 分层与组件验证

### 不要混层

- `studio/gui/` 只负责界面与事件转发。
- 业务计算、JSON 解析、工作流节点识别、任务队列编排应放在 `studio/utils/` 或 `studio/core/`。
- 外部 API 调用封装成独立客户端类，不要直接在 UI 里拼 URL/解析响应。

### 组件级验证

- 大提示 produces 黑箱。改一个功能时，把它拆成可测的小模块：parser → builder → runner。
- 每个模块先写测试（红），再实现（绿），再重构，最后组装。
- UI 改动必须能在“修改最小、可回退”的前提下完成。

## 提交纪律

1. **只改被指出的地方**。不要顺手重构无关代码。
2. 提交前自查：`py_compile` 全过、`unittest discover` 全过、未引入 ruff 错误。
3. 改动影响跨模块行为时，必须补充或更新对应测试。
4. 不要在提交信息里写含糊描述；写清楚“哪个模块 / 修复或新增 / 为什么”。

## 任务与队列

客户端任务通过服务端 `/tasks` 体系调度（前缀 `c_`）。
素材任务走 `/material/tasks`（前缀 `m_`）。
成片/编排任务走 `/scheduled/tasks`（串行执行）。

客户端只负责任务的领取、执行、上报，不要绕过服务端任务队列做本地并行。
