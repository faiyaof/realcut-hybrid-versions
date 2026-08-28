from _utils import write_draft, resolve_template_dir, ensure_utf8_stdout
import json, sys, uuid, shutil, copy, os, random, io
ensure_utf8_stdout()

# 花字默认关闭：业务已确认不需要花字。如需恢复，显式设置 REALCUT_ENABLE_HUAZI=1。
_enable_huazi = os.environ.get("REALCUT_ENABLE_HUAZI", "").strip().lower()
if _enable_huazi not in {"1", "true", "yes", "on"}:
    print("花字默认关闭：跳过步骤9（需要时设置 REALCUT_ENABLE_HUAZI=1）")
    sys.exit(0)

from pathlib import Path

ensure_utf8_stdout()



# 模板草稿：优先用当前风格的模板（style_config.json），找不到再回退 com.lveditor.draft/草稿
TEMPLATE, _tmpl_name = resolve_template_dir()
if TEMPLATE is None:
    TEMPLATE = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')) / '草稿'
BACKUP_TMPL = Path(os.environ.get('REALCUT_STYLE_LIB', r'D:\JianyingPro Drafts')) / '草稿'
FALLBACK_MATERIAL_TMPL = Path(os.environ.get('REALCUT_DRAFT_ROOT', r'C:\Users\JT\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft')) / '草稿'

def _has_huazi_materials(tmpl_dir):
    dc = tmpl_dir / 'draft_content.json'
    if not dc.exists():
        return False
    try:
        d = json.load(open(dc, encoding='utf-8'))
        m = d.get('materials', {})
        named_audios = [a for a in m.get('audios', []) if a.get('name')]
        return bool(m.get('text_templates')) and len(named_audios) >= 3
    except Exception:
        return False

if not _has_huazi_materials(TEMPLATE):
    if (FALLBACK_MATERIAL_TMPL / 'draft_content.json').exists():
        print(f'风格模板缺少花字/音效素材，花字/音效改用: {FALLBACK_MATERIAL_TMPL.name}')
        TEMPLATE = FALLBACK_MATERIAL_TMPL

def uid(): return str(uuid.uuid4()).upper()



dp = Path(sys.argv[1])

seg_meta_path = dp / 'step4_segments.json'




def ensure_template():
    if not (TEMPLATE / 'draft_content.json').exists():
        if BACKUP_TMPL.exists():
            if TEMPLATE.exists():
                shutil.rmtree(str(TEMPLATE))
            shutil.copytree(str(BACKUP_TMPL), str(TEMPLATE))
            print('已从 D: 复制模板草稿')
        else:
            print(f'模板草稿不存在: {TEMPLATE}')
            return False
    return True

if not ensure_template():
    sys.exit(1)

print(f'花字/音效 使用模板: {TEMPLATE}')

with open(TEMPLATE / 'draft_content.json', 'r', encoding='utf-8') as f:

    tmpl = json.load(f)

with open(dp / 'draft_content.json', 'r', encoding='utf-8') as f:

    draft = json.load(f)



asegs = [t['segments'] for t in draft['tracks'] if t['type'] == 'audio'][0]



# ===== CLEANUP: Only remove old flower text =====

old_tt_ids = {t['id'] for t in draft['materials'].get('text_templates', [])}

draft['tracks'] = [t for t in draft['tracks'] if not (

    t['type'] == 'text' and len(t.get('segments', [])) > 0

    and t['segments'][0].get('material_id', '') in old_tt_ids

)]

draft['materials']['text_templates'] = []



tmpl_sfx_names = {a.get('name') for a in tmpl['materials'].get('audios', []) if a.get('name')}

old_sfx_ids = {a['id'] for a in draft['materials']['audios'] 

               if a.get('name') in tmpl_sfx_names and a.get('duration', 0) < 5000000}

if old_sfx_ids:

    draft['materials']['audios'] = [a for a in draft['materials']['audios'] if a['id'] not in old_sfx_ids]

draft['tracks'] = [t for t in draft['tracks'] if not (

    t.get('name') == '__sfx__' and len(t.get('segments', [])) > 0

    and t['segments'][0].get('material_id', '') in old_sfx_ids

)]



# Clone template materials

new_tt = [copy.deepcopy(t) for t in tmpl['materials']['text_templates']]

for t in new_tt:

    t['id'] = uid()

    t['resources'] = copy.deepcopy(t.get('resources', []))

new_tx = [copy.deepcopy(t) for t in tmpl['materials']['texts']]

for t in new_tx:

    t['id'] = uid()

