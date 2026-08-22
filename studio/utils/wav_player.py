"""Windows WAV 播放器（基于 winsound）。

背景：Qt 的 QMediaPlayer / QSoundEffect 在部分 Windows 环境会按元数据/时长驱动播放，
把合法的 WAV 尾部截断（例如克隆声音 "特" 被吞成 "ti"），且 QSoundEffect 在本机
连 duration 都读不到（返回 -1）。
winsound.PlaySound 走系统原生播放通道，与第三方播放器行为一致，能完整播完整个 WAV。

说明：本项目仅支持 Windows，因此这里直接使用 winsound。
"""
import contextlib
import os
import winsound


def play_wav(wav_path):
    """异步完整播放一个 WAV 文件；若已有 winsound 播放则先停止。

    :param wav_path: WAV 文件绝对路径
    :return: bool 是否成功发起播放
    """
    try:
        stop_wav()
        if not wav_path or not os.path.exists(wav_path):
            return False
        winsound.PlaySound(
            wav_path,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        return True
    except Exception:  # winsound 系统调用
        return False


def stop_wav():
    """停止当前 winsound 播放（切换/离开页面时调用，避免声音残留）。"""
    with contextlib.suppress(Exception):
        winsound.PlaySound(None, winsound.SND_PURGE)
