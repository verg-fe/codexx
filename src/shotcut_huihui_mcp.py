"""Small CPU-only Shotcut/FFmpeg MCP for Huihui; no shell snippets or GPU paths."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

SHOTCUT = Path(r"G:\LocalCodex\tools\shotcut\Shotcut")
APPDATA = Path(r"D:\LocalCodex\shotcut-data")
OUTPUT_ROOT = Path(r"G:\LocalCodex\video-jobs")
FFMPEG = SHOTCUT / "ffmpeg.exe"
FFPROBE = SHOTCUT / "ffprobe.exe"


def _source(value: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ToolError("输入文件不存在或无法读取。") from exc
    if not path.is_file():
        raise ToolError("输入路径不是普通文件。")
    return path


def _output(value: str) -> Path:
    if not value or Path(value).name != value:
        raise ToolError("输出只接受 video-jobs 目录下的文件名，不接受目录或相对路径。")
    if Path(value).suffix.lower() != ".mp4":
        raise ToolError("输出文件必须使用 .mp4 扩展名。")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = (OUTPUT_ROOT / value).resolve()
    if path.parent != OUTPUT_ROOT.resolve():
        raise ToolError("输出必须位于 video-jobs 根目录。")
    if path.exists():
        raise ToolError("为保护现有文件，拒绝覆盖输出。")
    return path


async def _run(program: Path, args: list[str], timeout: int = 45) -> tuple[int, str, str]:
    if not program.is_file():
        raise ToolError(f"找不到 Shotcut 附带组件：{program}")
    proc = await asyncio.create_subprocess_exec(str(program), *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(SHOTCUT))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _probe_document(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ToolError("媒体探测器没有返回有效 JSON。") from exc


def main() -> None:
    global OUTPUT_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args()
    OUTPUT_ROOT = Path(args.output_root).expanduser().resolve()
    server = MCPServer("shotcut-cpu", instructions=(
        "Shotcut 26.9.27 本地视频工具。所有转码通过 FFmpeg libx264/aac CPU 执行，"
        "不用硬件编码。先 shotcut_status 检查安装，再 shotcut_media_info 读取素材，"
        "最后 shotcut_trim 导出新 MP4；output_name 必须是未占用的文件名且以 .mp4 结尾，"
        "不能传目录或相对路径。会检查真实产物且拒绝覆盖。输入必须是本机文件，"
        "输出固定在 G:\\LocalCodex\\video-jobs。它不会自动操作其他 GUI，也不上传媒体。"))

    @server.tool()
    async def shotcut_status() -> dict:
        """检查 Shotcut/FFmpeg 版本和 CPU 配置。"""
        if not (SHOTCUT / "shotcut.exe").is_file():
            raise ToolError("尚未找到 Shotcut。")
        ini = APPDATA / "shotcut.ini"
        config = ini.read_text(encoding="utf-8-sig") if ini.is_file() else ""
        def setting(section: str, key: str) -> str | None:
            match = __import__('re').search(
                rf"(?ms)^\[{__import__('re').escape(section)}\]\s*$([^\[]*)", config)
            if not match:
                return None
            value = __import__('re').search(rf"(?m)^{__import__('re').escape(key)}=(.*?)\s*$", match.group(1))
            return value.group(1).strip().lower() if value else None
        if (setting("General", "processingMode") != "0"
            or setting("player", "gpu2") != "false"
            or setting("player", "previewHardwareDecoder") != "false"
            or setting("encode", "useHardware") != "false"
            or setting("encode", "hardwareDecoder") != "false"
            or setting("proxy", "useHardware") != "false"):
            raise ToolError("Shotcut CPU 配置不存在或未生效；请先检查 D:\\LocalCodex\\shotcut-data\\shotcut.ini。")
        code, stdout, stderr = await _run(FFMPEG, ["-version"])
        if code:
            raise ToolError("Shotcut FFmpeg 无法启动：" + stderr[-1000:])
        return {"shotcut": "26.9.27", "ffmpeg": stdout.splitlines()[0] if stdout else "unknown",
                "processing": "Native8Cpu", "hardware_decode": False, "hardware_encode": False,
                "output_root": str(OUTPUT_ROOT)}

    @server.tool()
    async def shotcut_media_info(input: str) -> dict:
        """读取一个本机媒体文件的格式、时长、分辨率和音轨信息。"""
        source = _source(input)
        code, stdout, stderr = await _run(FFPROBE, ["-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(source)])
        if code:
            raise ToolError("无法读取媒体信息：" + stderr[-1200:])
        doc = _probe_document(stdout)
        return {"path": str(source), "format": doc.get("format", {}),
                "streams": [{k:s.get(k) for k in ("index","codec_type","codec_name","width","height","duration","sample_rate","channels") if k in s}
                            for s in doc.get("streams", [])]}

    @server.tool()
    async def shotcut_trim(input: str, output_name: str, start_seconds: float, end_seconds: float) -> dict:
        """按秒裁剪并导出 CPU MP4。output_name 必须是新的 .mp4 文件名（不带路径），禁止覆盖。"""
        source = _source(input)
        start, end = float(start_seconds), float(end_seconds)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ToolError("剪辑区间无效：需要有限数值且 end_seconds 大于 start_seconds。")
        if end - start > 3600:
            raise ToolError("单次 MCP CPU 导出最多 60 分钟。")
        dest = _output(output_name)
        temp = dest.with_name(dest.stem + ".partial.mp4")
        if temp.exists():
            raise ToolError("发现同名未完成临时文件；请先检查或移走：" + str(temp))
        try:
            code, probe_stdout, probe_err = await _run(FFPROBE, ["-v","error","-show_entries","format=duration",
                "-of","json",str(source)])
            if code:
                raise ToolError("输入不是 FFprobe 可读取的媒体：" + probe_err[-1000:])
            probe = _probe_document(probe_stdout)
            duration = float(probe.get("format", {}).get("duration", "nan"))
            if not math.isfinite(duration) or end > duration + 0.05:
                raise ToolError(f"结束时间超出媒体时长（{duration:.3f} 秒）。")
            argv = ["-hide_banner","-loglevel","error","-nostdin","-n","-ss",str(start),"-i",str(source),
                "-t",str(end-start),"-map","0:v:0","-map","0:a?","-c:v","libx264","-preset","ultrafast",
                "-crf","22","-threads","2","-c:a","aac","-b:a","160k","-movflags","+faststart",str(temp)]
            code, _, err = await _run(FFMPEG, argv, timeout=1200)
            if code or not temp.is_file() or temp.stat().st_size == 0:
                raise ToolError("CPU 导出失败：" + err[-1600:])
            code, stdout, err = await _run(FFPROBE, ["-v","error","-show_format","-show_streams","-of","json",str(temp)])
            if code:
                raise ToolError("导出后文件无法复核：" + err[-1000:])
            checked = _probe_document(stdout)
            streams = checked.get("streams", [])
            if not any(s.get("codec_type") == "video" for s in streams):
                raise ToolError("导出文件未包含视频流。")
            temp.replace(dest)
            return {"output":str(dest),"bytes":dest.stat().st_size,"duration":checked.get("format",{}).get("duration"),
                    "video_codec":next(s.get("codec_name") for s in streams if s.get("codec_type")=="video"),
                    "hardware_acceleration":False,"verified":True}
        except asyncio.CancelledError:
            raise ToolError("导出已取消。")
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
