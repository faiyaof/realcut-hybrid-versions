from _utils import write_draft
"""
步骤2：分离音频 - 从视频中提取音频，生成无音轨视频 + 独立音频

用法:
  python "步骤2-分离音频.py" <草稿路径>

示例:
  python "步骤2-分离音频.py" "C:/Users/JT/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/002_5X3138K"
"""

import json, os, sys, subprocess, uuid, shutil, time
from pathlib import Path

def run_ffmpeg(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'ffmpeg 错误: {result.stderr}')
        return False
    return True

def separate_audio(draft_path, auto_open=True):
    draft_path = Path(draft_path)
    if not draft_path.exists():
        print(f'草稿目录不存在: {draft_path}')
        return

    dc_path = draft_path / 'draft_content.json'
    if not dc_path.exists():
        print(f'draft_content.json 不存在')
        return

    with open(dc_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    videos = data['materials'].get('videos', [])
    if not videos:
        print('没有找到视频素材')
        return

    # Find the source video file in draft folder
    for v in videos:
        path_str = v.get('path', '')
        fname = os.path.basename(path_str.replace('\\', '/'))
        src = draft_path / fname
        if src.exists():
            break
    else:
        print('在草稿目录中没有找到对应的视频文件')
        return

    if not v.get('has_audio', True):
        print('视频已经分离过音频，跳过')
        return

    print(f'源视频: {src.name}')
    print(f'分离音频中...')

    # 1. Extract audio -> audio.mp3
    audio_mp3 = draft_path / 'audio.mp3'
    if not audio_mp3.exists():
        ok = run_ffmpeg([
            'ffmpeg', '-y', '-i', str(src),
            '-vn', '-acodec', 'libmp3lame', str(audio_mp3)
        ])
        if not ok:
            return
    else:
        print('  audio.mp3 已存在，跳过提取')

    # Get audio duration
    r = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                        '-of','csv=p=0',str(audio_mp3)], capture_output=True, text=True)
    audio_dur_s = float(r.stdout.strip()) if r.stdout.strip() else 0
    audio_dur_us = int(audio_dur_s * 1000000)

    # 2. Create video without audio -> video_only.mp4
    video_only = draft_path / 'video_only.mp4'
    if not video_only.exists():
        print(f'生成无音轨视频...')
        ok = run_ffmpeg([
            'ffmpeg', '-y', '-i', str(src),
            '-c:v', 'copy', '-an', str(video_only)
        ])
        if not ok:
            return
    else:
        print('  video_only.mp4 已存在，跳过')

    # 3. Get video duration
    video_dur = v.get('duration', audio_dur_us)

    # 4. Update video material
    v['has_audio'] = False
    old_path = v['path']
    v['path'] = str(video_only).replace('\\', '/')
    v['duration'] = video_dur

    # 5. Add audio material
    audio_id = str(uuid.uuid4()).upper()
    new_audio = {
        "app_id": "", "category_id": "", "category_name": "", "check_flag": 0,
        "copyright_limit_type": "",
        "duration": audio_dur_us,
        "effect_id": "", "formula_id": "",
        "id": audio_id, "intensifies_path": "",
        "is_ai_clone_tone": False, "is_text_edit_overdub": False,
        "is_ugc": False, "local_material_id": "", "music_id": "",
        "name": "audio.mp3",
        "path": str(audio_mp3).replace('\\', '/'),
        "query": "", "request_id": "", "resource_id": "",
        "search_id": "", "source_from": "", "source_platform": "",
        "team_id": "", "text_id": "",
        "tone_category_id": "", "tone_category_name": "", "tone_effect_id": "",
        "tone_effect_name": "", "tone_platform": "", "tone_second_category_id": "",
        "tone_second_category_name": "", "tone_speaker": "", "tone_type": "",
        "type": "sound", "video_id": "", "wave_points": ""
    }
    data['materials']['audios'].append(new_audio)

    # 6. Add audio track segment
    video_seg = None
    for t in data['tracks']:
        if t['type'] == 'video' and t['segments']:
            video_seg = t['segments'][0]
            break

    if video_seg:
        target_range = video_seg['target_timerange']
        source_range = video_seg.get('source_timerange', {'duration': video_dur, 'start': 0})

        audio_seg_id = str(uuid.uuid4()).upper()
        audio_track_id = str(uuid.uuid4()).upper()

        audio_seg = {
            "caption_info": None, "cartoon": None,
            "clip": {"alpha":1,"flip":{"horizontal":False,"vertical":False},"rotation":0,"scale":{"x":1,"y":1},"transform":{"x":0,"y":0}},
            "common_keyframes": [], "enable_adjust": False,
            "enable_color_correct_adjust": False, "enable_color_curves": False,
            "enable_color_match_adjust": False, "enable_color_wheels": False,
            "enable_lut": False, "enable_smart_color_adjust": False,
            "extra_material_refs": [], "group_id": "", "hdr_settings": "",
            "id": audio_seg_id, "intensifies_audio": None,
            "is_placeholder": False, "is_tone_modify": False,
            "keyframe_refs": [], "last_nonzero_volume": 1,
            "material_id": audio_id, "render_index": 0,
            "responsive_layout": 0, "reverse": False,
            "source_timerange": source_range,
            "speed": 1.0, "target_timerange": target_range,
            "template_id": "", "template_scene": "",
            "track_attribute": 1, "track_render_index": 0,
            "uniform_scale": 1, "visible": True, "volume": 1
        }

        audio_track = {
            "type": "audio", "flag": 0, "is_main_track": False,
            "attribute": 0, "id": audio_track_id,
            "segments": [audio_seg]
        }
        data['tracks'].append(audio_track)
        print(f'添加音频轨道: target={target_range}')

    # 7. Write JSON files（三文件原子同步，由 write_draft 保证：写前关剪映 + 备份 + 原子写）
    write_draft(draft_path, data)

    print(f'\n分离完成！视频: video_only.mp4, 音频: audio.mp3')
    print(f'请打开剪映验证效果')
    
    # 自动打开剪映草稿验证
    draft_name = os.path.basename(str(draft_path))
    jy_path = os.environ.get('REALCUT_JIANYING_EXE', r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe')
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')
    open_py = os.path.join(script_dir, 'open_draft.py')
    if auto_open:
        print('\n正在打开剪映验证...')
        subprocess.run(['taskkill', '/f', '/im', 'JianyingPro.exe'], capture_output=True, text=True)
        subprocess.Popen([jy_path], shell=True)
        time.sleep(20)
        subprocess.run(['python', open_py, draft_name], capture_output=True, text=True)
        print(f'已打开草稿「{draft_name}」请查看')
    else:
        print('(Skipping CapCut auto-open, --no-open)')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    auto_open = '--no-open' not in sys.argv
    separate_audio(sys.argv[1], auto_open=auto_open)
