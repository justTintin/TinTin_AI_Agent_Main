Windows 平台可执行文件。
代码中通过 get_bin(...) 自动定位到本目录。

Ollama: https://github.com/ollama/ollama/releases/latest (ollama-windows-amd64.exe → ollama.exe)
Dreamina: 即梦官方 CLI 工具
ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials → bin/ffmpeg.exe)
        放置 ffmpeg.exe 到本目录后，所有视频功能（直播切片转写、混剪、封面等）
        会通过 find_ffmpeg() 优先命中此处，无需另装系统 ffmpeg。
