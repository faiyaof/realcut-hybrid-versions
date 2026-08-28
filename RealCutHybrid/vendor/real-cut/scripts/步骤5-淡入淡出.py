"""
步骤5：音频淡入淡出 — 给每段音频加200ms淡入淡出
用法: python "步骤5-淡入淡出.py" <草稿路径>
"""

import json, sys, os, uuid, shutil, subprocess, time
from _utils import write_draft
from pathlib import Path

def uid(): return str(uuid.uuid4()).upper()

def add_fades(draft_path, auto_open=True):
    draft_path = Path(draft_path)
    dc_path = draft_path / 'draft_content.json'

    if not dc_path.exists():
        print('draft_content.json 不存在')
        return

    with open(dc_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)

    # Create 1 audio fade material
    fade_id = uid()
    fade = {
        "fade_in_duration": 200000,   # 200ms fade in
        "fade_out_duration": 200000,  # 200ms fade out
        "fade_type": 0,
        "id": fade_id,
        "type": "audio_fade"
    }
    draft['materials']['audio_fades'] = [fade]

    # Add fade ref to every audio segment
    fade_count = 0
    for t in draft['tracks']:
        if t['type'] == 'audio':
            for s in t['segments']:
                refs = s.get('extra_material_refs', [])
                if not isinstance(refs, list):
                    refs = []
                if fade_id not in refs:
                    refs.append(fade_id)
                s['extra_material_refs'] = refs
                fade_count += 1

    write_draft(draft_path, draft)

    print(f'添加淡入淡出完成！')
    print(f'  200ms淡入 + 200ms淡出')
    print(f'  已应用到 {fade_count} 个音频片段')

    # 自动打开剪映草稿验证
    draft_name = os.path.basename(str(draft_path))
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
    add_fades(sys.argv[1], auto_open=auto_open)