old_ids_mapping = {tmpl['materials']['texts'][k]['id']: new_tx[k]['id'] for k in range(len(new_tx))}

for tt in new_tt:

    for r in tt.get('text_info_resources', []):

        rid = r.get('text_material_id', '')

        if rid in old_ids_mapping:

            r['text_material_id'] = old_ids_mapping[rid]

new_ma = [copy.deepcopy(a) for a in tmpl['materials']['material_animations']]

for a in new_ma:

    a['id'] = uid()

new_ef = [copy.deepcopy(e) for e in tmpl['materials']['effects']]

for e in new_ef:

    e['id'] = uid()

sfx_map = {}

for a in tmpl['materials']['audios']:

    name = a.get('name', '')

    if name:

        na = copy.deepcopy(a)

        na['id'] = uid()

        sfx_map[name] = na



draft['materials']['text_templates'] = new_tt

draft['materials']['texts'] = draft['materials'].get('texts', []) + new_tx

draft['materials']['material_animations'] = draft['materials'].get('material_animations', []) + new_ma

draft['materials']['effects'] = draft['materials'].get('effects', []) + new_ef



# ===== POSITIONING: fix the 'or 0 is falsy' bug =====

seg_meta = []

if seg_meta_path.exists():

    with open(seg_meta_path, 'r', encoding='utf-8') as f:

        seg_meta = json.load(f)

cat_list = [m.get('category', '') for m in seg_meta] if seg_meta else []



def find_idx(cats, first=True):

    hits = [i for i, c in enumerate(cat_list) if c in cats]

    if not hits:

        return None

    return hits[0] if first else hits[-1]



def first_found(*lookups):

    for fn, cats, first in lookups:

        idx = fn(cats, first)

        if idx is not None:

            return idx

    return 0



idx_front = first_found(

    (find_idx, ['爆点'], True),

    (find_idx, ['展示衣服'], True),

)

idx_mid = first_found(

    (find_idx, ['金句'], True),

)

if idx_mid is None:

    idx_mid = len(asegs) // 2

if idx_mid <= idx_front:

    idx_mid = min(idx_front + 1, len(asegs) - 1)



idx_back = first_found(

    (find_idx, ['价格'], False),

    (find_idx, ['展示衣服'], False),

)

if idx_back is None:

    idx_back = len(asegs) - 1

if idx_back <= idx_mid:

    idx_back = min(idx_mid + 1, len(asegs) - 1)



    tt_front_start = asegs[idx_front]['target_timerange']['start'] / 1e6

    tt_mid_start = asegs[idx_mid]['target_timerange']['start'] / 1e6

    tt_back_start = asegs[idx_back]['target_timerange']['start'] / 1e6

    print(f'花字定位(原始): 前=seg{idx_front}[{tt_front_start:.1f}s], 中=seg{idx_mid}[{tt_mid_start:.1f}s], 后=seg{idx_back}[{tt_back_start:.1f}s]')



# Apply flower text

avail_tmpl = [0, 1, 2, 3, 4, 6, 7]  # ❌ 模板5(618促销)已禁用，用模板4替代

avail_sfx = [k for k, v in sfx_map.items() if v.get('duration', 0) < 5000000]

if not avail_sfx:

    avail_sfx = list(sfx_map.keys())[:3]

random.shuffle(avail_tmpl)

random.shuffle(avail_sfx)



# 去重：不允许两个花字落在同一个segment上

def dedupe_positions(indices, min_gap_s=2.0):

    occupied = set()

    result = []

    for pos in indices:

        if pos in occupied:

            found = None

            for alt in range(pos + 1, len(asegs)):

                if alt not in occupied:

                    found = alt

                    break

            if found is None:

                for alt in range(pos - 1, -1, -1):

                    if alt not in occupied:

                        found = alt

                        break

            if found is not None:

                print(f'  去重: seg{pos} 已被占用，移至 seg{found}')

                pos = found

            else:

                print(f'  去重: seg{pos} 已被占用且无可替换位置，丢弃')

                continue

        result.append(pos)

        occupied.add(pos)

    return result



# 先尝试3个位置做去重

candidates = [idx_front, idx_mid, idx_back]

candidates = dedupe_positions(candidates)

if len(candidates) < 2:

    candidates = [idx_front] if idx_front < len(asegs) else [0]



# 构建 huazi_items，与实际可用位置对齐

if len(candidates) >= 3:

    huazi_items = [

        (avail_tmpl[0], candidates[0], avail_sfx[0]),

        (avail_tmpl[1], candidates[1], avail_sfx[1]),

        (avail_tmpl[2], candidates[2], avail_sfx[2]),

    ]

    sfx_vol = {s: 0.178 for s in avail_sfx[:3]}

