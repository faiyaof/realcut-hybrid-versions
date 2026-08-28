# -*- coding: utf-8 -*-
"""
步骤4后处理：开盒检测 + 短片补位
=====================================
在 F1 步骤4-切割排序.py 执行完成后运行。
读取 step4_segments.json + asr_result.json，检测是否有开盒内容被丢弃。
如果最终视频时长 < 15s，自动补开盒画面到开头 + 配金句音频。

用法:
  python 步骤4后-开盒补位.py <草稿路径> [--no-open]
"""
import json, sys, os, shutil, subprocess, copy
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CLIP_LIB = Path(r"C:\Users\JT\Documents\剪辑\爆点+金句 素材库")
MAX_VIDEO_DURATION_MS = 30000  # 成片最长不超过30秒

def uid():
    import uuid
    return str(uuid.uuid4()).upper()

def get_audio_duration_ms(fp):
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(fp)],
                          capture_output=True, text=True, timeout=10)
        return int(float(r.stdout.strip()) * 1000) if r.stdout.strip() else 0
    except:
        return 0

def scan_folder_clips(folder_path):
    folder = Path(folder_path)
    return sorted([f for f in folder.iterdir() if f.suffix.lower() == ".mp3"]) if folder.exists() else []

def pick_best_clip(clips, asr_texts):
    """简单选取：用第一个可用素材"""
    if not clips:
        return None
    return clips[0]

