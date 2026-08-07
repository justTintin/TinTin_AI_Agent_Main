# 客户端稳定性 & 流畅度测试计划

> 版本：v2.2.0 | 最后更新：2026-07-17

---

## 一、测试范围总览

| 维度 | 目标 | 通过标准 |
|------|------|---------|
| **接口测试** | 所有服务端 API 可连通、格式对齐 | 全部 200，响应 < 30s |
| **压力测试** | 高并发下不崩溃、不丢数据 | 10并发 × 50请求，错误率 < 1% |
| **资源占用** | 内存/CPU 可控，无泄漏 | 内存 < 2GB，CPU < 50% 常态 |
| **UI 卡顿** | 主线程不阻塞，操作响应 | 任何操作 95 百分位 < 500ms |
| **功能回归** | 核心流程无崩溃、无数据丢失 | 全部 P0 用例通过 |

---

## 二、服务端接口测试

### 2.1 连通性测试

```bash
# 服务端地址
SERVER="http://X.X.X.X.X.X.X:8000"

# 批量连通性检查
curl -s -o /dev/null -w "%{http_code} %{url_effective}\n" \
  $SERVER/health \
  $SERVER/llm/chat/completions \
  $SERVER/whisper/health \
  $SERVER/voxcpm/health \
  $SERVER/ollama/status \
  $SERVER/clip/health \
  $SERVER/vsr/health \
  $SERVER/material/status \
  $SERVER/comfyui/status \
  $SERVER/tasks?limit=1 \
  $SERVER/models/status \
  $SERVER/system/license
```

**通过标准**：全部返回 2xx。

### 2.2 LLM `/llm/chat/completions` 接口测试

| 用例 | Method | Body | 预期 |
|------|--------|------|------|
| 纯文本调用 | POST | `{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"Hi"}],"max_tokens":5}` | 200, `choices[0].message.content` 非空 |
| 多模态调用 | POST | `{"model":"qwen2.5vl:7b-16k","messages":[{"role":"user","content":[{"type":"text","text":"描述"},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]}]}` | 200, 返回描述文本 |
| 无效模型 | POST | `{"model":"no-such-model","messages":[{"role":"user","content":"Hi"}]}` | 4xx，明确错误信息 |
| 空 messages | POST | `{"model":"deepseek-v4-flash","messages":[]}` | 422 |
| 大文本 | POST | system=10KB, user=50KB | 200，不截断 |
| 超时测试 | POST | timeout=180s，长文本返回 | 200，不超时 |

### 2.3 Whisper `/whisper/transcribe` 接口测试

| 用例 | 预期 |
|------|------|
| 上传 16kHz mono wav, 30s 中文语音 | 200, segments 数组非空, 文本准确 |
| 上传 5min 音频 | 200, 2min 内完成 |
| 上传非 wav 格式 | 4xx |
| 无 file 字段 | 422 |
| 指定 language=zh | 中文转写 |
| 指定 language=en | 英文转写（如有） |

### 2.4 VoxCPM `/voxcpm/tts` 接口测试

| 用例 | 预期 |
|------|------|
| text="你好世界", speaker="default" | 200, audio/wav 返回 |
| text 空 | 4xx |
| text=2000字 | 200, 60s 内完成 |
| prompt_audio 传 base64 | 200, 声音克隆生效 |

### 2.5 Ollama 接口测试

| 端点 | 预期 |
|------|------|
| GET /ollama/status | 200, 返回模型列表+进程状态 |
| GET /ollama/models | 200, models 数组 |
| POST /ollama/load (model=qwen2.5vl:7b-16k) | 200, 模型加载成功 |
| POST /ollama/unload (model=qwen2.5vl:7b-16k) | 200, 显存释放 |

### 2.6 素材管理 `/material/*` 接口测试

| 端点 | 预期 |
|------|------|
| POST /material/search (query="鼠标", top_k=20) | 200, results 数组 |
| GET /material/distinct?field=brand | 200, values 数组 |
| POST /material/ocr (上传 PNG) | 200, text 非空 |
| GET /material/stats | 200, 返回统计 |
| GET /material/list | 200, 分页数据 |

### 2.7 ComfyUI `/comfyui/*` 代理测试