elif len(candidates) == 2:

    huazi_items = [

        (avail_tmpl[0], candidates[0], avail_sfx[0]),

        (avail_tmpl[1], candidates[1], avail_sfx[1]),

    ]

    sfx_vol = {avail_sfx[0]: 0.178, avail_sfx[1]: 0.178}

else:

    huazi_items = [

        (avail_tmpl[0], candidates[0], avail_sfx[0]),

    ]

    sfx_vol = {avail_sfx[0]: 0.178}



for ti, sidx, sfx_key in huazi_items:

    if sidx >= len(asegs):

        continue

    seg = asegs[sidx]

    tgt = seg['target_timerange']

    seg_start = tgt['start']

    seg_dur = tgt['duration']

    dur = min(seg_dur, 2000000)



    tt_id = new_tt[ti]['id'] if ti < len(new_tt) else new_tt[0]['id']

    hz = {

        'caption_info': None, 'cartoon': False,

        'clip': {'alpha': 1, 'flip': {'horizontal': False, 'vertical': False},

                 'rotation': 0, 'scale': {'x': 0.35, 'y': 0.35},

                 'transform': {'x': 0.5, 'y': 0.65}},

        'common_keyframes': [], 'enable_adjust': False,

        'enable_color_correct_adjust': False, 'enable_color_curves': True,

        'enable_color_match_adjust': False, 'enable_color_wheels': True,

        'enable_lut': False, 'enable_smart_color_adjust': False,

        'extra_material_refs': [], 'group_id': '', 'hdr_settings': None,

        'id': uid(), 'intensifies_audio': False,

        'is_placeholder': False, 'is_tone_modify': False,

        'keyframe_refs': [], 'last_nonzero_volume': 1,

        'material_id': tt_id, 'render_index': 0,

        'responsive_layout': {'enable': False, 'horizontal_pos_layout': 0,

                               'size_layout': 0, 'target_follow': '',

                               'vertical_pos_layout': 0},

        'reverse': False, 'source_timerange': None, 'speed': 1,

        'target_timerange': {'duration': dur, 'start': seg_start},

        'template_id': '', 'template_scene': '',

        'track_attribute': 0, 'track_render_index': 0,

        'uniform_scale': 1, 'visible': True, 'volume': 1

    }

    draft['tracks'].append({'type': 'text', 'flag': 0, 'is_main_track': False,

                             'attribute': 0, 'id': uid(), 'segments': [hz]})



    sfx_obj = sfx_map.get(sfx_key)

    if sfx_obj:

        sfx_orig_dur = sfx_obj['duration']

        sfx_seg = {

            'caption_info': None, 'cartoon': False, 'clip': None,

            'common_keyframes': [], 'enable_adjust': False,

            'enable_color_correct_adjust': False, 'enable_color_curves': True,

            'enable_color_match_adjust': False, 'enable_color_wheels': True,

            'enable_lut': False, 'enable_smart_color_adjust': False,

            'extra_material_refs': [], 'group_id': '',

            'hdr_settings': None, 'id': uid(),

            'intensifies_audio': None, 'is_placeholder': False,

            'is_tone_modify': False, 'keyframe_refs': [],

            'last_nonzero_volume': sfx_vol.get(sfx_key, 0.316),

            'material_id': sfx_obj['id'], 'render_index': 0,

            'responsive_layout': {'enable': False, 'horizontal_pos_layout': 0,

                                   'size_layout': 0, 'target_follow': '',

                                   'vertical_pos_layout': 0},

            'reverse': False,

            'source_timerange': {'duration': sfx_orig_dur, 'start': 0},

            'speed': 1.0,

            'target_timerange': {'duration': sfx_orig_dur, 'start': seg_start},

            'template_id': '', 'template_scene': '',

            'track_attribute': 1, 'track_render_index': 0,

            'uniform_scale': 1, 'visible': True, 'volume': sfx_vol.get(sfx_key, 0.316)

        }

        draft['materials']['audios'].append(sfx_obj)

        draft['tracks'].append({'type': 'audio', 'flag': 0, 'is_main_track': False,

                                 'attribute': 0, 'id': uid(), 'name': '__sfx__',

                                 'segments': [sfx_seg]})



write_draft(dp, draft)



print('花字+音效添加完成:')

for ti, sidx, sfx_key in huazi_items:

    print(f'  seg{sidx} 花字模板{ti} + {sfx_key}')



