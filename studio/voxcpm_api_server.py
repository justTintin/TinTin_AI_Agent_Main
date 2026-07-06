# -*- coding: utf-8 -*-
import sys
import os

# 将 voxcpm2 venv 的 site-packages 加入路径（由 get_voxcpm_python 设置）
_extra_sp = os.environ.pop("VOXCPM_EXTRA_PATH", "")
if _extra_sp and os.path.isdir(_extra_sp):
    sys.path.insert(0, _extra_sp)

import argparse
import base64
import tempfile
import traceback
import io
import gc
import signal
import threading
import time
from flask import Flask, request, jsonify, send_file

# Add project root to python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 确保能找到 voxcpm 包（源码路径和已安装路径都尝试）
_voxcpm_src = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "apps", "voxcpm2", "src"
))
if os.path.isdir(_voxcpm_src) and _voxcpm_src not in sys.path:
    sys.path.insert(0, _voxcpm_src)



app = Flask(__name__)
model = None
model_lock = threading.Lock()  # 防止多请求并发竞争GPU资源
_checkpoint_path = None
_gpu_warn_threshold_mb = 20 * 1024  # 当剩余显存 < 20GB 时打印警告

# ─── GPU 显存监控工具 ───────────────────────────────────────────
def _get_gpu_info():
    """返回 (已用MB, 总MB) 或 None。"""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        used = torch.cuda.memory_allocated(0) // 1024 // 1024
        total = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
        return used, total
    except Exception:
        return None