| 端点 | 预期 |
|------|------|
| GET /comfyui/status | 200, online=true |
| GET /comfyui/queue | 200 |
| POST /comfyui/run (空 workflow) | 4xx 或 200 |
| POST /comfyui/upload/image | 200, 返回文件名 |

### 2.8 VSR `/vsr/*` 测试

| 用例 | 预期 |
|------|------|
| POST /vsr/remove (上传 mp4, inpaint_mode=sttn_det) | 200, 返回 task_id |
| GET /vsr/result/{task_id} | 200, 进度信息 |
| GET /vsr/download/{filename} | 200, 下载视频 |

### 2.9 混剪 `/montage/split` 测试

| 用例 | 预期 |
|------|------|
| POST /montage/split (上传 mp4, threshold=27) | 200, 返回分割结果 |
| threshold=50 | 分割数量减少 |
| min_scene_len=2 | 最小镜头 >= 2s |

---

## 三、压力测试

### 3.1 LLM 并发测试

```bash
# 10 并发 × 50 请求
for i in $(seq 1 50); do
  curl -s -X POST "$SERVER/llm/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"压力测试第'$i'次"}],"max_tokens":20}' \
    -w "%{http_code} %{time_total}s\n" -o /dev/null &
done
wait
echo "全部完成"
```

**通过标准**：
- 错误率 < 1%（最多 0~1 个失败）
- 95% 请求 < 30s
- 服务端不崩溃、Ollama 进程不退出

### 3.2 图片分析并发测试

```bash
# 5 并发多模态请求（各带 base64 图片 ~100KB）
# 通过标准：全部 200，无超时
```

### 3.3 Mix 压力场景

同时发起：3 个 LLM 文本 + 2 个视觉分析 + 1 个 Whisper 转写

**通过标准**：全部成功，GPU 显存不溢出，CPU 不持续 100%。

### 3.4 素材检索压力

```bash
# 100 次搜索
# 通过标准：95% < 2s，无超时
```

---

## 四、客户端资源占用测试

### 4.1 启动基线

| 指标 | 预期 |
|------|------|
| 内存 | < 300MB（未加载模型） |
| CPU | < 5% 闲置 |
| 启动时间 | < 5s（SSD） |

### 4.2 智能混剪流程

| 场景 | 内存峰值 | CPU 峰值 |
|------|---------|---------|
| 分割 10min 视频 → 20 镜头 | < 500MB | < 30% |
| 评分 20 个镜头（后台线程） | < 400MB | < 50% |
| 拼接 20 镜头 → 1 视频 | < 600MB | < 60% |
| LLM 生成文案（后台） | < 400MB | < 10% |

### 4.3 长时间运行

| 指标 | 测试方法 | 预期 |
|------|---------|------|
| 内存泄漏 | 运行 1 小时，循环「分割→评分→拼接」 | 内存增长 < 50MB |
| 线程泄漏 | 运行后检查 threading.active_count() | 不持续增长 |
| 文件句柄 | 运行后检查 lsof / handle | 无泄露 |

### 4.4 大文件处理

| 文件大小 | 场景 | 预期 |
|---------|------|------|
| 1GB mp4 | 分割 | 不崩溃，内存 < 1.5GB |
| 100 个镜头 | 拼接 | 不崩溃 |
| 500MB 素材目录 | 扫描加载 | < 10s |

---

## 五、UI 卡顿测试

### 5.1 响应时间要求

| 操作 | 目标 (p95) | 最大 |
|------|-----------|------|
| 切换页面 tab | < 100ms | 300ms |
| 点击按钮 → 状态变化 | < 50ms | 200ms |
| 分割表格加载 50 行 | < 200ms | 500ms |
| 弹对话框 | < 50ms | 200ms |
| 拖动滑块 → 数值更新 | < 30ms | 100ms |
| 双击预览视频 → 播放 | < 500ms | 1s |

### 5.2 关键路径主线程阻塞检测

| 操作 | 是否有后台线程 | 验证方法 |
|------|-------------|---------|
| 视频分割 | ✅ PySceneDetectWorker | 分割中拖动窗口不卡 |
| 镜头评分 | ✅ ScoreClipsWorker | 评分中点击其他按钮有反应 |
| LLM 调用 | ✅ LLMWorker | 请求中 UI 不冻结 |
| 文案生成 | ✅ SceneCopyWorker | 生成中可切换页面 |
| 预合成拼接 | ✅ 子进程 ffmpeg | 拼接中可操作其他 |
| 素材扫描 | ✅ 非 UI 线程 | 大量文件不卡 |
| 备份/还原 | ✅ BaseWorker | 操作中 UI 响应 |

