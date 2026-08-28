# -*- coding: utf-8 -*-
"""实验版音频平滑：备份人声 clip、合并过短相邻展示段、EBU R128 响度归一化。

用法: python audio_smooth.py <草稿路径> [--target-lufs -16] [--max-gain 12]
"""
import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from _utils import ensure_utf8_stdout, read_draft, uid, write_draft

ensure_utf8_stdout()


def ffmpeg_bin():
    return shutil.which('ffmpeg') or r'C:\ffmpeg\bin\ffmpeg.exe'


def _local_material_path(dp, mat):
    """把 sound 素材路径锁定到当前草稿目录，防止测试副本误改原草稿。"""
    raw = str(mat.get('path', '') or '').strip()
    name = str(mat.get('name', '') or '').strip()
    base = os.path.basename((raw or name or '').replace('\\', '/'))
    if not base:
        return None
    local = dp / base
    if local.is_file():
        mat['path'] = str(local)
        return local
    try:
        raw_path = Path(raw)
        if not raw_path.is_absolute():
            raw_path = dp / raw_path
        if raw_path.is_file():
            resolved = raw_path.resolve()
            if resolved == dp.resolve() or dp.resolve() in resolved.parents:
                mat['path'] = str(resolved)
                return resolved
    except OSError:
        pass
    if local.is_file():
        mat['path'] = str(local)
        return local
    return None


def audio_info(draft, dp):
    mats = {m['id']: m for m in draft.get('materials', {}).get('audios', []) + draft.get('materials', {}).get('music', [])}
    infos = []
    for tr in draft.get('tracks', []):
        if tr.get('type') != 'audio':
            continue
        for seg in tr.get('segments', []) or []:
            mat = mats.get(seg.get('material_id', {}), {})
            if mat.get('type') != 'sound':
                continue
            path = _local_material_path(dp, mat)
            base = os.path.basename(str(mat.get('path', '') or mat.get('name', '') or '').replace('\\', '/'))
            info = {
                'track': tr,
                'seg': seg,
                'mat': mat,
                'path': path if path is not None else (dp / base if base else None),
                'base': base,
                'target_dur': int((seg.get('target_timerange', {}) or {}).get('duration', 0) or 0),
                'source_dur': int((seg.get('source_timerange', {}) or {}).get('duration', 0) or 0),
                'speed': float(seg.get('speed', 1.0) or 1.0),
                'category': '',
                'meta': {},
            }
            if info['path'] is None or not info['path'].is_file():
                print(f'  [跳过] 草稿内未找到音频素材: {base}')
                continue
            infos.append(info)
    meta_path = dp / 'step4_segments.json'
    meta_by_clip = {}
    if meta_path.is_file():
        try:
            metas = json.loads(meta_path.read_text(encoding='utf-8-sig'))
            for m in metas:
                if m.get('index') is not None and m.get('category'):
                    meta_by_clip[f'clip_{m["index"]:02d}_{m["category"]}.mp3'] = m
        except Exception:
            pass
    for info in infos:
        info['meta'] = meta_by_clip.get(info['base'], {})
        info['category'] = str(info['meta'].get('category') or _category_from_name(info['base']))
    infos.sort(key=lambda x: (x['seg'].get('target_timerange', {}).get('start', 0), x['seg'].get('target_timerange', {}).get('duration', 0)))
    for i, info in enumerate(infos):
        info['new_index'] = i
    return infos


def _category_from_name(base):
    if '展示衣服' in base:
        return '展示衣服'
    if '金句' in base:
        return '金句'
    if '价格' in base:
        return '价格'
    if '爆点' in base:
        return '爆点'
    if '原价' in base:
        return '原价'
    if '上车价' in base:
        return '上车价'
    return '展示衣服'