def _release_gpu_cache():
    """安全地释放未使用的 GPU 显存缓存，降低驱动内存碎片压力。"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()
    except Exception:
        pass


# ─── 健康检查接口 ───────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    gpu_info = _get_gpu_info()
    info = {"status": "ok", "model_loaded": model is not None}
    if gpu_info:
        used_mb, total_mb = gpu_info
        info["gpu_used_mb"] = used_mb
        info["gpu_total_mb"] = total_mb
        info["gpu_free_mb"] = total_mb - used_mb
    return jsonify(info)


# ─── TTS 推理接口 ───────────────────────────────────────────────
@app.route("/v1/tts", methods=["POST"])
def tts():
    global model
    if not model:
        return jsonify({"error": "Model not loaded"}), 500

    try:
        data = request.json or {}
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "Text is empty"}), 400

        ref_audio_path = None
        prompt_text = None
        references = data.get("references", [])
        if references and isinstance(references, list) and len(references) > 0:
            ref_data = references[0]
            audio_b64 = ref_data.get("audio")
            prompt_text = ref_data.get("text", "").strip()
            if audio_b64:
                # 保存 base64 音频到临时文件
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(base64.b64decode(audio_b64))
                    ref_audio_path = tmp.name

        # 客户端可选传入生成质量参数；不传则使用服务端默认值
        cfg_value = float(data.get("cfg_value", 2.0))
        inference_timesteps = int(data.get("inference_timesteps", 10))
        normalize = bool(data.get("normalize", True))   # 默认开启文本归一化
        # denoise 只在模型加载了降噪器时才生效；服务端以 load_denoiser=False 启动时忽略
        denoise = bool(data.get("denoise", False)) and (model.denoiser is not None)

        import numpy as np
        import soundfile as sf

        # ─── 使用互斥锁，防止多个请求同时抢占 GPU ──────────────
        with model_lock:
            # 推理前检查剩余显存，打印警告（但不阻断）
            gpu_info = _get_gpu_info()
            if gpu_info:
                used_mb, total_mb = gpu_info
                free_mb = total_mb - used_mb
                if free_mb < 2048:  # 剩余 < 2GB 发出严重警告
                    print(
                        f"[VOXCPM WARNING] GPU 剩余显存严重不足: {free_mb}MB，"
                        f"此次推理可能失败或导致系统不稳定！",
                        flush=True
                    )

            try:
                if ref_audio_path:
                    if prompt_text:
                        # 开启终极克隆（Ultimate Cloning）高保真模式，传递 prompt_wav_path 和 prompt_text
                        audio_arr = model.generate(
                            text=text,
                            prompt_wav_path=ref_audio_path,
                            prompt_text=prompt_text,
                            reference_wav_path=ref_audio_path,
                            cfg_value=cfg_value,
                            inference_timesteps=inference_timesteps,
                            normalize=normalize,
                            denoise=denoise,
                        )
                    else:
                        audio_arr = model.generate(
                            text=text,
                            reference_wav_path=ref_audio_path,
                            cfg_value=cfg_value,
                            inference_timesteps=inference_timesteps,
                            normalize=normalize,
                            denoise=denoise,
                        )
                else:
                    audio_arr = model.generate(
                        text=text,
                        cfg_value=cfg_value,
                        inference_timesteps=inference_timesteps,
                        normalize=normalize,
                    )
            finally:
                # 无论推理成功与否，都释放 GPU 缓存
                _release_gpu_cache()
                # 清理临时参考音频文件
                if ref_audio_path:
                    try:
                        os.remove(ref_audio_path)
                    except Exception:
                        pass

        # 获取采样率（VoxCPM 默认 48000）
        sample_rate = 48000
        if hasattr(model, "tts_model") and hasattr(model.tts_model, "sample_rate"):
            sample_rate = model.tts_model.sample_rate

        # 将 numpy 音频写入 WAV 字节缓冲区并返回
        wav_io = io.BytesIO()
        sf.write(wav_io, audio_arr, sample_rate, format="WAV")
        wav_io.seek(0)

        return send_file(wav_io, mimetype="audio/wav")

    except MemoryError as e:
        # GPU / 系统内存不足时的专项处理
        _release_gpu_cache()
        traceback.print_exc()
        return jsonify({"error": f"内存不足，请减小输入文本长度或等待一段时间后重试: {e}"}), 503
    except Exception as e:
        _release_gpu_cache()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ─── 优雅退出处理 ───────────────────────────────────────────────
def _handle_shutdown(signum, frame):
    """收到终止信号时，先释放 GPU 资源再退出，避免驱动内存泄漏。"""
    print("[VOXCPM] 收到退出信号，正在释放 GPU 资源...", flush=True)
    global model
    with model_lock:
        if model is not None:
            try:
                del model
                model = None
            except Exception:
                pass
        _release_gpu_cache()
    print("[VOXCPM] GPU 资源已释放，进程退出。", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1:8000")
    parser.add_argument("--checkpoint-path", default="openbmb/VoxCPM2")
    args = parser.parse_args()

    _checkpoint_path = args.checkpoint_path
    # 如果路径是本地目录，转为绝对路径（避免被当成 HuggingFace repo ID）
    if not _checkpoint_path.startswith("openbmb/"):
        _abs = os.path.abspath(_checkpoint_path)
        if not os.path.isdir(_abs):
            # 可能相对路径基于工作区根目录而非 studio/
            _abs = os.path.abspath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "..", _checkpoint_path))
        if os.path.isdir(_abs):
            _checkpoint_path = _abs

    host, port = "127.0.0.1", 8000
    if ":" in args.listen:
        host, port_str = args.listen.rsplit(":", 1)
        port = int(port_str)

    # 注册优雅退出信号处理（Windows 支持 SIGTERM 和 SIGINT）
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    print(f"voxcpm_model_path: {_checkpoint_path}, zipenhancer_model_path: None, enable_denoiser: False", flush=True)
    try:
        from voxcpm import VoxCPM
        # load_denoiser=False：避免加载额外依赖；optimize=False：禁用 Triton（Windows 不兼容）
        model = VoxCPM.from_pretrained(_checkpoint_path, load_denoiser=False, optimize=False)
        print("Model loaded successfully!", flush=True)

        # 加载后立即释放一次碎片缓存
        _release_gpu_cache()

        # 打印初始 GPU 状态
        gpu_info = _get_gpu_info()
        if gpu_info:
            used_mb, total_mb = gpu_info
            print(f"[VOXCPM] GPU 显存使用: {used_mb}MB / {total_mb}MB（模型加载后）", flush=True)

    except Exception as e:
        print(f"Failed to load VoxCPM model: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    print(f"Starting VoxCPM API server at http://{host}:{port}/v1/tts ...", flush=True)
    # threaded=False：使用单线程处理请求，避免多请求同时占用 GPU 导致显存溢出
    # (互斥锁 model_lock 已保证推理串行化，threaded=True 也安全，但关闭更省内存)
    app.run(host=host, port=port, debug=False, threaded=False)