### 5.3 已知风险点（需重点验证）

| 风险 | 状态 | 验证 |
|------|------|------|
| ~~EndOfMedia 信号回调 setSource() 死锁~~ | ✅ 已修复 (QTimer 延迟) | 连续播放 5 个镜头依次播完 |
| ~~分割完成同步评分卡 UI~~ | ✅ 已修复 (异步评分) | 20 镜头分割后鼠标不转圈 |
| ~~LLM URL 404 导致无响应~~ | ✅ 已修复 | 所有 LLM 调用有结果 |
| QMediaPlayer 内存/句柄泄漏 | ⚠️ 需验证 | 循环播放 50 次后内存 |
| cv2 处理大帧 OOM | ⚠️ 需验证 | 4K 视频评分不 OOM |
| ffmpeg 子进程僵尸 | ⚠️ 需验证 | 取消拼接后无残留进程 |

---

## 六、功能回归测试（覆盖全部菜单）

### 6.1 方案脚本

#### 我的知识库 (page 29)
- [ ] **加载列表**：打开页面 → 知识条目列表正常显示
- [ ] **导入收藏**：素材浏览器同步 → 导入成功
- [ ] **风格化提炼**：点「提炼风格化」→ LLM 打标并生成风格化条目
- [ ] **重新提炼**：选中条目 → 点重新提炼 → 内容更新
- [ ] **调文案**：选中风格化 → 点「调文案」→ 输入待改写文案 → LLM 改写
- [ ] **知识背景**：功能按钮已删除（确认不显示）

#### 产品资料 (page 28)
- [ ] **加载列表**：打开页面 → 产品列表显示
- [ ] **新增/编辑**：填写品牌+型号 → 保存 → 列表更新
- [ ] **智能挖掘**：填品牌+型号 → 点「🪄 智能挖掘」→ LLM 返回性能参数+卖点 → 填入字段
- [ ] **批量挖掘**：点「⚡ 挖掘」→ 逐条调用 LLM → 进度条更新
- [ ] **图片上传**：上传产品图片 → 保存成功

#### 产品文案创作 (page 30)
- [ ] **填写产品信息**：填写品类+品牌+型号
- [ ] **生成文案**：点生成 → LLM 调用 → 返回口播/带货文案
- [ ] **未配置模型提示**：清空模型配置 → 点生成 → 显示配置提示

#### 分镜脚本创作 (page 38)
- [ ] **填写产品背景**：填写产品信息 + 参考风格
- [ ] **生成分镜**：点生成 → LLM 返回分镜脚本
- [ ] **脚本编辑**：手动编辑分镜内容

---

### 6.2 媒体库

#### 即梦生成 (page 32)
- [ ] **文生图**：输入 prompt → 点生成 → 即梦 API 调用 → 显示结果
- [ ] **参数配置**：调整宽高/风格 → 生效
- [ ] **下载保存**：生成后下载到本地

#### 素材检索 (page 39)
- [ ] **关键词搜索**：输入关键词 → POST /material/search → 列表显示
- [ ] **品牌筛选**：下拉选择品牌 → 过滤结果
- [ ] **分类/类型筛选**：切换分类 → 结果更新
- [ ] **复制路径**：选中行 → 点复制路径 → 剪贴板正确
- [ ] **双击打开位置**：双击行 → 打开文件夹

#### 任务队列 (page 9)
- [ ] **任务列表**：显示服务端队列中的任务
- [ ] **同步服务端**：点同步 → 刷新列表
- [ ] **取消任务**：选中任务 → 取消

#### 素材浏览器（外部 app）
- [ ] **启动**：点按钮 → Electron 窗口弹出
- [ ] **握手**：从选题页启动 → 自动搜索

---

### 6.3 成片制作

