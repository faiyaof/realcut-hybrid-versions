#!/usr/bin/env python3
"""
步骤6：画面匹配 v9 — 1s全视频扫描+缓存+质量分配
=================================================
核心逻辑（铁律）：
1. ffmpeg fps=1 一次提取全视频帧（1s间隔）
2. 千问逐帧判断：展示中/丢掉/其他商品/开盒/空手
3. 结果缓存到 _frame_full_cache_1s.json，下次直接加载不重扫
4. 只用纯展示区间，开盒/剪标签/其他商品画面不进成片
5. 相邻段源区间不重叠，同一源区间最多使用2次且自动镜像

用法: python "步骤6-画面匹配.py" <草稿路径> [--no-open]
"""

import json
import sys
import os
import uuid
import shutil
import base64
import subprocess
import time
import io
import glob

from _utils import write_draft
from _video_assign import assign_video_sources

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path


def uid():
    return str(uuid.uuid4()).upper()


def find_source_video(draft_path):
    for fname in os.listdir(draft_path):
        fpl = fname.lower()
        if any(fpl.endswith(ext) for ext in ('.mp4', '.mkv', '.mov', '.avi', '.flv')):
            fp = os.path.join(str(draft_path), fname)
            if os.path.isfile(fp) and os.path.getsize(fp) > 1024:
                if not fpl.endswith('video_only.mp4'):
                    return fp
    for fname in os.listdir(draft_path):
        if fname.lower().endswith(('.mp4', '.mkv')):
            return os.path.join(str(draft_path), fname)
    return None


def get_video_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0


