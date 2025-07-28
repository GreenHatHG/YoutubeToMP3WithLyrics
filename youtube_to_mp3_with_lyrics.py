#!/usr/bin/env python3
# youtube_to_mp3_with_lyrics.py (v3.2 - Corrected lyrics embedding method)

import os
import subprocess
import sys
import eyed3
import argparse
import re
import shutil
from typing import List, Tuple, Optional, Dict

# ==============================================================================
#  内部 VTT 转 LRC 转换模块 (保持不变)
# ==============================================================================
def vtt_parse_time(time_str: str) -> float:
    if '.' not in time_str: time_str += '.000'
    parts = time_str.strip().split(':')
    if len(parts) == 3: h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    elif len(parts) == 2: h, m, s = 0, int(parts[0]), float(parts[1])
    else: raise ValueError(f"无法解析时间格式: {time_str}")
    return h * 3600 + m * 60 + s

def seconds_to_lrc_time(seconds: float) -> str:
    if seconds < 0: seconds = 0
    minutes = int(seconds // 60)
    secs = seconds % 60
    centiseconds = int((secs * 100) % 100)
    return f"[{minutes:02d}:{int(secs):02d}.{centiseconds:02d}]"

def parse_vtt_file(vtt_path: str) -> List[Tuple[float, float, str]]:
    subtitles = []
    with open(vtt_path, 'r', encoding='utf-8') as f: content = f.read()
    if content.startswith('\ufeff'): content = content[1:]
    time_pattern = r'(\d{1,2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}\.\d{3})'
    blocks = content.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        if not lines: continue
        time_line_index = next((i for i, line in enumerate(lines) if '-->' in line), -1)
        if time_line_index == -1: continue
        time_match = re.search(time_pattern, lines[time_line_index])
        if time_match:
            try:
                start_sec = vtt_parse_time(time_match.group(1))
                end_sec = vtt_parse_time(time_match.group(2))
                text_content = ' '.join(lines[time_line_index+1:])
                text_content = re.sub(r'<[^>]+>', '', text_content).strip()
                if text_content: subtitles.append((start_sec, end_sec, text_content))
            except ValueError as e: print(f"警告: 跳过字幕块: {lines[0]} - {e}")
    return sorted(subtitles, key=lambda x: x[0])

def filter_subtitles(subs: List[Tuple[float, float, str]], start: float, end: float) -> List[Tuple[float, float, str]]:
    return [sub for sub in subs if sub[0] < end and sub[1] > start]

def convert_to_lrc_lines(subs: List[Tuple[float, float, str]], offset: float) -> List[str]:
    return [f"{seconds_to_lrc_time(s - offset)}{t}" for s, _, t in subs if s - offset >= 0]

# ==============================================================================
#  主执行模块 (已重构)
# ==============================================================================

def run_command(command: List[str], quiet: bool = False) -> str:
    if not quiet: print(f"\n▶️  执行命令: {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(f"\n❌ 命令执行失败，返回码: {process.returncode}")
        print(f"   错误信息: {stderr.strip()}")
        sys.exit(1)
    if not quiet:
        print(stdout)
        print("✅ 命令执行成功")
    return stdout

def get_video_metadata(url: str) -> Dict[str, str]:
    print("ℹ️  正在获取视频元数据...")
    title_raw = run_command(["yt-dlp", "--get-title", url], quiet=True).strip()
    title = re.sub(r'[\\/*?:"<>|]', '_', title_raw)
    video_id = run_command(["yt-dlp", "--get-id", url], quiet=True).strip()
    print(f"✅  获取成功: [ID: {video_id}, 标题: {title}]")
    return {"id": video_id, "title": title}

def parse_arguments():
    parser = argparse.ArgumentParser(description="独立的YouTube音频和歌词下载工具，支持缓存和目录管理。", epilog="示例: python %(prog)s \"URL\" -s 0:00 -e 2:21", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("url", help="目标YouTube视频的完整URL。")
    parser.add_argument("-s", "--start", required=True, help="截取开始时间 (格式: MM:SS 或 HH:MM:SS)。")
    parser.add_argument("-e", "--end", required=True, help="截取结束时间 (格式: MM:SS 或 HH:MM:SS)。")
    parser.add_argument("-l", "--lang", default="en", help="字幕语言代码 (默认为 'en')。")
    parser.add_argument("--source-dir", default="./source_files", help="存放原始下载文件和LRC的目录。")
    parser.add_argument("--output-dir", default="./final_mp3s", help="存放最终带歌词的MP3文件的目录。")
    parser.add_argument("--no-cleanup", action="store_true", help="保留源目录中的所有中间文件。")
    return parser.parse_args()

def main():
    args = parse_arguments()
    print("--- 流程开始 ---")

    try:
        metadata = get_video_metadata(args.url)
        final_base_name = f"{metadata['title']} [{metadata['id']}]"
        source_base_name = metadata['id']
        os.makedirs(args.source_dir, exist_ok=True)
        os.makedirs(args.output_dir, exist_ok=True)
        final_mp3_path = os.path.join(args.output_dir, f"{final_base_name}.mp3")
        source_mp3_path = os.path.join(args.source_dir, f"{source_base_name}.mp3")
        source_vtt_path = os.path.join(args.source_dir, f"{source_base_name}.{args.lang}.vtt")
        source_lrc_path = os.path.join(args.source_dir, f"{source_base_name}.lrc")
    except Exception as e:
        sys.exit(f"❌ 无法获取视频元数据: {e}")

    if os.path.exists(final_mp3_path):
        print(f"✅ 任务已完成。最终文件已存在于: {final_mp3_path}")
        sys.exit(0)

    if not os.path.exists(source_mp3_path) or not os.path.exists(source_vtt_path):
        print("ℹ️  源文件不存在，开始下载...")
        output_template = os.path.join(args.source_dir, f"{source_base_name}.%(ext)s")
        run_command(["yt-dlp", "-x", "--audio-format", "mp3", "--download-sections", f"*{args.start}-{args.end}", "--write-sub", "--sub-lang", args.lang, "-o", output_template, args.url])
    else:
        print("✅ 检测到已存在的源MP3和VTT文件，跳过下载。")

    if not os.path.exists(source_lrc_path):
        print("\n▶️  将 VTT 转换为 LRC...")
        try:
            start_sec, end_sec = vtt_parse_time(args.start), vtt_parse_time(args.end)
            all_subs = parse_vtt_file(source_vtt_path)
            filtered_subs = filter_subtitles(all_subs, start_sec, end_sec)
            lrc_lines = convert_to_lrc_lines(filtered_subs, offset=start_sec)
            with open(source_lrc_path, 'w', encoding='utf-8') as f:
                f.write(f"[by:youtube_to_mp3_with_lyrics.py]\n" + '\n'.join(lrc_lines))
            print(f"✅ VTT 已成功转换为 {source_lrc_path}")
        except Exception as e:
            sys.exit(f"❌ VTT转换LRC时发生错误: {e}")
    else:
        print("✅ 检测到已存在的LRC文件，跳过转换。")
        
    print("\n▶️  开始嵌入歌词并生成最终文件...")
    try:
        shutil.copy2(source_mp3_path, final_mp3_path)
        audiofile = eyed3.load(final_mp3_path)
        if audiofile is None: raise IOError("eyed3 无法加载最终的MP3文件。")
        
        # 确保tag对象存在
        if audiofile.tag is None:
            audiofile.initTag(version=eyed3.id3.ID3_V2_3)
        
        with open(source_lrc_path, "r", encoding="utf-8") as f:
            lrc_text = f.read()

        # ==========================================================
        #  核心修正点
        # ==========================================================
        # 移除所有现有的歌词以避免重复
        audiofile.tag.lyrics.remove(u'')
        # 使用最简单、最可靠的方式设置歌词，只传递文本
        audiofile.tag.lyrics.set(lrc_text)
        # ==========================================================
        
        audiofile.tag.save(version=eyed3.id3.ID3_V2_3, encoding='utf-8')
        
        print(f"✅ 成功将歌词嵌入并保存到: {final_mp3_path}")
        print(f"   最终文件大小: {os.path.getsize(final_mp3_path) / 1024:.2f} KB")

    except Exception as e:
        sys.exit(f"❌ 嵌入歌词时发生错误: {e}")

    if not args.no_cleanup:
        print("\n▶️  清理源文件...")
        for f_path in [source_mp3_path, source_vtt_path, source_lrc_path]:
            if os.path.exists(f_path):
                try: os.remove(f_path); print(f"🗑️  已删除: {f_path}")
                except OSError as e: print(f"⚠️ 清理文件时出错: {e}")

    print("\n--- 🎉 所有流程已成功完成！ ---")

if __name__ == "__main__":
    main()