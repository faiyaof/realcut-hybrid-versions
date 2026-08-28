"""
导入视频到剪映草稿
用法: python "导入视频到剪映.py" <视频路径>

示例:
  python "导入视频到剪映.py" D:\共享文件夹\2026-05-16-09-00-27_clips\0010.mkv
"""

import json, uuid, os, shutil, time, sys, subprocess
from pathlib import Path
from _utils import write_draft, ensure_utf8_stdout

ensure_utf8_stdout()

DRAFT_DIR = r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft'

def get_ffprobe(path, arg):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', arg,
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return r.stdout.strip()

def create_draft(video_path, auto_open=True, draft_name_override=None):
    if not os.path.exists(video_path):
        print(f'文件不存在: {video_path}')
        return

    basename = os.path.splitext(os.path.basename(video_path))[0]
    # Clean draft name: max 50 chars, no special chars
    draft_name = f'{basename}'
    if draft_name_override:
        draft_name = draft_name_override
    if len(draft_name) > 50:
        draft_name = draft_name[:50]
    # Add prefix to avoid conflict with existing drafts
    existing = set(os.listdir(DRAFT_DIR))
    if draft_name in existing:
        i = 1
        while f'{draft_name}_{i}' in existing:
            i += 1
        draft_name = f'{draft_name}_{i}'

    draft_path = os.path.join(DRAFT_DIR, draft_name)
    os.makedirs(draft_path, exist_ok=True)

    # Copy video
    video_dest = os.path.join(draft_path, os.path.basename(video_path))
    if not os.path.exists(video_dest):
        print(f'复制视频...')
        shutil.copy2(video_path, video_dest)

    # Get video info
    duration_s = float(get_ffprobe(video_path, 'format=duration'))
    duration_us = int(duration_s * 1000000)
    wh = get_ffprobe(video_path, 'stream=width,height').split(',')
    width, height = int(wh[0]), int(wh[1])
    fps_str = get_ffprobe(video_path, 'stream=r_frame_rate').split('\n')[0].split('\n')[0].split('\n')[0]
    if '/' in fps_str:
        num, den = fps_str.split('/')
        fps = float(num) / float(den) if int(den) > 0 else float(num)
    else:
        fps = float(fps_str)

    print(f'视频: {basename} ({width}x{height}, {fps:.1f}fps, {duration_s:.2f}s)')

    # Generate IDs
    video_id = str(uuid.uuid4()).upper()
    draft_id = str(uuid.uuid4()).upper()
    track_id = str(uuid.uuid4()).upper()
    segment_id = str(uuid.uuid4()).upper()
    video_path_normalized = video_dest.replace('\\', '/')

    # draft_content.json
    content = {
        "canvas_config": {
            "design_resolution_switch": False, "resolution_mode": 2,
            "canvas_aspect_ratio_id": "ratio_9:16",
            "canvas_height": height, "canvas_width": width,
            "canvas_rotation": 0, "enable_design_resolution": True,
            "design_resolution_width": width, "design_resolution_height": height,
            "design_resolution_preset_id": "vertical_9_16_1080",
            "canvas_mode": "free", "design_resolution_duration": duration_us,
            "design_resolution_fps": fps,
            "canvas_id": str(uuid.uuid4()).upper(),
            "is_template_canvas": False, "is_ai_layout": False, "ai_layout_data": ""
        },
        "color_space": "", "config": {
            "app_version": "5.9.0.11632", "draft_id": draft_id,
            "enable_caption_auto_generate": False, "is_use_mv_auto_draft": False,
            "source_platform": "win", "storyline_mode": False
        },
        "cover": {"type": "none", "image_id": "", "image_name": ""},
        "create_time": int(time.time()), "duration": duration_us,
        "extra_info": {"draft_business_id": "", "draft_description": ""},
        "fps": fps, "free_render_index_mode_on": False, "group_container": {},
        "id": draft_id, "keyframe_graph_list": [], "keyframes": [],
        "last_modified_platform": "win",
        "materials": {
            "ai_translates": [], "audio_balances": [], "audio_effects": [],
            "audio_fades": [], "audio_track_indexes": [], "audios": [],
            "beats": [],
            "canvases": [{"album_image":"","blur":0,"color":[0,0,0],"id":str(uuid.uuid4()).upper(),"image":"","image_id":"","image_name":"","source_platform":"","team_id":"","type":"canvas_blur_color"}],
            "chromas": [], "color_curves": [], "digital_humans": [], "drafts": [],
            "effects": [], "flowers": [], "green_screens": [], "handwrites": [],
            "hsl": [], "images": [], "log_color_wheels": [], "loudnesses": [],
            "manual_deformations": [], "masks": [], "material_animations": [],
            "material_colors": [], "multi_language_refs": [], "placeholders": [],
            "plugin_effects": [], "primary_color_wheels": [], "realtime_denoises": [],
            "shapes": [], "smart_crops": [], "smart_relights": [],
            "sound_channel_mappings": [], "speeds": [], "stickers": [],
            "tail_leaders": [], "text_templates": [], "texts": [],
            "time_marks": [], "transitions": [], "video_effects": [],
            "video_trackings": [],
            "videos": [{
                "aigc_type": "", "audio_fade": "", "cartoon_path": "",
                "category_id": "", "category_name": "", "check_flag": 0,
                "crop": {"height": 0, "width": 0, "x": 0, "y": 0},
                "crop_ratio": 0.0, "crop_scale": 1.0, "duration": duration_us,
                "extra_type_option": 0, "formula_id": "", "freeze": "",
                "has_audio": True, "height": height, "id": video_id,
                "intensifies_audio_path": "", "intensifies_path": "",
                "is_ai_generate_content": False, "is_copyright": False,
                "is_text_edit_overdub": False, "is_unified_beauty_mode": False,
                "local_id": "", "local_material_id": "", "material_id": "",
                "material_name": "", "material_url": "", "matting": "",
                "media_path": "", "object_locked": False, "origin_material_id": "",
                "path": video_path_normalized,
                "picture_from": "", "picture_set_category_id": "",
                "picture_set_category_name": "", "request_id": "",
                "reverse_intensifies_path": "", "reverse_path": "",
                "smart_motion": "", "source": "", "source_platform": "",
                "stable": "", "team_id": "", "type": "video",
                "video_algorithm": "", "width": width
            }],
            "vocal_beautifys": [], "vocal_separations": []
        },
        "mutable_config": {}, "name": draft_name, "new_version": "5.9.0",
        "platform": "pc", "relationships": {},
        "render_index_track_mode_on": True, "retouch_cover": False,
        "source": "pc", "static_cover_image_path": "", "time_marks": [],
        "tracks": [{
            "type": "video", "flag": 0, "is_main_track": True, "attribute": 0,
            "id": track_id, "segments": [{
                "caption_info": None, "cartoon": None,
                "clip": {"alpha":1,"flip":{"horizontal":False,"vertical":False},"rotation":0,"scale":{"x":1,"y":1},"transform":{"x":0,"y":0}},
                "common_keyframes": [], "enable_adjust": False,
                "enable_color_correct_adjust": False, "enable_color_curves": False,
                "enable_color_match_adjust": False, "enable_color_wheels": False,
                "enable_lut": False, "enable_smart_color_adjust": False,
                "extra_material_refs": [], "group_id": "", "hdr_settings": "",
                "id": segment_id, "intensifies_audio": None,
                "is_placeholder": False, "is_tone_modify": False,
                "keyframe_refs": [], "last_nonzero_volume": 1,
                "material_id": video_id, "render_index": 0,
                "responsive_layout": 0, "reverse": False,
                "source_timerange": {"duration": duration_us, "start": 0},
                "speed": 1.0, "target_timerange": {"duration": duration_us, "start": 0},
                "template_id": "", "template_scene": "",
                "track_attribute": 1, "track_render_index": 0,
                "uniform_scale": 1, "visible": True, "volume": 1
            }]
        }],
        "update_time": int(time.time()), "version": 360000
    }

    # Write all files（三文件原子同步 + 写前备份 + 写前关剪映，由 write_draft 保证）
    write_draft(draft_path, content)

    # draft_meta_info.json
    with open(os.path.join(draft_path, 'draft_meta_info.json'), 'w', encoding='utf-8') as f:
        json.dump({
            "cloud_package_completed_time": "", "draft_cloud_capcut_purchase_info": "",
            "draft_cloud_last_action_download": False, "draft_cloud_materials": [],
            "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
            "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
            "draft_cover": "draft_cover.jpg", "draft_deeplink_url": "",
            "draft_enterprise_info": {"draft_enterprise_extra":"","draft_enterprise_id":"","draft_enterprise_name":"","enterprise_material":[]},
            "draft_fold_path": video_path_normalized.replace(f'/{os.path.basename(video_path)}', ''),
            "draft_id": draft_id, "draft_is_ai_packaging_used": False,
            "draft_is_ai_shorts": False, "draft_is_ai_translate": False,
            "draft_is_article_video_draft": False, "draft_is_from_deeplink": "false",
            "draft_is_invisible": False,
            "draft_materials": [{"type":0,"value":[{"create_time":int(time.time()),"duration":duration_us,"extra_info":os.path.basename(video_path),"file_Path":"./" + os.path.basename(video_path),"height":height,"id":video_id.lower().replace('-',''),"import_time":int(time.time()),"import_time_ms":int(time.time()*1000000),"item_source":1,"md5":"","metetype":"video","roughcut_time_range":{"duration":duration_us,"start":0},"sub_time_range":{"duration":-1,"start":-1},"type":0,"width":width}]},{"type":1,"value":[]},{"type":2,"value":[]},{"type":3,"value":[]},{"type":6,"value":[]},{"type":7,"value":[]},{"type":8,"value":[]}],
            "draft_materials_copied_info": [], "draft_name": draft_name,
            "draft_new_version": "109.0.0", "draft_removable_storage_device": "",
            "draft_root_path": DRAFT_DIR.replace('\\', '/'),
            "draft_segment_extra_info": [], "draft_timeline_materials_size_": os.path.getsize(video_path),
            "draft_type": "", "tm_draft_cloud_completed": "", "tm_draft_cloud_modified": 0,
            "tm_draft_create": int(time.time()*1000000), "tm_draft_modified": int(time.time()*1000000),
            "tm_draft_removed": 0, "tm_duration": duration_us
        }, f, ensure_ascii=False, indent=4)

    # template.tmp
    with open(os.path.join(draft_path, 'template.tmp'), 'w', encoding='utf-8') as f:
        json.dump({
            "canvas_config":{"height":0,"ratio":"original","width":0},"color_space":-1,
            "config":{"adjust_max_index":1,"attachment_info":[],"combination_max_index":1,"export_range":None,"extract_audio_last_index":1,"lyrics_recognition_id":"","lyrics_sync":True,"lyrics_taskinfo":[],"maintrack_adsorb":True,"material_save_mode":0,"multi_language_current":"none","multi_language_list":[],"multi_language_main":"none","multi_language_mode":"none","original_sound_last_index":1,"record_audio_last_index":1,"sticker_max_index":1,"subtitle_keywords_config":None,"subtitle_recognition_id":"","subtitle_sync":True,"subtitle_taskinfo":[],"system_font_list":[],"video_mute":False,"zoom_info_params":None},
            "cover":None,"create_time":0,"duration":0,"extra_info":None,"fps":30.0,"free_render_index_mode_on":False,"group_container":None,"id":draft_id,
            "keyframe_graph_list":[],"keyframes":{"adjusts":[],"audios":[],"effects":[],"filters":[],"handwrites":[],"stickers":[],"texts":[],"videos":[]},
            "last_modified_platform":{"app_id":0,"app_source":"","app_version":"","device_id":"","hard_disk_id":"","mac_address":"","os":"","os_version":""},
            "materials":{"ai_translates":[],"audio_balances":[],"audio_effects":[],"audio_fades":[],"audio_track_indexes":[],"audios":[],"beats":[],"canvases":[],"chromas":[],"color_curves":[],"digital_humans":[],"drafts":[],"effects":[],"flowers":[],"green_screens":[],"handwrites":[],"hsl":[],"images":[],"log_color_wheels":[],"loudnesses":[],"manual_deformations":[],"masks":[],"material_animations":[],"material_colors":[],"multi_language_refs":[],"placeholders":[],"plugin_effects":[],"primary_color_wheels":[],"realtime_denoises":[],"shapes":[],"smart_crops":[],"smart_relights":[],"sound_channel_mappings":[],"speeds":[],"stickers":[],"tail_leaders":[],"text_templates":[],"texts":[],"time_marks":[],"transitions":[],"video_effects":[],"video_trackings":[],"videos":[],"vocal_beautifys":[],"vocal_separations":[]},
            "mutable_config":None,"name":"","new_version":"75.0.0",
            "platform":{"app_id":0,"app_source":"","app_version":"","device_id":"","hard_disk_id":"","mac_address":"","os":"","os_version":""},
            "relationships":[],"render_index_track_mode_on":False,"retouch_cover":None,"source":"default","static_cover_image_path":"","time_marks":None,"tracks":[],"update_time":0,"version":360000
        }, f, ensure_ascii=False, indent=4)

    # draft_settings
    now = int(time.time())
    with open(os.path.join(draft_path, 'draft_settings'), 'w', encoding='utf-8') as f:
        f.write(f"[General]\ncloud_last_modify_platform=windows\ndraft_create_time={now}\ndraft_last_edit_time={now}\nreal_edit_seconds=10\nreal_edit_keys=1\n")

    # attachment_pc_common.json
    with open(os.path.join(draft_path, 'attachment_pc_common.json'), 'w', encoding='utf-8') as f:
        json.dump({"ai_packaging_infos":[],"ai_packaging_report_info":{"caption_id_list":[],"task_id":"","text_style":"","tos_id":"","video_category":""},"commercial_music_category_ids":[],"pc_feature_flag":0,"recognize_tasks":[],"template_item_infos":[],"unlock_template_ids":[]}, f, ensure_ascii=False, indent=4)

    # Remove .bak / .backup
    for fn in os.listdir(draft_path):
        if fn.endswith('.bak') or fn.endswith('.backup'):
            os.remove(os.path.join(draft_path, fn))

    print(f'草稿「{draft_name}」创建完成！')
    print(f'打开剪映 -> 本地草稿 查看')
    
    # 自动打开剪映草稿验证
    jy_path = r'C:\Users\JT\Desktop\剪映5.9Windows\JianyingPro\5.9.0.11632\JianyingPro.exe'
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
    draft_name_override = None
    if '--draft-name' in sys.argv:
        idx = sys.argv.index('--draft-name')
        if idx + 1 < len(sys.argv):
            draft_name_override = sys.argv[idx + 1]
    create_draft(sys.argv[1], auto_open=auto_open, draft_name_override=draft_name_override)
