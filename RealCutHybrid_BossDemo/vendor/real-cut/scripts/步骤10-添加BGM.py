from _utils import write_draft, resolve_template_dir, ensure_utf8_stdout
"""
步骤10：添加BGM — 从草稿模板挑选BGM或自定义本地音频，音量-15dB，自动匹配画面/音频时长
用法: python "步骤10-添加BGM.py" <草稿路径> [--bgm 6|7|8|9|10|11|12|13]
"""

import json, sys, uuid, shutil, copy, argparse, subprocess, io
from pathlib import Path

ensure_utf8_stdout()

# 模板草稿：优先用当前风格模板，找不到回退 com.lveditor.draft/草稿
TEMPLATE, _tmpl_name = resolve_template_dir()
if TEMPLATE is None:
    TEMPLATE = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\草稿')
FALLBACK_BGM_TMPL = Path(r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\草稿')

def _supports_default_bgm(tmpl_dir):
    dc = tmpl_dir / 'draft_content.json'
    if not dc.exists():
        return False
    try:
        d = json.load(open(dc, encoding='utf-8'))
        audio_tracks = [t for t in d.get('tracks', []) if t.get('type') == 'audio' and t.get('segments')]
        return len(audio_tracks) >= 5
    except Exception:
        return False

if not _supports_default_bgm(TEMPLATE):
    if (FALLBACK_BGM_TMPL / 'draft_content.json').exists():
        print(f'风格模板缺少默认BGM素材，BGM改用: {FALLBACK_BGM_TMPL.name}')
        TEMPLATE = FALLBACK_BGM_TMPL

# 自定义 BGM 音频文件（用户额外添加）
CUSTOM_BGM_FILES = {
    11: {'path': r'D:\工作空间\精剪\音频\悠闲.MP3',  'name': '悠闲'},
    12: {'path': r'D:\工作空间\精剪\音频\烟雨入画.MP3', 'name': '烟雨入画'},
    13: {'path': r'D:\工作空间\精剪\音频\爱的魔法.MP3', 'name': '爱的魔法'},
}

BGM_NAMES = {
    6: '水仙', 7: 'Shadowed Whisper', 8: 'Skipping Pebbles',
    9: '慵懒穿搭分享', 10: '时尚惬意驰放Positive Dreamy',
    11: '悠闲', 12: '烟雨入画', 13: '爱的魔法',
}


def uid():
    return str(uuid.uuid4()).upper()


def get_timeline_duration(draft):
    """计算实际时间线总长（仅视频/主音频轨道，不含BGM/音效）"""
    max_end = 0
    for t in draft.get('tracks', []):
        if t['type'] == 'audio' and len(t.get('segments',[])) == 1 and t.get('name','') != '__sfx__':
            continue
        if t.get('name','') == '__sfx__':
            continue
        for seg in t.get('segments', []):
            tr = seg.get('target_timerange', {})
            end = tr.get('start', 0) + tr.get('duration', 0)
            if end > max_end:
                max_end = end
    return max_end


def get_audio_duration(filepath):
    """用 ffprobe 获取音频文件时长（微秒）"""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(filepath)],
            capture_output=True
        )
        info = json.loads(r.stdout.decode('utf-8', 'ignore'))
        dur_sec = float(info['format']['duration'])
        return int(dur_sec * 1_000_000)
    except Exception as e:
        print(f'获取音频时长失败: {e}')
        return None


def create_custom_audio_material(filepath, name, draft):
    """为自定义BGM创建音频素材并加入草稿"""
    audio_id = uid()
    duration = get_audio_duration(filepath)
    if not duration:
        return None

    audio_material = {
        "id": audio_id,
        "local_material_id": audio_id,
        "name": name,
        "type": "audio",
        "path": str(filepath),
        "duration": duration,
        "category_name": "自定义BGM",
        "volume": 1.0,
    }
    draft['materials']['audios'].append(audio_material)
    print(f'  自定义BGM素材已创建: {name} ({duration/1000000:.1f}s)')
    return audio_id, duration


def create_bgm_segment(mat_id, duration_us, total_dur_us):
    """创建BGM轨道片段"""
    use_dur = min(total_dur_us, duration_us)
    return {
        "caption_info": None, "cartoon": False, "clip": None,
        "common_keyframes": [], "enable_adjust": False,
        "enable_color_correct_adjust": False, "enable_color_curves": True,
        "enable_color_match_adjust": False, "enable_color_wheels": True,
        "enable_lut": False, "enable_smart_color_adjust": False,
        "extra_material_refs": [], "group_id": "", "hdr_settings": None,
        "id": uid(), "intensifies_audio": False,
        "is_placeholder": False, "is_tone_modify": False,
        "keyframe_refs": [], "last_nonzero_volume": 1,
        "material_id": mat_id, "render_index": 0,
        "responsive_layout": {
            "enable": False, "horizontal_pos_layout": 0,
            "size_layout": 0, "target_follow": "",
            "vertical_pos_layout": 0
        },
        "reverse": False,
        "source_timerange": {"duration": use_dur, "start": 0},
        "speed": 1,
        "target_timerange": {"duration": use_dur, "start": 0},
        "template_id": "", "template_scene": "default",
        "track_attribute": 0, "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0},
        "visible": True, "volume": 0.177827941  # -15dB
    }, use_dur