def find_merge_groups(infos, each_ms=1300, total_ms=3000):
    groups = []
    i = 0
    each_us = each_ms * 1000
    total_us = total_ms * 1000
    while i < len(infos):
        info = infos[i]
        if info['category'] != '展示衣服' or info['target_dur'] >= each_us or abs(info['speed'] - 1.0) > 1e-6:
            i += 1
            continue
        group = [info]
        total = info['target_dur']
        j = i + 1
        while j < len(infos):
            nxt = infos[j]
            if nxt['track'] is not info['track']:
                break
            prev_end = group[-1]['seg']['target_timerange'].get('start', 0) + group[-1]['target_dur']
            nxt_start = nxt['seg']['target_timerange'].get('start', 0)
            if nxt_start < prev_end or nxt_start - prev_end > 1000:
                break
            if nxt['category'] != '展示衣服' or nxt['target_dur'] >= each_us or abs(nxt['speed'] - 1.0) > 1e-6:
                break
            if total + nxt['target_dur'] > total_us:
                break
            group.append(nxt)
            total += nxt['target_dur']
            j += 1
        if len(group) > 1:
            groups.append(group)
        i = j
    return groups


def backup_clips(dp, infos):
    backup_dir = dp / '.audio_smooth_backup'
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for info in infos:
        src = info['path']
        if not src.is_file():
            continue
        dst = backup_dir / src.name
        if not dst.exists():
            shutil.copy2(str(src), str(dst))
        copied.append(src.name)
    return backup_dir, sorted(set(copied))