#### 智能混剪 (page 15)
- [ ] **步骤1 分割视频**：选视频 → 点分割 → 表格显示镜头 → 评分列 ⏳ → 评分完成
- [ ] **步骤1 挑选精华**：配置时长 → 点挑选 → 精华片段 + 评分 → 弹对话框（评完再弹）
- [ ] **步骤1 生成描述**：点「生成画面文案描述」→ 调 LLM → 描述列有文字
- [ ] **步骤2 镜头重组**：勾选镜头 → 点重组 → 预合成列表
- [ ] **步骤2 LUT 还原**：选 LUT → 点合成 → 输出视频色彩正确
- [ ] **步骤2 预览播放**：点击预合成 → 播放镜头 → 自动切下一个 → 不卡死
- [ ] **步骤2 去重**：相似镜头只保留质量好的
- [ ] **步骤2 评分自动勾选**：≥7 分默认勾
- [ ] **步骤2 AI 生成文案**：点「AI 生成文案」→ LLM 生成 → 写入文本框
- [ ] **步骤2 按文案智能匹配**：粘贴文案 → 点重组 → LLM 匹配
- [ ] **步骤2 合成视频生成文案**：点按钮 → 输入品牌 → LLM 生成 → .txt+.meta.json 保存
- [ ] **步骤2 预合成文案显示**：列表显示前 30 字预览 → 双击弹窗全文
- [ ] **步骤3 口播配音**：选声音样本 → 生成配音
- [ ] **步骤4 合成导出**：配 BGM + 字幕 → 导出最终视频

#### 直播切片 (page 19)
- [ ] **直播录制**：配置直播源 → 录制
- [ ] **切片提取**：从录制中提取精华片段
- [ ] **文案生成**：LLM 分析画面生成文案

---

### 6.4 图形处理

#### 图像抠图 (page 16)
- [ ] **单张抠图**：上传图片 → 点抠图 → 生成透明背景
- [ ] **批量抠图**：选文件夹 → 批量处理

#### 图片框选 OCR (page 25)
- [ ] **框选区域**：拖拽选择图片区域
- [ ] **OCR 识别**：识别文字 → 显示结果
- [ ] **批量处理**：选文件夹 → 批量 OCR

---

### 6.5 视频处理

#### 视频转文字 (page 12)
- [ ] **选择视频**：选 mp4 → 点转写 → Whisper 调用 → 返回文本
- [ ] **语言选择**：切换中文/英文 → 生效
- [ ] **导出 SRT**：导出字幕文件

#### 声音克隆 (page 21)
- [ ] **TTS 合成**：选声音样本 + 输入文案 → 生成 wav
- [ ] **声音样本管理**：添加/删除样本
- [ ] **文案标点恢复**：LLM 恢复无标点文案
- [ ] **句尾分割**：LLM 智能断句
- [ ] **服务连通**：VoxCPM 状态灯绿色

#### 视频去字幕 (page 18)
- [ ] **上传视频**：选 mp4 → 点去字幕 → VSR 处理
- [ ] **下载结果**：处理完成 → 下载去字幕视频
- [ ] **模式选择**：sttn_det / lama / propainter

#### 视频框选 OCR (page 24)
- [ ] **框选区域**：拖拽选择视频区域
- [ ] **OCR 识别**：逐帧识别 → 汇总结果

---

### 6.6 视频运营

#### 视频评价预测 (page 35)
- [ ] **选择视频**：选 mp4 → 点预测 → 抽帧 → 视觉 LLM 分析
- [ ] **雷达图**：6 维评分显示
- [ ] **平台切换**：切换抖音/小红书/B 站 → 不同评价
- [ ] **反馈数据回填**：填写真实播放量 → 保存 → 校准 prompt
- [ ] **视觉模型测试**：点测试连接 → LLM 代理测试

#### 视频营销检测 (page 41)
- [ ] **选择视频**：选 mp4 → 点检测 → 抽帧 → 判断是否营销
- [ ] **结果详情**：置信度 / 类别 / 线索 / 建议
- [ ] **视觉模型测试**：点测试连接

---

### 6.7 系统设置

#### 模型配置 (page 7)
- [ ] **LLM 配置**：选提供商 → API 地址自动填充 → 保存
- [ ] **LLM 测试连接**：点测试 → POST /llm/chat/completions → 成功/失败提示
- [ ] **视觉模型配置**：填模型名 → 测试连接
- [ ] **Whisper/CLIP 配置**：地址从统一服务端地址联动
- [ ] **VoxCPM 配置**：地址手动维护 → 保存 → 测试连接
- [ ] **保存全部**：修改任意 → 点保存全部 → 所有配置持久化

