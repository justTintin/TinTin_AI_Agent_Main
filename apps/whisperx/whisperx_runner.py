# -*- coding: utf-8 -*-
import os
import sys
import argparse
import shutil
import subprocess
import traceback

# 1. 配置 DLL 搜索路径 (必须在 import torch 等依赖 CUDA 的库之前执行)
def setup_nvidia_dll_path():
    if sys.platform != "win32":
        return

    import site
    packages_dirs = []

    try:
        packages_dirs.extend(site.getsitepackages())
    except Exception:
        pass

    try:
        packages_dirs.append(site.getusersitepackages())
    except Exception:
        pass

    try:
        base_dir = os.path.dirname(sys.executable)
        packages_dirs.append(os.path.join(base_dir, "Lib", "site-packages"))
        packages_dirs.append(os.path.join(base_dir, "lib", "site-packages"))
    except Exception:
        pass

    try:
        cwd = os.getcwd()
        packages_dirs.append(os.path.join(cwd, "python_embeded", "Lib", "site-packages"))
        packages_dirs.append(os.path.join(cwd, "python_embeded", "lib", "site-packages"))
    except Exception:
        pass

    added = False
    for p in packages_dirs:
        if not p or not os.path.isdir(p):
            continue
        nvidia_base = os.path.join(p, "nvidia")
        if os.path.isdir(nvidia_base):
            for sub in ["cublas", "cudnn"]:
                bin_path = os.path.join(nvidia_base, sub, "bin")
                if os.path.isdir(bin_path):
                    if bin_path not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(bin_path)
                            added = True
                        except Exception:
                            pass
    if added:
        print("[STAGE] 已自动加载 nvidia CUDA/cuDNN DLL 路径")
        sys.stdout.flush()

setup_nvidia_dll_path()

# 2. 将 apps 目录加入 sys.path, 确保能 import whisperx
apps_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if apps_dir not in sys.path:
    sys.path.insert(0, apps_dir)

# 自动配置 Hugging Face 镜像加速
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import torch
import whisperx

def format_srt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_vtt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_txt_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{m:02d}:{s:02d}.{ms:03d}"