def merge_group(group, dp):
    paths = [info['path'] for info in group]
    if any(not p.is_file() for p in paths):
        print(f'  [合并] 跳过缺失音频: {paths}')
        return False
    first = group[0]
    total_target = sum(x['target_dur'] for x in group)
    total_source = sum(x['source_dur'] for x in group)
    temp = dp / f'.audio_merge_{uuid.uuid4().hex}.mp3'
    ffmpeg = ffmpeg_bin()
    if not os.path.exists(ffmpeg):
        print('  [合并] 找不到 ffmpeg')
        return False
    cmd = [ffmpeg, '-y', '-nostdin', '-loglevel', 'error']
    for p in paths:
        cmd += ['-i', str(p)]
    filters = []
    for idx in range(len(paths)):
        filters.append(f'[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{idx}]')
    concat_in = ''.join(f'[a{i}]' for i in range(len(paths)))
    filters.append(f'{concat_in}concat=n={len(paths)}:v=0:a=1[aout]')
    cmd += ['-filter_complex', ';'.join(filters), '-map', '[aout]', '-c:a', 'libmp3lame', '-q:a', '2', str(temp)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
        print(f'  [合并] ffmpeg 失败: {(r.stderr or b"").decode("utf-8", errors="replace")[-300:]}')
        try:
            temp.unlink()
        except Exception:
            pass
        return False
    dest = first['path']
    try:
        os.replace(str(temp), str(dest))
    except Exception:
        try:
            temp.unlink()
        except Exception:
            pass
        return False
    first['mat']['path'] = str(dest)
    first['mat']['name'] = dest.name
    first['mat']['duration'] = sum(int(x['mat'].get('duration') or 0) for x in group) or total_source
    first['seg']['target_timerange'] = {'start': first['seg']['target_timerange'].get('start', 0), 'duration': total_target}
    first['seg']['source_timerange'] = {'start': 0, 'duration': total_source}
    refs = []
    for info in group:
        for ref in info['seg'].get('extra_material_refs', []) or []:
            if ref not in refs:
                refs.append(ref)
    first['seg']['extra_material_refs'] = refs
    first['meta']['file'] = dest.name
    first['meta']['merged_from_indices'] = [x['new_index'] for x in group[1:]]
    removed = {x['seg']['id'] for x in group[1:]}
    first['track']['segments'] = [s for s in first['track'].get('segments', []) if s.get('id') not in removed]
    print(f"  [合并] {len(group)} 段 -> {dest.name}（{total_target / 1000000:.2f}s）")
    return True


def measure_loudness(path):
    ffmpeg = ffmpeg_bin()
    cmd = [ffmpeg, '-nostdin', '-i', str(path), '-af', 'loudnorm=print_format=json', '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    text = ((r.stderr or b'') + (r.stdout or b'')).decode('utf-8', errors='replace')
    idx = text.rfind('{')
    if idx < 0:
        return None
    end = text.rfind('}')
    if end < idx:
        return None
    try:
        obj = json.loads(text[idx:end + 1])
        value = obj.get('input_i')
        if value == '-inf':
            return 'silence'
        return float(value) if value not in (None, 'inf') else None
    except Exception:
        return None


def normalize_clip(path, target_lufs=-16.0, max_gain_db=12.0):
    if not path.is_file():
        return False, 'missing'
    current = measure_loudness(path)
    if current is None:
        return False, 'measure_failed'
    if current == 'silence':
        print(f'  [响度] {path.name}: 静音片段，跳过归一化')
        return True, 'silence-skip'
    gain = target_lufs - current
    gain = max(-max_gain_db, min(max_gain_db, gain))
    temp = path.with_name(path.name + '.norm.tmp.mp3')
    ffmpeg = ffmpeg_bin()
    cmd = [
        ffmpeg, '-y', '-nostdin', '-loglevel', 'error',
        '-i', str(path),
        '-af', f'volume={gain:.3f}dB,alimiter=limit=0.95:attack=5:release=50:level=disabled',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(temp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            print(f'  [响度] {path.name} 处理失败: {(r.stderr or b"").decode("utf-8", errors="replace")[-300:]}')
            try:
                temp.unlink()
            except Exception:
                pass
            return False, 'ffmpeg'
        os.replace(str(temp), str(path))
        print(f"  [响度] {path.name}: {current:+.1f}dB -> {target_lufs:+.0f} LUFS（增益 {gain:+.1f}dB）")
        return True, f'{gain:.1f}dB'
    except Exception as exc:
        print(f'  [响度] {path.name} 异常: {exc}')
        return False, str(exc)


def rewrite_step4(dp, infos):
    rows = []
    for info in infos:
        meta = copy.deepcopy(info.get('meta') or {})
        if info['category'] == '展示衣服':
            src_dur_ms = int(info['source_dur'] / 1000)
            meta.setdefault('src_start_ms', 0)
            meta['src_dur_ms'] = src_dur_ms
            meta['src_end_ms'] = meta.get('src_start_ms', 0) + src_dur_ms
        file = meta.get('file') or (info['path'].name if info['path'] else '')
        rows.append({
            'index': info['new_index'],
            'category': info['category'],
            'src_start_ms': meta.get('src_start_ms', 0),
            'src_end_ms': meta.get('src_end_ms', 0),
            'src_dur_ms': meta.get('src_dur_ms', 0),
            'source': meta.get('source', 'asr'),
            'text': meta.get('text', ''),
            'file': file,
            'merged_from_indices': meta.get('merged_from_indices'),
        })
    (dp / 'step4_segments.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


def smooth_audio(dp_str, target_lufs=-16.0, max_gain_db=12.0, merge_each_ms=1300, merge_total_ms=3000):
    dp = Path(dp_str).resolve()
    draft = read_draft(dp)
    infos = audio_info(draft, dp)
    if not infos:
        print('未找到可处理的人声 clip')
        return True
    backup_dir, names = backup_clips(dp, infos)
    print(f'已备份 {len(names)} 个人声 clip 到 {backup_dir}')
    groups = find_merge_groups(infos, merge_each_ms, merge_total_ms)
    merged_count = 0
    for group in groups:
        if merge_group(group, dp):
            merged_count += 1
            for info in group[1:]:
                info['removed'] = True
    infos = [i for i in infos if not i.get('removed')]
    for i, info in enumerate(infos):
        info['new_index'] = i
    ok = 0
    failed = 0
    for info in infos:
        success, _ = normalize_clip(info['path'], target_lufs, max_gain_db)
        if success:
            ok += 1
        else:
            failed += 1
    write_draft(dp, draft)
    rewrite_step4(dp, infos)
    report = {
        'target_lufs': target_lufs,
        'max_gain_db': max_gain_db,
        'merge_each_ms': merge_each_ms,
        'merge_total_ms': merge_total_ms,
        'merged_groups': merged_count,
        'normalized': ok,
        'failed': failed,
        'backup_dir': str(backup_dir),
    }
    (dp / 'audio_smooth_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'音频平滑完成：合并 {merged_count} 组，归一化 {ok} 条，失败 {failed} 条')
    return failed == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='实验版音频平滑')
    parser.add_argument('draft', help='草稿路径')
    parser.add_argument('--target-lufs', type=float, default=-16.0)
    parser.add_argument('--max-gain', type=float, default=12.0)
    parser.add_argument('--merge-each-ms', type=int, default=1300)
    parser.add_argument('--merge-total-ms', type=int, default=3000)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    sys.exit(0 if smooth_audio(args.draft, args.target_lufs, args.max_gain, args.merge_each_ms, args.merge_total_ms) else 1)