#### 平台接入 (page 23)
- [ ] **抖音账号**：添加/删除账号
- [ ] **登录**：Playwright 自动登录

#### 资源配置 (page 22)
- [ ] **声音样本**：列表显示 → 添加/删除样本
- [ ] **视频配置**：添加 LUT 文件 → 保存 → 混剪界面上拉可选
- [ ] **本地配置**：设置缓存目录 → 保存 → 下次打开保持

#### 运行环境 (page 37)
- [ ] **系统状态**：CPU/RAM/GPU 信息显示
- [ ] **环境修复**：点修复 → pip install PyTorch CUDA
- [ ] **终端**：打开 Python 终端
- [ ] **备份管理**：点备份 → 生成 zip（含 video_config.json + local_config.json）
- [ ] **备份还原**：选 zip → 还原 → 配置恢复
- [ ] **素材重定位**：输旧/新前缀 → 批量替换路径

#### 帮助 (page 6)
- [ ] **帮助文档**：显示 help.md 内容

---

### 6.8 跨页面场景

- [ ] **服务端离线**：各 LLM 页面调用 → 显示明确错误提示，不崩溃
- [ ] **连续切换页面**：快速切换 10+ 页面 → 不卡顿、内存不暴涨
- [ ] **配置修改实时生效**：模型配置页改模型 → 混剪/产品页立即使用新模型
- [ ] **本地配置全局可用**：设置缓存目录 → 混剪生成文件落入该目录

---

## 七、测试 Check List

### 每次发版前（全量）

```
[ ] 接口连通性全量检查 — 60+ 端点 (2.1)
[ ] LLM 核心接口 6 用例 (2.2)
[ ] Whisper / VoxCPM / Ollama / Material / ComfyUI / VSR 各 ≥ 3 用例 (2.3-2.9)
[ ] 压力测试 LLM 10×50 (3.1) + 图片 5×20 (3.2)
[ ] 混剪完整流程 P0 回归 (6.3)
[ ] 所有 LLM 调用页面回归 (6.1, 6.2, 6.6)
[ ] 声音克隆完整流程 (6.5)
[ ] 资源配置 + 备份还原 (6.7)
[ ] 内存基线检查 (4.1)
[ ] UI 关键路径响应时间 (5.1)
[ ] 服务端离线容错 (6.8)
```

### 每周

```
[ ] 长时间运行内存泄漏检查 (4.3)
[ ] 大文件处理验证 (4.4)
[ ] QMediaPlayer 循环测试 (5.3)
[ ] ffmpeg 僵尸进程检查 (5.3)
```

---

## 八、测试工具

| 工具 | 用途 |
|------|------|
| `curl` + shell | 接口连通性、压力测试 |
| Windows 任务管理器 | CPU/内存监控 |
| `perfmon` / `resmon` | 句柄泄漏、磁盘 IO |
| `time.time()` 打点 | 客户端响应时间 |
| `loguru` 日志 | 错误追踪 |

### 快速压力脚本示例

```python
# stress_llm.py — LLM 压力测试
import threading, time, requests

SERVER = "http://X.X.X.X.X.X.X:8000"
CONCURRENT = 10
REQUESTS = 50
errors = []
times = []

def worker(start, count):
    for i in range(start, start + count):
        t0 = time.time()
        try:
            r = requests.post(f"{SERVER}/llm/chat/completions", json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": f"stress test {i}"}],
                "max_tokens": 20,
            }, timeout=60)
            elapsed = time.time() - t0
            times.append(elapsed)
            if r.status_code != 200:
                errors.append(f"req {i}: HTTP {r.status_code}")
        except Exception as e:
            errors.append(f"req {i}: {e}")

threads = []
per = REQUESTS // CONCURRENT
for i in range(CONCURRENT):
    t = threading.Thread(target=worker, args=(i * per, per))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print(f"Errors: {len(errors)}/{REQUESTS}")
if times:
    times.sort()
    print(f"P50: {times[len(times)//2]:.2f}s")
    print(f"P95: {times[int(len(times)*0.95)]:.2f}s")
    print(f"P99: {times[int(len(times)*0.99)]:.2f}s")
```
