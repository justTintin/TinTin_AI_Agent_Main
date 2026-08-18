 # AGENTS.md — TinTin AI Agent 编码纪律

 ## 1. 修改范围
- 只改被指出的问题或当前任务明确要求改的文件/函数。
- 不因为“顺手”重构无关代码；如需改动必须在本轮请求范围内。
- 修改前先 `git diff` 确认当前工作区状态，不覆盖用户未提交的改动。

 ## 2. 读全再改
- 修改任何函数前，必须读完该函数的完整实现 + 直接调用方。
- 修改 storage/网络/模型/任务等边界层时，必须读完对应抽象层的接口约定。
- 不抄表面：例如 WebDAV 路径处理必须看完 `storage.abspath()` 全部分支。

 ## 3. 测试守护
- 每次改代码，优先给该链路补测试；没有测试的改动必须说明风险。
- 改客户端分割/组合/分析代码 → 必须跑 `python_embeded\python.exe -m unittest discover tests/unit`。
- 新增测试放在 `tests/unit/` 或 `tests/integration/`，沿用现有 `testutil` 路径设置。
- 测试必须能离线跑：核心 worker 用 mock，不依赖真实服务端或模型。

 ## 4. 运行验证
- 使用工程自带的 `python_embeded\python.exe`。
- 改后至少执行：
  1. `python_embeded\python.exe -m py_compile <修改的文件>`
  2. `python_embeded\python.exe -m unittest discover tests/unit`
  3. `python_embeded\python.exe build.py run` 启动无导入错误
- 不把这些验证当成“可选”，必须在本轮内完成。

 ## 5. 结构化纪律
- UI 层只做展示和事件转发，业务逻辑下沉到 controller/worker。
- 一个文件超过 2000 行必须考虑拆 controller；VideoMontagePage 当前正在逐步拆分。
- 不改别人的代码风格；新增代码与文件现有风格一致。

 ## 6. 提交前
- `git diff` 自检：确认只包含必要改动。
- 不遗留临时文件、`print` 调试语句、未关闭的文件句柄。
- 中文注释/字符串保持 UTF-8，不在源码里混用乱码。

 ## 7. 发现历史债务
- 如发现无关但严重的 bug，单独记录，不夹带在本次改动里。
- 向用户说明：发现了什么、为什么现在不改、建议什么时候处理。
