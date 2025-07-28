#!/usr/bin/env python3

import os
import subprocess
import sys
import eyed3
import argparse
import re
import shutil
import time
from typing import List, Tuple, Optional, Dict

# ==============================================================================
#  内部 SRT 转 LRC 转换模块
# ==============================================================================
def parse_time(time_str: str) -> float:
    """Parse time string in format HH:MM:SS.mmm or MM:SS.mmm"""
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

def parse_srt_file(srt_path: str) -> List[Tuple[float, float, str]]:
    """Parse SRT file and return list of (start_time, end_time, text) tuples"""
    subtitles = []
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if content.startswith('\ufeff'):
        content = content[1:]
    
    # SRT time pattern: 00:00:20,000 --> 00:00:24,400
    time_pattern = r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})'
    blocks = content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # Skip sequence number (first line)
        time_line = lines[1]
        text_lines = lines[2:]
        
        time_match = re.search(time_pattern, time_line)
        if time_match:
            try:
                start_time_str = time_match.group(1).replace(',', '.')
                end_time_str = time_match.group(2).replace(',', '.')
                start_sec = parse_time(start_time_str)
                end_sec = parse_time(end_time_str)
                text_content = ' '.join(text_lines).strip()
                
                # Remove HTML tags and clean text
                text_content = re.sub(r'<[^>]+>', '', text_content).strip()
                
                if text_content:
                    subtitles.append((start_sec, end_sec, text_content))
            except ValueError as e:
                print(f"警告: 跳过字幕块: {lines[0]} - {e}")
    
    # Sort by start time and remove duplicates
    subtitles = sorted(subtitles, key=lambda x: x[0])
    
    # Simple deduplication for SRT (should be much cleaner than VTT)
    filtered_subtitles = []
    for current in subtitles:
        # Only add if it's not a duplicate of the previous subtitle
        if (not filtered_subtitles or 
            (current[2] != filtered_subtitles[-1][2] and 
             abs(current[0] - filtered_subtitles[-1][0]) > 0.1)):
            filtered_subtitles.append(current)
    
    return filtered_subtitles

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
        if quiet and "--list-subs" in command and (stdout.strip() or stderr.strip()):
             pass
        else:
            print(f"\n❌ 命令执行失败，返回码: {process.returncode}")
            print(f"   命令: {' '.join(command)}")
            print(f"   错误信息: {stderr.strip()}")
            sys.exit(1)
    if not quiet:
        print("✅ 命令执行成功")
    return stdout + stderr

def get_video_metadata(url: str) -> Dict[str, str]:
    print("ℹ️  正在获取视频元数据...")
    title_raw = run_command(["yt-dlp", "--get-title", url], quiet=False).strip()
    title = re.sub(r'[\\/*?:"<>|]', '_', title_raw)
    video_id = run_command(["yt-dlp", "--get-id", url], quiet=False).strip()
    print(f"✅  获取成功: [ID: {video_id}, 标题: {title}]")
    return {"id": video_id, "title": title}