def add_bgm(draft_path, bgm_track_idx=10):
    """
    bgm_track_idx: 轨道索引
      6 → 水仙（模板）
      7 → Shadowed Whisper（模板）
      8 → Skipping Pebbles（模板）
      9 → 慵懒穿搭分享（模板）
     10 → 时尚惬意驰放Positive Dream（模板，默认）
     11 → 悠闲（自定义）
     12 → 烟雨入画（自定义）
     13 → 爱的魔法（自定义）
    """
    dp = Path(draft_path)
    with open(dp / 'draft_content.json', 'r', encoding='utf-8') as f:
        draft = json.load(f)

    total_dur = get_timeline_duration(draft)
    bgm_name = BGM_NAMES.get(bgm_track_idx, f'轨道{bgm_track_idx}')
    print(f'BGM 选择: {bgm_track_idx} ({bgm_name})')
    print(f'BGM 模板: {TEMPLATE}')
    print(f'时间线总长: {total_dur/1000000:.1f}s')

    # ── 自定义BGM（11-13）──
    if bgm_track_idx in CUSTOM_BGM_FILES:
        info = CUSTOM_BGM_FILES[bgm_track_idx]
        filepath = Path(info['path'])
        if not filepath.exists():
            print(f'自定义BGM文件不存在: {filepath}')
            return False

        result = create_custom_audio_material(filepath, info['name'], draft)
        if not result:
            return False
        mat_id, bgm_dur = result
        seg_data, use_dur = create_bgm_segment(mat_id, bgm_dur, total_dur)

    # ── 模板BGM（6-10）──
    else:
        with open(TEMPLATE / 'draft_content.json', 'r', encoding='utf-8') as f:
            tmpl = json.load(f)

        if bgm_track_idx < 0 or bgm_track_idx >= len(tmpl['tracks']):
            print(f'BGM 轨道索引 {bgm_track_idx} 越界，回退到默认 10')
            bgm_track_idx = 10
            bgm_name = BGM_NAMES[10]

        bgm_track = tmpl['tracks'][bgm_track_idx]
        bgm_seg = bgm_track['segments'][0]
        bgm_mat_id = bgm_seg['material_id']

        bgm_audio = None
        for a in tmpl['materials']['audios']:
            if a['id'] == bgm_mat_id:
                bgm_audio = copy.deepcopy(a)
                break

        if not bgm_audio:
            print('未找到 BGM 素材')
            return False

        bgm_audio['id'] = uid()
        bgm_audio['local_material_id'] = bgm_audio['id']
        draft['materials']['audios'].append(bgm_audio)

        bgm_dur = bgm_audio.get('duration', total_dur)
        use_dur = min(total_dur, bgm_dur)

        seg_data = {
            "caption_info": None, "cartoon": False, "clip": None,
            "common_keyframes": [], "enable_adjust": False,
            "enable_color_correct_adjust": False, "enable_color_curves": True,
            "enable_color_match_adjust": False, "enable_color_wheels": True,
            "enable_lut": False, "enable_smart_color_adjust": False,
            "extra_material_refs": [], "group_id": "", "hdr_settings": None,
            "id": uid(), "intensifies_audio": False,
            "is_placeholder": False, "is_tone_modify": False,
            "keyframe_refs": [], "last_nonzero_volume": 1,
            "material_id": bgm_audio['id'], "render_index": 0,
            "responsive_layout": {
                "enable": False, "horizontal_pos_layout": 0,
                "size_layout": 0, "target_follow": "",
                "vertical_pos_layout": 0
            },
            "reverse": False,
            "source_timerange": {"duration": use_dur, "start": 0},
            "speed": 1,
            "target_timerange": {"duration": use_dur, "start": 0},
            "template_id": "", "template_scene": "default",
            "track_attribute": 0, "track_render_index": 0,
            "uniform_scale": {"on": True, "value": 1.0},
            "visible": True, "volume": 0.177827941
        }

    print(f'BGM 原长: {bgm_dur/1000000:.1f}s')
    print(f'实际使用: {use_dur/1000000:.1f}s')

    # 添加到新轨道
    draft['tracks'].append({
        "attribute": 0, "flag": 0, "id": uid(),
        "is_default_name": True, "name": "",
        "segments": [seg_data], "type": "audio"
    })

    draft['duration'] = total_dur
    write_draft(dp, draft)

    print(f'BGM 已添加: {bgm_name}')
    print(f'  音量: -15dB (0.178)')
    print(f'  时长: {use_dur/1000000:.1f}s (与画面/音频一致)')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='添加 BGM')
    parser.add_argument('draft_path', help='草稿目录路径')
    parser.add_argument('--bgm', type=int, default=10, choices=[6,7,8,9,10,11,12,13],
                        help='BGM: 6=水仙, 7=Shadowed Whisper, 8=Skipping Pebbles, 9=慵懒穿搭分享, 10=Positive Dreamy(默认), 11=悠闲, 12=烟雨入画, 13=爱的魔法')
    args = parser.parse_args()
    success = add_bgm(args.draft_path, args.bgm)
    sys.exit(0 if success else 1)
