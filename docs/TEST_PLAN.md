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
SERVER="http://192.168.111.30:8000"

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

## 六、功能回归测试（P0）

### 6.1 智能混剪

- [ ] **分割视频**：选择 mp4 → 点分割 → 表格显示镜头 → 评分列 ⏳ → 评分完成
- [ ] **挑选精华**：配置精华时长 → 点挑选 → 生成精华片段 → 评分 → 弹对话框
- [ ] **生成描述**：点「生成画面文案描述」→ 调用 LLM → 描述列填充有意义文字
- [ ] **镜头重组**：勾选镜头 → 点重组 → 预合成列表 → 双击预合成查看文案
- [ ] **LUT 还原**：选择 LUT → 点合成 → 输出的视频色彩正确
- [ ] **预览播放**：点击预合成 → 播放第一个镜头 → 自动切下一个 → 不卡死
- [ ] **去重**：两个相似镜头并存 → 重组时只保留质量好的
- [ ] **评分自动勾选**：≥7 分默认勾，<7 分不勾

### 6.2 LLM 调用

- [ ] **产品资料挖掘**：填品牌+型号 → 点挖掘 → 返回性能参数和卖点
- [ ] **AI 脚本生成**：填参考 → 点生成 → 返回文案
- [ ] **知识库提炼**：有点素材 → 点提炼 → 风格化条目生成
- [ ] **分镜脚本**：填产品信息 → 生成分镜
- [ ] **混剪文案生成**：点「AI 生成文案」→ 画面对应文案

### 6.3 资源配置

- [ ] **视频配置**：添加 LUT 文件 → 保存 → 混剪界面下拉可选
- [ ] **本地配置**：设置缓存目录 → 保存 → 下次打开保持

### 6.4 备份管理

- [ ] **备份**：点备份 → 生成 zip → 含 video_config.json + local_config.json
- [ ] **还原**：选 zip → 还原 → 配置恢复

### 6.5 声音克隆

- [ ] **TTS 合成**：选声音样本 + 输入文案 → 生成 wav
- [ ] **服务连通**：状态灯绿色

---

## 七、测试 Check List

### 每次发版前

```
[ ] 接口连通性全量检查 (2.1)
[ ] LLM 核心接口 6 用例 (2.2)
[ ] 压力测试 10×50 (3.1)
[ ] 混剪完整流程回归 (6.1)
[ ] 内存基线检查 (4.1)
[ ] UI 关键路径响应时间 (5.1)
```

### 每周

```
[ ] 长时间运行内存泄漏检查 (4.3)
[ ] 大文件处理验证 (4.4)
[ ] QMediaPlayer 循环测试 (5.3)
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

SERVER = "http://192.168.111.30:8000"
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