def get_available_subtitles(url: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    print("ℹ️  正在查询可用字幕...")
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        output = run_command(["yt-dlp", "--list-subs", url], quiet=False)
        manual_subs, auto_subs = {}, {}
        lines = output.splitlines()
        parsing_manual, parsing_auto = False, False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for section headers
            if "Available subtitles for" in line:
                parsing_manual, parsing_auto = True, False
                continue
            if "Available automatic captions for" in line:
                parsing_manual, parsing_auto = False, True
                continue
            
            # Skip header lines
            if line.lower().startswith(('language', 'id')) or line.startswith('---'):
                continue
            
            # Parse subtitle lines - format: "lang_code    Language Name    formats"
            # Use regex to match language code at start of line
            match = re.match(r'^([a-zA-Z0-9._-]+)\s+(.+?)\s+(?:vtt|srt|ttml)', line)
            if match:
                lang_code = match.group(1)
                lang_name = match.group(2).strip()
                
                if parsing_manual:
                    manual_subs[lang_code] = lang_name
                elif parsing_auto:
                    auto_subs[lang_code] = lang_name
        
        if manual_subs or auto_subs:
            print("✅ 字幕查询成功。")
            return manual_subs, auto_subs

        if attempt < max_retries - 1:
            print(f"⚠️  未找到任何字幕。可能是临时问题，将在 {retry_delay} 秒后重试 ({attempt + 1}/{max_retries})...")
            time.sleep(retry_delay)
        else:
            print("⚠️  多次尝试后仍未获取到字幕列表。")
    
    return {}, {}

def print_subtitle_lists(manual_subs: Dict[str, str], auto_subs: Dict[str, str]):
    def print_in_columns(title: str, subs: Dict[str, str]):
        if not subs:
            print(f"  {title} 无可用的字幕。")
            return
        print(f"  {title}")
        items = [f"{code}: {name}" for code, name in sorted(subs.items())]
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        max_len = max(len(item) for item in items) if items else 0
        col_width = max_len + 4
        num_cols = max(1, terminal_width // col_width)
        for i in range(0, len(items), num_cols):
            row_items = items[i:i+num_cols]
            line = "".join(item.ljust(col_width) for item in row_items)
            print(f"      {line}")
    print("--- 字幕可用性详情 ---")
    print_in_columns("📖 可用的手动字幕:", manual_subs)
    print("")
    print_in_columns("🤖 可用的自动字幕:", auto_subs)
    print("------------------------")

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
        source_srt_path = os.path.join(args.source_dir, f"{source_base_name}.{args.lang}.srt")
        source_lrc_path = os.path.join(args.source_dir, f"{source_base_name}.lrc")
    except Exception as e:
        sys.exit(f"❌ 无法获取视频元数据: {e}")

    if os.path.exists(final_mp3_path):
        print(f"✅ 任务已完成。最终文件已存在于: {final_mp3_path}")
        sys.exit(0)

    manual_subs, auto_subs = get_available_subtitles(args.url)
    
    use_auto_sub = False
    if args.lang in manual_subs:
        print(f"✅ 找到请求的手动字幕: '{args.lang}' ({manual_subs[args.lang]})")
    elif args.lang in auto_subs:
        print(f"\n⚠️  警告: 未找到手动字幕 '{args.lang}'。将使用找到的自动生成字幕替代。")
        print_subtitle_lists(manual_subs, auto_subs)
        use_auto_sub = True
    else:
        print(f"\n❌ 错误: 找不到请求的字幕语言 '{args.lang}'。")
        if not manual_subs and not auto_subs:
            print("   原因: 无法从 YouTube 获取任何可用的字幕列表。这可能是临时的网络问题或视频限制。请稍后重试。")
        else:
             print_subtitle_lists(manual_subs, auto_subs)
        sys.exit(1)

    if not os.path.exists(source_mp3_path) or not os.path.exists(source_srt_path):
        print("\nℹ️  源文件不存在，开始下载...")
        output_template = os.path.join(args.source_dir, f"{source_base_name}.%(ext)s")
        dl_command = ["yt-dlp", "-x", "--audio-format", "mp3"]
        if use_auto_sub:
            dl_command.extend(["--write-auto-sub", "--sub-lang", args.lang, "--sub-format", "srt"])
        else:
            dl_command.extend(["--write-sub", "--sub-lang", args.lang, "--sub-format", "srt"])
        dl_command.extend(["--download-sections", f"*{args.start}-{args.end}", "-o", output_template, args.url])
        run_command(dl_command)
    else:
        print("\n✅ 检测到已存在的源MP3和SRT文件，跳过下载。")

    if not os.path.exists(source_srt_path):
        sys.exit(f"❌ 错误: 字幕文件 {source_srt_path} 未能成功下载。请检查语言代码和网络连接。")
    if not os.path.exists(source_lrc_path):
        print("\n▶️  将 SRT 转换为 LRC...")
        try:
            start_sec, end_sec = parse_time(args.start), parse_time(args.end)
            all_subs = parse_srt_file(source_srt_path)
            filtered_subs = filter_subtitles(all_subs, start_sec, end_sec)
            lrc_lines = convert_to_lrc_lines(filtered_subs, offset=start_sec)
            with open(source_lrc_path, 'w', encoding='utf-8') as f: f.write(f"[by:youtube_to_mp3_with_lyrics.py]\n" + '\n'.join(lrc_lines))
            print(f"✅ SRT 已成功转换为 {source_lrc_path}")
        except Exception as e: sys.exit(f"❌ SRT转换LRC时发生错误: {e}")
    else:
        print("✅ 检测到已存在的LRC文件，跳过转换。")
    print("\n▶️  开始嵌入歌词并生成最终文件...")
    try:
        shutil.copy2(source_mp3_path, final_mp3_path)
        audiofile = eyed3.load(final_mp3_path)
        if audiofile is None: raise IOError("eyed3 无法加载最终的MP3文件。")
        if audiofile.tag is None: audiofile.initTag(version=eyed3.id3.ID3_V2_3)
        with open(source_lrc_path, "r", encoding="utf-8") as f: lrc_text = f.read()
        audiofile.tag.lyrics.remove(u'')
        audiofile.tag.lyrics.set(lrc_text)
        audiofile.tag.save(version=eyed3.id3.ID3_V2_3, encoding='utf-8')
        print(f"✅ 成功将歌词嵌入并保存到: {final_mp3_path}")
        print(f"   最终文件大小: {os.path.getsize(final_mp3_path) / 1024:.2f} KB")
    except Exception as e: sys.exit(f"❌ 嵌入歌词时发生错误: {e}")
    if not args.no_cleanup:
        print("\n▶️  清理源文件...")
        for f_path in [source_mp3_path, source_srt_path, source_lrc_path]:
            if os.path.exists(f_path):
                try: os.remove(f_path); print(f"🗑️  已删除: {f_path}")
                except OSError as e: print(f"⚠️ 清理文件时出错: {e}")
    print("\n--- 🎉 所有流程已成功完成！ ---")

if __name__ == "__main__":
    main()