def get_frame_actions(src_video, draft_path):
    """获取全视频帧动作数据 (1s间隔)。缓存到文件避免重复扫描。"""
    cache_path = os.path.join(draft_path, '_frame_full_cache_1s.json')

    # 步骤4重跑后自动失效缓存
    seg_meta = os.path.join(draft_path, 'step4_segments.json')
    if os.path.exists(cache_path) and os.path.exists(seg_meta):
        if os.path.getmtime(seg_meta) > os.path.getmtime(cache_path):
            os.remove(cache_path)
            print('[Keng6] step4_segments.json updated -> cache invalidated')

    if os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    print('首次全视频扫描 1s间隔 (结果将缓存)...')
    frame_dir = os.path.join(draft_path, '_frame_s4')
    if os.path.exists(frame_dir):
        shutil.rmtree(frame_dir, ignore_errors=True)
    os.makedirs(frame_dir)

    subprocess.run(['ffmpeg', '-y', '-i', src_video, '-vf', 'fps=1',
                    '-q:v', '2', '-hide_banner', '-loglevel', 'error',
                    os.path.join(frame_dir, 'f_%04d.png')],
                   capture_output=True)

    frames = sorted(glob.glob(os.path.join(frame_dir, '*.png')))
    print('  帧数:', len(frames))

    actions = {}
    import threading
    _TIMEOUT_S = 30  # 单帧VL调用超时（秒），防卡死

    def _call_vl(fp):
        result = {}

        def worker():
            try:
                with open(fp, 'rb') as f:
                    img_b64 = base64.b64encode(f.read()).decode('utf-8')
                from dashscope import MultiModalConversation
                resp = MultiModalConversation.call(
                    model='qwen-vl-plus',
                    messages=[{'role': 'user', 'content': [
                        {'image': 'data:image/png;base64,' + img_b64},
                        {'text': '只看画面，主播有没有举起/展示这件衣服？详细判断：展示中(手举着/拿着展示衣服), 丢掉(放下/丢下衣服), 其他商品(出现其他商品/其他品类), 开盒(在打开包装盒), 空手(没拿衣服/空手比划)。只回答其中一个：展示中, 丢掉, 其他商品, 开盒, 空手'}
                    ]}],
                    result_format='message'
                )
                txt = ''
                if hasattr(resp, 'status_code') and resp.status_code == 200:
                    c = resp.output.choices[0].message.content
                    txt = c[0]['text'] if isinstance(c, list) and len(c) > 0 and isinstance(c[0], dict) else str(c)
                result['txt'] = txt
            except Exception as e:
                result['err'] = str(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(_TIMEOUT_S)
        if t.is_alive():
            return ''
        if 'err' in result:
            return ''
        return result.get('txt', '')

    for i, fp in enumerate(frames):
        fname = os.path.basename(fp)
        fnum = int(fname.split('_')[1].split('.')[0])
        ms = fnum * 1000
        key = str(ms)

        txt = _call_vl(fp)
        actions[key] = txt
        print('  ' + format(ms / 1000, '.2f') + 's: ' + txt + ' (' + str(i + 1) + '/' + str(len(frames)) + ')')

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(actions, f, ensure_ascii=False)
    print('缓存已保存到 _frame_full_cache_1s.json')

    if os.path.exists(frame_dir):
        shutil.rmtree(frame_dir, ignore_errors=True)
    return actions


def match_video(draft_path, auto_open=True):
    draft_path = Path(draft_path)
    dc_path = draft_path / 'draft_content.json'
    seg_meta_path = draft_path / 'step4_segments.json'
    if not dc_path.exists():
        print('draft_content.json 不存在')
        return
    if not seg_meta_path.exists():
        print('step4_segments.json 不存在')
        return

    src_video = find_source_video(draft_path)
    if not src_video:
        print('未找到源视频')
        return
    print('源视频:', os.path.basename(src_video))

    video_file_dur_s = get_video_dur(src_video)
    video_file_dur_us = int(video_file_dur_s * 1e6) if video_file_dur_s > 0 else 22000000
    print('视频文件时长:', video_file_dur_s, 's')

    with open(dc_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)
    with open(seg_meta_path, 'r', encoding='utf-8') as f:
        seg_meta = json.load(f)

    audio_track = None
    for t in draft['tracks']:
        if t['type'] == 'audio':
            audio_track = t
            break
    if not audio_track or not audio_track['segments']:
        print('未找到音频段')
        return

    asegs = audio_track['segments']
    video_id = draft['materials']['videos'][0]['id']

    api_available = True
    try:
        import dashscope
        if not os.environ.get('DASHSCOPE_API_KEY', ''):
            api_available = False
            print('API Key not set, skip visual check')
    except ImportError:
        api_available = False
        print('dashscope not installed, skip visual check')

    frame_actions = {}
    if api_available:
        frame_actions = get_frame_actions(src_video, str(draft_path))
    else:
        print('跳过画面分析，使用原位置分配')
        frame_actions = {}

    print('\nPhase 2: 质量画面分配...')
    sources = assign_video_sources(asegs, seg_meta, frame_actions, video_file_dur_us)

    existing_video_segs = draft['tracks'][0].get('segments', [])
    video_segs = []
    target_start = 0
    for i, seg in enumerate(asegs):
        audio_dur = seg['target_timerange']['duration']
        src_start, flip_h = sources[i]
        material_id = video_id
        if i < len(seg_meta) and seg_meta[i].get('source') == 'mirror':
            # Preserve the pre-rendered mirror/reverse clip created by mirror_通用.
            if i < len(existing_video_segs):
                material_id = existing_video_segs[i].get('material_id', video_id)
            src_start = 0
            flip_h = False
        sid = uid()
        seg_data = {
            "caption_info": None, "cartoon": None,
            "clip": {"alpha": 1, "flip": {"horizontal": flip_h, "vertical": False},
                     "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}},
            "common_keyframes": [], "enable_adjust": False,
            "enable_color_correct_adjust": False, "enable_color_curves": False,
            "enable_color_match_adjust": False, "enable_color_wheels": False,
            "enable_lut": False, "enable_smart_color_adjust": False,
            "extra_material_refs": [], "group_id": "", "hdr_settings": "",
            "id": sid, "intensifies_audio": None,
            "is_placeholder": False, "is_tone_modify": False,
            "keyframe_refs": [], "last_nonzero_volume": 1,
            "material_id": material_id, "render_index": 0,
            "responsive_layout": 0, "reverse": False,
            "source_timerange": {"duration": audio_dur, "start": src_start},
            "speed": 1.0,
            "target_timerange": {"duration": audio_dur, "start": target_start},
            "template_id": "", "template_scene": "",
            "track_attribute": 1, "track_render_index": 0,
            "uniform_scale": 1, "visible": True, "volume": 1
        }
        video_segs.append(seg_data)

        src_e = (src_start + audio_dur) / 1e6
        tgt_s = target_start / 1e6
        tgt_e = (target_start + audio_dur) / 1e6
        print('    tgt[' + format(tgt_s, '.2f') + 's-' + format(tgt_e, '.2f') +
              's] <- src[' + format(src_start / 1e6, '.3f') + 's-' +
              format(src_e, '.3f') + 's]' + (' [mirror]' if flip_h else ''))
        target_start += audio_dur

    if len(video_segs) < len(asegs):
        print('严重错误：video_segs({}) < asegs({})，终止写入'.format(len(video_segs), len(asegs)))
        sys.exit(1)

    bak_path = str(dc_path) + '.bak'
    shutil.copy2(str(dc_path), bak_path)
    print('已备份: ' + bak_path)

    draft['tracks'][0]['segments'] = video_segs
    draft['duration'] = target_start
    write_draft(draft_path, draft)

    print('\n画面匹配完成！')
    print('  视频段:', len(video_segs))

    if auto_open:
        jy_path = os.environ.get('REALCUT_JIANYING_EXE', r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe')
        script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')
        open_py = os.path.join(script_dir, 'open_draft.py')
        print('打开剪映验证...')
        subprocess.run(['taskkill', '/f', '/im', 'JianyingPro.exe'], capture_output=True, text=True)
        subprocess.Popen([jy_path], shell=True)
        time.sleep(20)
        subprocess.run(['python', open_py, os.path.basename(str(draft_path))], capture_output=True, text=True)
        print('已打开草稿【' + os.path.basename(str(draft_path)) + '】请查看')
    else:
        print('(Skipping CapCut auto-open, --no-open)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    auto_open = '--no-open' not in sys.argv
    match_video(sys.argv[1], auto_open=auto_open)