def main():
    parser = argparse.ArgumentParser(description="WhisperX Subprocess Runner")
    parser.add_argument("--video_path", required=True, help="Path to input video file")
    parser.add_argument("--audio_path", required=True, help="Path to output/input audio file")
    parser.add_argument("--output_path", required=True, help="Path to output subtitle file")
    parser.add_argument("--model_name", required=True, help="Whisper model name")
    parser.add_argument("--language", default="", help="Transcription language")
    parser.add_argument("--task_type", default="transcribe", help="Task type (transcribe/translate)")
    parser.add_argument("--multi_mode", action="store_true", help="Enable speaker diarization")
    parser.add_argument("--download_root", required=True, help="Download root directory for models")
    parser.add_argument("--device_mode", default="auto", help="Device mode (auto/cuda/cpu)")
    parser.add_argument("--ffmpeg_path", default="", help="ffmpeg 可执行文件路径（由主进程解析后传入）")

    args = parser.parse_args()

    try:
        # Step 1: 音频提取（如果已存在且非空，则跳过）
        import shutil
        is_win = sys.platform == "win32"
        curr_dir = os.path.dirname(os.path.abspath(__file__))
        workspace_root = os.path.dirname(os.path.dirname(curr_dir))
        ffmpeg_exe = "ffmpeg.exe" if is_win else "ffmpeg"

        # 优先使用主进程传入的路径；否则回退到本地搜索（项目 bin / 系统 PATH / 工程根）
        ffmpeg_path = args.ffmpeg_path
        if not (ffmpeg_path and os.path.isfile(ffmpeg_path)):
            candidates = [
                os.path.join(curr_dir, ffmpeg_exe),
                os.path.join(os.path.dirname(curr_dir), ffmpeg_exe),
                os.path.join(workspace_root, ffmpeg_exe),
                os.path.join(workspace_root, "python_embeded", ffmpeg_exe),
                os.path.join(workspace_root, "python_embeded", "Scripts", ffmpeg_exe),
                os.path.join(workspace_root, "studio", "bin", "win" if is_win else "linux", ffmpeg_exe),
            ]
            ffmpeg_path = shutil.which("ffmpeg")
            if not (ffmpeg_path and os.path.isfile(ffmpeg_path)):
                for c in candidates:
                    if os.path.isfile(c):
                        ffmpeg_path = os.path.abspath(c)
                        break
        if not (ffmpeg_path and os.path.isfile(ffmpeg_path)):
            raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入系统环境变量 PATH。")

        # 将 ffmpeg 所在目录加入到当前进程的 PATH 环境变量中，以保证 whisperx.load_audio 能够成功调用 ffmpeg
        if ffmpeg_path:
            ffmpeg_dir = os.path.dirname(ffmpeg_path)
            if ffmpeg_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

        if os.path.exists(args.audio_path) and os.path.getsize(args.audio_path) > 0:
            print("[STAGE] 检测到已存在的音频文件，跳过提取音频。")
            print("[PROGRESS] 25")
            sys.stdout.flush()
        else:
            print("[STAGE] 正在读取视频并转换为声音文件...")
            print("[PROGRESS] 10")
            sys.stdout.flush()

            cmd = [
                ffmpeg_path, "-y", "-i", args.video_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                args.audio_path,
            ]
            # 隐藏命令行窗口 (Windows)
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg 提取音频失败：\n{r.stderr}")
            
            print("[STAGE] 声音文件转换完成，准备加载 WhisperX 模型...")
            print("[PROGRESS] 30")
            sys.stdout.flush()

        # Step 2: 设备选择与模型路径
        device = "cuda" if (args.device_mode == "cuda" or (args.device_mode == "auto" and torch.cuda.is_available())) else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        print(f"[STAGE] 决定运行设备: {device.upper()}, 计算精度: {compute_type}")
        sys.stdout.flush()

        # 自动解析本地模型路径
        hf_model_dir = os.path.join(args.download_root, f"models--Systran--faster-whisper-{args.model_name}")
        
        # 检查 Hugging Face 本地缓存目录中是否存在具体的 snapshot 文件夹
        hf_snapshot_path = None
        if os.path.isdir(hf_model_dir):
            snapshots_dir = os.path.join(hf_model_dir, "snapshots")
            if os.path.isdir(snapshots_dir):
                for sub in os.listdir(snapshots_dir):
                    sub_p = os.path.join(snapshots_dir, sub)
                    if os.path.isdir(sub_p) and os.path.isfile(os.path.join(sub_p, "model.bin")):
                        hf_snapshot_path = os.path.abspath(sub_p)
                        break

        simple_model_dir = os.path.join(args.download_root, args.model_name)
        simple_model_dir_alt = os.path.join(args.download_root, f"faster-whisper-{args.model_name}")
        root_model_bin = os.path.join(args.download_root, "model.bin")
        root_config_json = os.path.join(args.download_root, "config.json")

        actual_model_path = args.model_name
        local_files_only = False

        if os.path.isdir(simple_model_dir) and os.path.isfile(os.path.join(simple_model_dir, "model.bin")):
            actual_model_path = os.path.abspath(simple_model_dir)
            local_files_only = True
        elif os.path.isdir(simple_model_dir_alt) and os.path.isfile(os.path.join(simple_model_dir_alt, "model.bin")):
            actual_model_path = os.path.abspath(simple_model_dir_alt)
            local_files_only = True
        elif hf_snapshot_path:
            actual_model_path = hf_snapshot_path
            local_files_only = True
        elif os.path.isfile(root_model_bin) and os.path.isfile(root_config_json):
            actual_model_path = os.path.abspath(args.download_root)
            local_files_only = True

        if local_files_only:
            print(f"[STAGE] 正在从本地加载 WhisperX 模型（{device.upper()}/{compute_type}）：{args.model_name}...")
        else:
            print(f"[STAGE] 正在在线加载/下载 WhisperX 模型（{device.upper()}/{compute_type}）：{args.model_name}...")
        sys.stdout.flush()

        # Step 3: 初始化 VAD (CPU 模式下最稳定)
        print("[STAGE] 正在初始化语音活动检测 (VAD) 模型...")
        sys.stdout.flush()
        from whisperx.vads.pyannote import Pyannote
        vad_model = Pyannote(
            device=torch.device("cpu"),
            use_auth_token=None,
            chunk_size=30,
            vad_onset=0.5,
            vad_offset=0.363
        )

        model = whisperx.load_model(
            actual_model_path,
            device=device,
            compute_type=compute_type,
            download_root=args.download_root,
            local_files_only=local_files_only,
            vad_model=vad_model
        )

        print("[STAGE] 正在加载音频数据...")
        print("[PROGRESS] 50")
        sys.stdout.flush()
        audio = whisperx.load_audio(args.audio_path)

        print("[STAGE] 正在使用 WhisperX 转写语音...")
        print("[PROGRESS] 65")
        sys.stdout.flush()

        transcribe_options = {}
        if args.language:
            transcribe_options["language"] = args.language
        if args.task_type:
            transcribe_options["task"] = args.task_type

        result = model.transcribe(audio, batch_size=8, **transcribe_options)

        # Step 4: 对齐时间轴 (Word-level timestamps)
        print("[STAGE] 正在对齐时间轴（精确至毫秒级）...")
        print("[PROGRESS] 80")
        sys.stdout.flush()
        try:
            # Check if there is a local Chinese alignment model directory containing pytorch_model.bin
            local_zh_align_dir = os.path.join(args.download_root, "models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn")
            local_zh_align_dir_alt = os.path.join(args.download_root, "精确对齐声音")
            
            align_model_name = None
            if result["language"] == "zh":
                if os.path.isdir(local_zh_align_dir) and os.path.isfile(os.path.join(local_zh_align_dir, "pytorch_model.bin")):
                    align_model_name = os.path.abspath(local_zh_align_dir)
                    print("[STAGE] 正在从本地加载中文精确时间轴对齐模型...")
                elif os.path.isdir(local_zh_align_dir_alt) and os.path.isfile(os.path.join(local_zh_align_dir_alt, "pytorch_model.bin")):
                    align_model_name = os.path.abspath(local_zh_align_dir_alt)
                    print("[STAGE] 正在从本地加载中文精确时间轴对齐模型...")
                sys.stdout.flush()

            model_a, metadata = whisperx.load_align_model(
                language_code=result["language"],
                device=device,
                model_name=align_model_name,
                model_dir=args.download_root
            )
            result = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                device,
                return_char_alignments=False
            )
        except Exception as e:
            print(f"[STAGE] WhisperX 时间轴对齐失败，将使用原始时间轴。错误: {e}")
            sys.stdout.flush()

        # Step 5: 说话人日志 (Speaker Diarization)
        if args.multi_mode:
            print("[STAGE] 正在进行说话人角色日志划分...")
            sys.stdout.flush()
            try:
                hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HF_API_KEY")
                diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
                diarize_segments = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception as e:
                print(f"[STAGE] 角色日志划分失败（未配置 HF_TOKEN 或获取失败），跳过日志划分。错误: {e}")
                sys.stdout.flush()

        print("[STAGE] 正在保存字幕文件...")
        print("[PROGRESS] 90")
        sys.stdout.flush()

        # 生成字幕内容
        # 1. 生成 SRT 格式
        srt_lines = []
        for i, seg in enumerate(result["segments"], 1):
            start = format_srt_timestamp(seg["start"])
            end = format_srt_timestamp(seg["end"])
            text = (seg["text"] or "").strip()
            speaker = seg.get("speaker")
            if speaker:
                text = f"[{speaker}]: {text}"
            srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        srt_content = "\n".join(srt_lines).strip()

        # 2. 生成 WebVTT 格式
        vtt_lines = ["WEBVTT\n"]
        for seg in result["segments"]:
            start = format_vtt_timestamp(seg["start"])
            end = format_vtt_timestamp(seg["end"])
            text = (seg["text"] or "").strip()
            speaker = seg.get("speaker")
            if speaker:
                text = f"[{speaker}]: {text}"
            vtt_lines.append(f"{start} --> {end}\n{text}\n")
        vtt_content = "\n".join(vtt_lines).strip()

        # 3. 生成 Timeline TXT 格式
        txt_lines = []
        for seg in result["segments"]:
            start = format_txt_timestamp(seg["start"])
            end = format_txt_timestamp(seg["end"])
            text = (seg["text"] or "").strip()
            speaker = seg.get("speaker")
            if speaker:
                text = f"[{speaker}]: {text}"
            txt_lines.append(f"[{start} --> {end}]  {text}")
        txt_content = "\n".join(txt_lines).strip()

        # 4. 生成不带时间戳 of 纯文本格式
        plain_lines = []
        for seg in result["segments"]:
            text = (seg["text"] or "").strip()
            speaker = seg.get("speaker")
            if speaker:
                text = f"[{speaker}]: {text}"
            if text:
                plain_lines.append(text)
        plain_content = "\n".join(plain_lines).strip()

        os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
        
        base_out_path = args.output_path.rsplit(".", 1)[0]
        srt_path = base_out_path + ".srt"
        vtt_path = base_out_path + ".vtt"
        txt_path = base_out_path + ".txt"
        plain_path = base_out_path + "_plain.txt"
        json_path = base_out_path + ".json"

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt_content)
        with open(plain_path, "w", encoding="utf-8") as f:
            f.write(plain_content)
            
        import json
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                try:
                    return json.JSONEncoder.default(self, obj)
                except Exception:
                    return str(obj)
                    
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, cls=CustomEncoder)

        print("[PROGRESS] 100")
        print(f"[FINISHED] {srt_path}")
        sys.stdout.flush()

    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        sys.stdout.flush()
        sys.exit(1)

if __name__ == "__main__":
    main()