def main(dp_str, auto_open=True):
    dp = Path(dp_str)
    seg_path = dp / "step4_segments.json"
    asr_path = dp / "asr_result.json"
    dc_path = dp / "draft_content.json"

    if not seg_path.exists():
        print("[跳过] step4_segments.json 不存在，请先执行步骤4")
        return
    if not asr_path.exists():
        print("[跳过] asr_result.json 不存在")
        return
    if not dc_path.exists():
        print("[跳过] draft_content.json 不存在")
        return

    with open(seg_path, "r", encoding="utf-8") as f:
        segs = json.load(f)
    with open(asr_path, "r", encoding="utf-8") as f:
        asr = json.load(f)
    with open(dc_path, "r", encoding="utf-8") as f:
        draft = json.load(f)

    sentences = asr.get("sentences", [])

    # 计算当前总时长
    total_dur_ms = sum(s.get("src_dur_ms", 0) for s in segs)
    print(f"当前总时长: {total_dur_ms / 1000:.1f}s")

    # 找开盒句：在 ASR 全量句子中搜索关键词，且不在已用段中
    kai_kw = ["开箱", "开盒子", "拆包装", "打开盒子", "盒子打开", "拆开包装", "包装箱", "包装盒"]
    used_texts = {s.get("text", "")[:20] for s in segs}
    kai_candidates = []
    for s in sentences:
        t = s.get("text", "")
        if any(k in t for k in kai_kw):
            if t[:20] not in used_texts:
                kai_candidates.append(s)

    if not kai_candidates:
        print("[跳过] 未检测到开盒内容")
        return

    print(f"检测到 {len(kai_candidates)} 条开盒句（未使用）")
    kai_s = kai_candidates[0]
    kai_dur = kai_s["end"] - kai_s["start"]
    kai_dur_ms = kai_dur

    if total_dur_ms >= 15000:
        print(f"总时长 {total_dur_ms/1000:.1f}s >= 15s，开盒段丢弃，不做处理")
        return

    # 总时长 < 15s → 补开盒到开头
    print(f"\n总时长 {total_dur_ms/1000:.1f}s < 15s，补开盒画面到开头")

    # 找金句音频
    jinju_clips = scan_folder_clips(CLIP_LIB / "金句")
    jinju_file = None
    jinju_dur_ms = 0
    if jinju_clips:
        jinju_file = pick_best_clip(jinju_clips, sentences)
        jinju_dur_ms = get_audio_duration_ms(jinju_file)
        print(f"  配金句: {jinju_file.name if jinju_file else 'N/A'} ({jinju_dur_ms/1000:.1f}s)")

    # 获取视频素材信息用于画面复制
    video_mats = draft.get("materials", {}).get("videos", [])
    video_path = None
    for vm in video_mats:
        p = vm.get("path", "")
        if p and "video_only" in p.lower():
            video_path = p
            break
    if not video_path and video_mats:
        video_path = video_mats[0].get("path", "")
    
    if not video_path:
        print("[错误] 找不到视频素材路径")
        return
    
    # 修复占位符路径
    draft_placeholder = ""
    for v in video_mats:
        p = v.get("path", "")
        if "##_draftpath_placeholder" in p:
            draft_placeholder = p[:p.index("##/") + 3]
            break
    if draft_placeholder:
        video_path = video_path.replace("##_draftpath_placeholder", dp.as_posix())

    # 更新 video track 段：把开盒段画面加进去
    video_track = None
    for t in draft["tracks"]:
        if t["type"] == "video":
            video_track = t
            break

    if not video_track:
        print("[错误] 找不到视频轨道")
        return

    # 获取当前总时长（微秒）
    tl_us = draft.get("duration", 0)
    if not tl_us and video_track.get("segments"):
        last = video_track["segments"][-1]
        tt = last.get("target_timerange", {})
        tl_us = tt.get("start", 0) + tt.get("duration", 0)

    # 计算开盒段的时间（微秒）
    # 开盒补位最多只能补到30秒，不能因为补位把成片拉长到30秒以上
    current_total_us = int(tl_us) if tl_us else int(total_dur_ms * 1000)
    available_us = max(0, MAX_VIDEO_DURATION_MS * 1000 - current_total_us)
    if available_us < 100000:
        print(f"可用补位时长不足0.1s，开盒段不做处理")
        return
    kai_dur_us = min(kai_dur_ms * 1000, available_us)
    jinju_dur_us = min(jinju_dur_ms * 1000, max(0, available_us - kai_dur_us))
    if jinju_dur_us < 100000:
        jinju_file = None
        jinju_dur_us = 0
        print("  30秒上限内没有足够金句音频空间，仅保留开盒画面")

    # 原有的所有视频段需要后移
    offset_us = kai_dur_us + jinju_dur_us
    old_video_segs = video_track.get("segments", [])
    for seg in old_video_segs:
        tt = seg.get("target_timerange", {})
        if tt:
            tt["start"] = tt.get("start", 0) + offset_us

    # 找到原始视频素材中对应开盒段的区间
    src_start_us = int(kai_s["start"] * 1000)
    src_end_us = int(kai_s["end"] * 1000)
    # 开盒目标时长受30秒上限约束，不能直接照搬原句时长
    src_dur_us = kai_dur_us

    # 创建开盒视频段
    from _utils import write_draft
    import shutil, uuid

    # 开盒段直接在视频轨道前插两个新段
    new_video_segs = []

    # 段1：开盒画面
    kai_mat_id = uid()
    # 用第一个视频素材
    first_vid = video_mats[0] if video_mats else None
    video_mat_id = first_vid["id"] if first_vid else uid()
    vid_duration = first_vid.get("duration", tl_us) if first_vid else tl_us

    kai_seg = {
        "id": uid(),
        "material_id": video_mat_id,
        "target_timerange": {"duration": src_dur_us, "start": 0},
        "source_timerange": {"duration": src_dur_us, "start": src_start_us},
        "speed": 1,
        "volume": 1,
        "visible": True,
        "extra_material_refs": []
    }
    new_video_segs.append(kai_seg)

    # 段2：如果配了金句，用开盒画面持续到金句结束
    if jinju_file and jinju_dur_us > 0:
        jinju_video_seg = copy.deepcopy(kai_seg)
        jinju_video_seg["id"] = uid()
        jinju_video_seg["target_timerange"] = {"duration": jinju_dur_us, "start": src_dur_us}
        # source 也延长到金句结束（画面延续开盒最后1帧）
        # 用 re-source 到开盒段末尾附近（最后1帧循环）
        jinju_end_src = min(src_end_us + jinju_dur_us, vid_duration)
        jinju_video_seg["source_timerange"] = {"duration": jinju_dur_us, "start": max(0, src_end_us - 50000)}  # 最后50ms循环
        new_video_segs.append(jinju_video_seg)

    # 加上原有的视频段
    new_video_segs.extend(old_video_segs)
    video_track["segments"] = new_video_segs

    # 添加金句音频
    if jinju_file:
        jinju_name = f"voiceover_kaikai_{jinju_file.stem}.mp3"
        jinju_dest = dp / jinju_name
        shutil.copy2(str(jinju_file), str(jinju_dest))
        
        jinju_mat_id = uid()
        draft["materials"]["audios"].append({
            "id": jinju_mat_id,
            "duration": jinju_dur_us,
            "name": jinju_name,
            "path": str(jinju_dest),
            "type": "sound"
        })
        
        # 找音频轨道或创建
        audio_track = None
        for t in draft["tracks"]:
            if t["type"] == "audio":
                audio_track = t
                break
        if not audio_track:
            audio_track = {"type": "audio", "flag": 0, "is_main_track": False, "attribute": 0, "id": uid(), "segments": []}
            draft["tracks"].append(audio_track)

        # 金句音频段插在最前面
        jinju_audio_seg = {
            "id": uid(),
            "material_id": jinju_mat_id,
            "target_timerange": {"duration": jinju_dur_us, "start": src_dur_us},
            "source_timerange": {"duration": jinju_dur_us, "start": 0},
            "speed": 1,
            "volume": 0.3,
            "visible": True,
            "extra_material_refs": []
        }
        # 先插入到音频轨道开头
        existing_audio = audio_track.get("segments", [])
        audio_track["segments"] = [jinju_audio_seg] + existing_audio
    
    # 更新总时长
    new_total = current_total_us + offset_us
    draft["duration"] = new_total
    for vm in draft.get("materials", {}).get("videos", []):
        vm["duration"] = new_total

    # 保存
    from _utils import write_draft
    write_draft(dp, draft)
    
    print(f"\n完成！开盒段已插入到开头（{src_dur_us/1000000:.1f}s）")
    if jinju_file:
        print(f"      金句音频已叠加（{jinju_dur_us/1000000:.1f}s @ 音量0.3）")
    print(f"      新总时长: {new_total/1000000:.1f}s")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    auto_open = "--no-open" not in sys.argv
    main(sys.argv[1], auto_open=auto_open)
