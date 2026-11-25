#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品图片本地颜色识别、人工复核与手动标注平台。

用法:
    python "Utils/Product color recognition/color_matcher.py" products.json images
    python "Utils/Product color recognition/color_matcher.py"

图片路径按 download_images.py 的规则解析：<图片目录>/<md5>/<images索引:03d>.(jpg|png)。
启动后在浏览器中逐商品查看拼图，可先运行本地识别，再确认或手动调整。
自动成功结果写入输出 JSON，未成功结果仅保存候选和原因，人工操作优先。
原始 JSON 保留不变；识别来源和复核状态保存在兼容旧版的进度文件中。
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import mimetypes
from pathlib import Path
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from local_color_recognition import extract_features, recognize_product
from product_data import (
    atomic_json as _atomic_json,
    clean_pasted_path as _clean_pasted_path,
    find_color_map as _find_color_map,
    safe_product_folder as _safe_product_folder,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CONTACT_SHEET_COLUMNS = 5
CONTACT_CELL_SIZE = (220, 180)
CONTACT_GAP = 2
CONTACT_LABEL_SIZE = (70, 50)


def _image_for_index(folder: Path, index: int) -> tuple[Path | None, str | None]:
    stem = f"{index:03d}"
    matches = [path for path in folder.glob(stem + ".*")
               if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, "找不到该序号图片"
    return None, "同一序号存在多个图片文件，无法确定使用哪一个"


def _contact_sheet_font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 24)
    except OSError:
        try:
            return ImageFont.load_default(size=24)
        except TypeError:
            return ImageFont.load_default()


def create_contact_sheets(
    images_root: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[Path, int, int]:
    """为图片根目录下每个 MD5 图片文件夹生成五列序号拼图。

    拼图写入 images_root/_contact_sheets/<md5>.jpg；原始序号图片保持不变。
    返回 (拼图目录, 成功生成数量, 无法读取的原图数量)。
    """
    output_dir = images_root / "_contact_sheets"
    if not images_root.is_dir():
        return output_dir, 0, 0

    folders = sorted(
        (path for path in images_root.iterdir()
         if path.is_dir() and path.name.casefold() != "_contact_sheets"),
        key=lambda path: path.name.casefold(),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    font = _contact_sheet_font()
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    generated = 0
    unreadable = 0

    for folder_index, folder in enumerate(folders, start=1):
        if progress_callback is not None:
            progress_callback(folder_index, len(folders))
        image_files = sorted(
            (path for path in folder.iterdir()
             if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stem.isdecimal()),
            key=lambda path: (int(path.stem), path.name.casefold()),
        )
        if not image_files:
            continue
        sheet_path = output_dir / f"{folder.name}.jpg"
        try:
            # Directory time also changes when an image is deleted or renamed.
            newest_source = max(folder.stat().st_mtime_ns,
                                *(path.stat().st_mtime_ns for path in image_files))
            if sheet_path.is_file() and sheet_path.stat().st_mtime_ns >= newest_source:
                continue
        except OSError:
            pass

        rows = (len(image_files) + CONTACT_SHEET_COLUMNS - 1) // CONTACT_SHEET_COLUMNS
        cell_width, cell_height = CONTACT_CELL_SIZE
        sheet_width = CONTACT_SHEET_COLUMNS * cell_width + (CONTACT_SHEET_COLUMNS + 1) * CONTACT_GAP
        sheet_height = rows * cell_height + (rows + 1) * CONTACT_GAP
        sheet = Image.new("RGB", (sheet_width, sheet_height), (238, 238, 238))
        draw = ImageDraw.Draw(sheet)

        for cell_index, image_path in enumerate(image_files):
            number = int(image_path.stem)
            column = cell_index % CONTACT_SHEET_COLUMNS
            row = cell_index // CONTACT_SHEET_COLUMNS
            x = CONTACT_GAP + column * (cell_width + CONTACT_GAP)
            y = CONTACT_GAP + row * (cell_height + CONTACT_GAP)
            try:
                with Image.open(image_path) as source:
                    thumbnail = source.convert("RGB")
                    thumbnail.thumbnail(CONTACT_CELL_SIZE, resampling)
                tile = Image.new("RGB", CONTACT_CELL_SIZE, (255, 255, 255))
                tile_x = (cell_width - thumbnail.width) // 2
                tile_y = (cell_height - thumbnail.height) // 2
                tile.paste(thumbnail, (tile_x, tile_y))
                sheet.paste(tile, (x, y))
                label = str(number)
            except Exception:
                unreadable += 1
                draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1), fill=(255, 245, 245))
                draw.text((x + 8, y + 65), "图片读取失败", fill=(160, 0, 0), font=font)
                label = str(number)

            label_width, label_height = CONTACT_LABEL_SIZE
            draw.rectangle((x, y, x + label_width - 1, y + label_height - 1), fill=(0, 0, 0))
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            text_x = x + max(2, (label_width - text_width) // 2) - bbox[0]
            text_y = y + max(2, (label_height - text_height) // 2) - bbox[1]
            draw.text((text_x, text_y), label, fill=(255, 220, 0), font=font)

        sheet.save(sheet_path, format="JPEG", quality=90, optimize=True)
        generated += 1

    return output_dir, generated, unreadable


MANUAL_LABEL_PLATFORM_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>商品颜色识别与复核</title>
<style>
:root{color-scheme:dark;--bg:#101214;--panel:#191c20;--panel2:#22262b;--line:#343a42;--gold:#efc45c;--text:#eceef0;--muted:#a1a9b1;--green:#75d9a3;--blue:#8ebdff;--red:#f0a197}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI","Microsoft YaHei",sans-serif}button,input,select{font:inherit}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}.app{height:100vh;min-height:620px;display:grid;grid-template-columns:265px minmax(380px,1fr) 330px;gap:12px;padding:12px}.panel{min-height:0;overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:12px}.products,.colors,.work{display:flex;flex-direction:column}.head{padding:15px;border-bottom:1px solid var(--line)}h1,h2,p{margin:0}.head h1{font-size:17px}.head h2{font-size:16px}.muted{color:var(--muted);font-size:12px;margin-top:5px}.search,.filter{margin:9px 10px 0;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:#111416;color:var(--text)}.filter{margin-bottom:6px}.product-list,.color-list{flex:1;overflow:auto;padding:6px}.product{width:100%;text-align:left;background:transparent;border:1px solid transparent;border-radius:8px;color:var(--text);padding:10px;margin:2px 0}.product:hover{background:var(--panel2)}.product.active{background:#302a1b;border-color:#806a36}.product-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.product-meta{color:var(--muted);font-size:11px;margin-top:4px}.product-tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}.tag{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:1px 5px}.tag.auto_success{color:var(--blue);border-color:#526d94}.tag.auto_failed,.tag.pending,.tag.manual_pending{color:var(--gold);border-color:#806a36}.tag.manual_done,.tag.auto_confirmed{color:var(--green);border-color:#3c7857}.toolbar{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.product-heading{min-width:0;flex:1}.product-heading h2{font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.product-heading div{font-size:12px;color:var(--muted);word-break:break-all}.toolbar-actions,.actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.button,.small{background:var(--panel2);border:1px solid var(--line);color:var(--text);border-radius:7px;padding:7px 10px}.button:hover,.small:hover{border-color:var(--gold)}.button.primary{background:var(--gold);border-color:var(--gold);color:#171717;font-weight:700}.small{font-size:12px;padding:5px 8px}.recognition-bar{padding:10px 14px;border-bottom:1px solid var(--line);background:#15191d}.recognition-bar .actions{margin-bottom:8px}.job{font-size:12px;color:var(--muted)}progress{display:block;width:100%;height:6px;margin-top:8px;accent-color:var(--gold)}.notice{font-size:12px;color:var(--gold);padding:8px 14px;min-height:34px;border-bottom:1px solid var(--line);word-break:break-word}.sheet-scroll{flex:1;overflow:auto;padding:14px}.sheet{position:relative;width:100%;max-width:1400px;margin:auto;line-height:0}.sheet img{display:block;width:100%;height:auto}.hit-layer{position:absolute;inset:0}.hit{position:absolute;padding:0;border:0;background:transparent;cursor:pointer}.hit:hover{outline:3px solid var(--gold);background:#efc45c22}.hit.auto{outline:2px solid var(--blue);outline-offset:-2px}.hit.manual{outline:2px solid var(--green);outline-offset:-2px}.hit.suggested{border:3px dashed var(--gold)}.hit.selected{outline:4px solid var(--gold);outline-offset:-4px}.cell-label{position:absolute;left:3px;bottom:3px;background:#111e;color:var(--text);font-size:11px;line-height:1.4;padding:2px 5px;max-width:96%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-radius:4px}.empty{border:1px dashed var(--line);border-radius:9px;min-height:230px;display:grid;place-items:center;text-align:center;padding:24px;color:var(--muted)}.sheet-footer,.color-footer{padding:10px 14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}.color-card{padding:11px;margin:5px 0;border:1px solid var(--line);border-radius:9px;background:#15181b}.color-card.active{border-color:var(--gold);box-shadow:0 0 0 1px #efc45c33}.color-card.auto_success{border-left:3px solid var(--blue)}.color-card.auto_failed,.color-card.manual_pending{border-left:3px solid var(--gold)}.color-card.manual_done,.color-card.auto_confirmed{border-left:3px solid var(--green)}.color-row{display:flex;align-items:center;justify-content:space-between;gap:6px}.color-name{font-weight:650;word-break:break-word}.status-label{margin-top:7px;font-size:12px}.status-label.auto_success{color:var(--blue)}.status-label.auto_failed,.status-label.manual_pending,.status-label.pending{color:var(--gold)}.status-label.manual_done,.status-label.auto_confirmed{color:var(--green)}.value{font-size:11px;color:var(--muted);word-break:break-all;margin:7px 0}.reason{font-size:12px;color:var(--muted);margin:6px 0}.metrics{font-size:11px;color:var(--muted);margin-bottom:8px}.empty-list{padding:18px;color:var(--muted)}.path{word-break:break-all;font-size:11px;margin-top:7px}details summary{cursor:pointer}a{color:var(--blue)}@media(max-width:1100px){.app{grid-template-columns:220px minmax(350px,1fr);grid-template-rows:minmax(600px,1fr) 330px;height:auto;min-height:100vh}.colors{grid-column:1/3}.color-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}.toolbar-actions{width:100%}}@media(max-width:650px){.app{display:flex;flex-direction:column;height:auto}.products{max-height:300px}.work{min-height:600px}.colors{min-height:350px}}
</style></head><body><div class="app">
<aside class="panel products"><div class="head"><h1>商品颜色识别与复核</h1><div class="muted" id="stats">正在读取…</div></div><input id="search" class="search" placeholder="搜索商品名 / MD5"><select id="filter" class="filter" aria-label="按识别状态筛选"><option value="all">全部商品</option><option value="review">需要人工复核</option><option value="auto">自动识别成功 · 待确认</option><option value="failed">识别未成功</option><option value="pending">尚未识别 / 未绑定</option><option value="manual">人工已确认 / 已调整</option></select><div class="product-list" id="products"></div></aside>
<main class="panel work"><div class="toolbar"><div class="product-heading"><h2 id="title">选择商品</h2><div id="subtitle"></div></div><div class="toolbar-actions"><button class="button" id="prev">上一个</button><button class="button" id="next">下一个</button><button class="button" id="nextReview">下个待复核</button><button class="button" id="save">保存 JSON</button></div></div>
<div class="recognition-bar"><div class="actions"><button class="button primary" id="recognizeAll">本地识别全部</button><button class="button" id="recognizeOne">识别当前商品</button><button class="button" id="confirmAll">确认本商品识别结果</button></div><div class="job" id="job">使用本地图片识别；已有人工标注和人工确认结果将保留。</div><progress id="progress" max="1" value="0" hidden></progress></div>
<div class="notice" id="saveState" role="status" aria-live="polite">自动识别结果仍建议人工检查；蓝框为自动识别，绿框为人工确认，黄虚框为复核候选。</div>
<div class="sheet-scroll" id="sheetArea"><div class="empty">选择商品，运行本地识别；也可直接选颜色并点击图片。</div></div><div class="sheet-footer" id="sheetFooter">选颜色 → 点图片；每次修改自动保存。</div></main>
<aside class="panel colors"><div class="head"><h2>JSON 颜色选项</h2><div class="muted" id="colorHint">识别成功和未成功都可手动调整</div></div><div class="color-list" id="colorList"></div><div class="color-footer">自动识别成功会填入输出 JSON；未成功仅给候选，保留空值。原 JSON 保留。<details><summary>当前输出文件</summary><div class="path" id="outputPath"></div></details></div></aside></div>
<script>
let state=null,currentId=null,activeColor=null,query='',busy=false,loading=false,refreshChain=Promise.resolve();
const el=id=>document.getElementById(id);
const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(text){el('saveState').textContent=text}
async function request(path,body){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};const response=await fetch(path,options);const result=await response.json();if(!response.ok)throw Error(result.error||response.statusText);return result}
function selected(){return state?.products.find(p=>p.id===currentId)}
function count(p,key){return p.counts[key]||0}
function visibleProducts(){return (state?.products||[]).filter(p=>{if(query&&!(p.title+' '+p.md5).toLowerCase().includes(query))return false;switch(el('filter').value){case 'review':return p.review_count>0;case 'auto':return count(p,'auto_success')>0;case 'failed':return count(p,'auto_failed')>0;case 'pending':return p.pending>0;case 'manual':return count(p,'manual_done')+count(p,'auto_confirmed')>0;default:return true}})}
function tags(p){const pieces=[];if(count(p,'auto_success'))pieces.push('<span class="tag auto_success">识别成功 '+count(p,'auto_success')+'</span>');if(count(p,'auto_failed'))pieces.push('<span class="tag auto_failed">识别未成功 '+count(p,'auto_failed')+'</span>');const manual=count(p,'manual_done')+count(p,'auto_confirmed');if(manual)pieces.push('<span class="tag manual_done">人工完成 '+manual+'</span>');const pending=count(p,'pending')+count(p,'manual_pending');if(pending)pieces.push('<span class="tag pending">未绑定 '+pending+'</span>');return pieces.join('')||'<span class="tag">'+(p.colors.length?'原有链接':'无颜色选项')+'</span>'}
function renderList(){const box=el('products');const scroll=box.scrollTop;box.replaceChildren();if(!state)return;const visible=visibleProducts();for(const p of visible){const b=document.createElement('button');b.className='product'+(p.id===currentId?' active':'');b.innerHTML='<div class="product-title">'+esc(p.title||'(无标题)')+'</div><div class="product-meta">'+esc(p.md5||'无 MD5')+'</div><div class="product-tags">'+tags(p)+'</div>';b.onclick=()=>{currentId=p.id;activeColor=null;render()};box.append(b)}if(!visible.length)box.innerHTML='<div class="empty-list">没有符合条件的商品</div>';box.scrollTop=scroll;const t=state.totals;el('stats').textContent=state.products.length+' 个商品 · 自动待确认 '+(t.auto_success||0)+' 色 · 识别未成功 '+(t.auto_failed||0)+' 色 · 人工完成 '+((t.manual_done||0)+(t.auto_confirmed||0))+' 色'}
function selectColor(name){activeColor=name;renderColors(selected());renderSheet(selected());notice('当前选择：'+name+'；请点击对应图片，可直接改选尚未确认的自动结果')}
function renderColors(p){const box=el('colorList');const scroll=box.scrollTop;box.replaceChildren();el('colorHint').textContent=p.error||p.colors.length+' 个颜色 · '+p.review_count+' 项待复核';if(!p.colors.length){box.innerHTML='<div class="empty-list">该商品没有可编辑的 Color 对象</div>';return}for(const c of p.colors){const card=document.createElement('div');card.className='color-card '+c.status+(activeColor===c.name?' active':'');const d=c.detection||{};let extra='';if(d.reason)extra+='<div class="reason">'+(['manual_done','auto_confirmed','manual_pending'].includes(c.status)?'此前识别说明：':'识别说明：')+esc(d.reason)+'</div>';if(Number.isInteger(d.image_index))extra+='<div class="metrics">识别候选 #'+d.image_index+(Number.isFinite(d.delta_e)?' · 色差 '+d.delta_e:'')+(Number.isFinite(d.margin)?' · 区分度 '+d.margin:'')+'</div>';card.innerHTML='<div class="color-row"><div class="color-name">'+esc(c.name)+'</div><span>'+(c.assigned_index!==null?'#'+c.assigned_index:'')+'</span></div><div class="status-label '+c.status+'">'+esc(c.status_label)+'</div>'+extra+'<details class="value"><summary>'+(c.url?'查看已绑定 URL':'尚未绑定图片')+'</summary>'+esc(c.url||'未成功的候选不会写入 JSON')+'</details><div class="actions"><button class="small choose">'+(activeColor===c.name?'请点击图片':(c.url?'手动调整':'选择图片'))+'</button>'+(c.status==='auto_success'?'<button class="small confirm">确认识别</button>':'')+(c.status==='auto_failed'&&Number.isInteger(d.image_index)?'<button class="small accept">采用候选</button>':'')+(c.url?'<button class="small clear">清除</button>':'')+'</div>';card.querySelector('.choose').onclick=()=>selectColor(c.name);card.querySelector('.confirm')?.addEventListener('click',()=>confirm(c.name));card.querySelector('.accept')?.addEventListener('click',()=>assign(d.image_index,c.name));card.querySelector('.clear')?.addEventListener('click',()=>assign(null,c.name));box.append(card)}box.scrollTop=scroll}
function renderSheet(p){const area=el('sheetArea');const oldScroll=area.scrollTop;area.replaceChildren();if(!p.sheet_url||!p.cells.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=p.sheet_error||'该商品没有可用拼图';area.append(empty);el('sheetFooter').textContent='原始编号对应原 JSON 的 images 索引';return}const frame=document.createElement('div');frame.className='sheet';const img=document.createElement('img');img.src=p.sheet_url;img.alt='商品图片编号拼图';const layer=document.createElement('div');layer.className='hit-layer';const active=p.colors.find(c=>c.name===activeColor);for(const cell of p.cells){const hit=document.createElement('button');const owners=p.colors.filter(c=>c.assigned_index===cell.image_index);const owner=owners[0];const suggested=active?.status==='auto_failed'&&active.detection.image_index===cell.image_index;hit.className='hit'+(owner?(owner.status==='auto_success'?' auto':' manual'):'')+(suggested?' suggested':'')+(owner&&owner.name===activeColor?' selected':'');Object.assign(hit.style,{left:cell.left+'%',top:cell.top+'%',width:cell.width+'%',height:cell.height+'%'});hit.title='图片 '+cell.image_index+(owner?' · '+owner.name+' · '+owner.status_label:'');hit.setAttribute('aria-label',hit.title);if(owner){const label=document.createElement('span');label.className='cell-label';label.textContent=owner.name+' · '+(owner.status==='auto_success'?'自动':'人工确认');hit.append(label)}hit.onclick=()=>{if(activeColor===null){notice('先在右侧选择需要标注或调整的颜色');return}assign(cell.image_index,activeColor)};layer.append(hit)}frame.append(img,layer);area.append(frame);area.scrollTop=oldScroll;img.onerror=()=>{area.innerHTML='<div class="empty">拼图读取失败，请确认图片目录。</div>'};el('sheetFooter').textContent=p.cells.length+' 张图片 · '+(activeColor===null?'先选颜色，再点图片':'当前颜色：'+activeColor)+' · 蓝框自动 / 绿框人工 / 黄虚框候选'}
function renderJob(){if(!state)return;const j=state.job;el('progress').hidden=!j.running;el('progress').max=Math.max(j.total,1);el('progress').value=j.completed;el('job').textContent=j.error||(j.running?'正在识别 '+j.completed+'/'+j.total+' 商品 · '+j.current:(j.total?'识别完成 '+j.completed+'/'+j.total+' 商品，用时 '+j.elapsed+' 秒':'本地识别：保留人工标注、人工确认和人工清除；仅处理未确认颜色。'));el('recognizeAll').disabled=busy||j.running;el('recognizeOne').disabled=busy||j.running||!selected()?.colors.length;el('confirmAll').disabled=busy||!selected()?.colors.some(c=>c.status==='auto_success')}
function render(){renderList();renderJob();el('outputPath').textContent=state?.output||'';const p=selected();if(!p){el('title').textContent='选择商品';el('subtitle').textContent='';el('colorList').replaceChildren();return}el('title').textContent=p.title||'(无标题)';el('subtitle').textContent='MD5 '+p.md5+' · '+p.image_count+' 张原始图片';renderColors(p);renderSheet(p)}
function reload(keep){const task=refreshChain.catch(()=>{}).then(async()=>{loading=true;try{const oldRunning=state?.job.running;state=await request('/api/state');if(keep!==undefined&&state.products.some(p=>p.id===keep))currentId=keep;else if(currentId===null&&state.products.length)currentId=state.products[0].id;render();if(oldRunning&&!state.job.running)notice(state.job.error||'识别完成：可按左侧状态筛选，逐项确认或手动调整')}finally{loading=false}});refreshChain=task;return task}
async function mutate(path,payload,message){if(busy)return;busy=true;renderJob();notice('正在保存…');try{await request(path,payload);activeColor=null;await reload();notice(message)}catch(e){notice(e.message)}finally{busy=false;renderJob()}}
function assign(index,color){const p=selected();if(p)mutate('/api/assign',{id:p.id,color,image_index:index},'已自动保存；人工调整已记录')}
function confirm(color){const p=selected();if(p)mutate('/api/confirm',{id:p.id,...(color===null?{}:{color})},'已人工确认并保存')}
async function recognize(all){if(busy)return;busy=true;renderJob();try{await request('/api/recognize',all?{}:{id:currentId});await reload();notice(state.job.total?'识别任务已启动，可同时人工标注；人工结果优先':'没有待识别颜色；已有人工结果会保留')}catch(e){notice(e.message)}finally{busy=false;renderJob()}}
function move(delta,reviewOnly=false){const list=reviewOnly?state.products.filter(p=>p.review_count>0):visibleProducts();if(!list.length){notice('没有符合条件的待复核商品');return}let i=list.findIndex(p=>p.id===currentId);currentId=list[(i+delta+list.length)%list.length].id;activeColor=null;render()}
el('search').oninput=e=>{query=e.target.value.trim().toLowerCase();renderList()};el('filter').onchange=renderList;el('prev').onclick=()=>move(-1);el('next').onclick=()=>move(1);el('nextReview').onclick=()=>move(1,true);el('recognizeAll').onclick=()=>recognize(true);el('recognizeOne').onclick=()=>recognize(false);el('confirmAll').onclick=()=>confirm(null);el('save').onclick=()=>mutate('/api/save',{},'已保存 JSON 和识别复核进度');
reload().catch(e=>notice('读取失败：'+e.message));setInterval(()=>{if(state?.job.running&&!busy&&!loading)reload().catch(e=>notice(e.message))},1500);
</script></body></html>'''


class ManualLabelPlatform:
    """原始索引始终引用输入 JSON；识别来源和复核状态只写入进度侧车文件。"""

    def __init__(self, json_path: Path, images_root: Path, output_path: Path):
        self.json_path = json_path.resolve()
        self.images_root = images_root.resolve()
        self.output_path = output_path.resolve()
        self.progress_path = self.output_path.with_name(self.output_path.stem + '_progress.json')
        if self.json_path in {self.output_path, self.progress_path}:
            raise ValueError('输出文件或进度文件不能覆盖原 JSON')
        source_bytes = self.json_path.read_bytes()
        self.source_hash = hashlib.sha256(source_bytes).hexdigest()
        self.source_data = json.loads(source_bytes.decode('utf-8-sig'))
        if not isinstance(self.source_data, list):
            raise ValueError('商品 JSON 顶层必须是数组')
        self.assignments: dict[int, dict[str, int]] = {}
        self.origins: dict[int, dict[str, str]] = {}
        self.detections: dict[int, dict[str, dict[str, Any]]] = {}
        self.cleared: set[tuple[int, str]] = set()
        self.reviewed: set[tuple[int, str]] = set()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.feature_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self.job = {'running': False, 'total': 0, 'completed': 0, 'current': '', 'error': '', 'elapsed': 0}
        self._load_progress()

    def _product_colors(self, item: Any) -> tuple[dict[str, Any], str | None]:
        if not isinstance(item, dict):
            return {}, '商品数据不是对象'
        colors, error = _find_color_map(item.get('options'))
        return colors or {}, error

    def _load_progress(self) -> None:
        if not self.progress_path.is_file():
            if self.output_path.exists():
                raise ValueError('已有输出 JSON 但缺少进度文件；请恢复原进度文件或用 --output 指定新文件')
            return
        saved = json.loads(self.progress_path.read_text(encoding='utf-8-sig'))
        if not isinstance(saved, dict) or saved.get('source_sha256') != self.source_hash:
            raise ValueError('进度文件与输入 JSON 不匹配，请选择当初的原始 JSON，或用 --output 指定新文件')
        for product_id, colors in saved.get('assignments', {}).items():
            try:
                index = int(product_id)
            except (ValueError, TypeError):
                continue
            if not 0 <= index < len(self.source_data) or not isinstance(colors, dict):
                continue
            item = self.source_data[index]
            color_map, error = self._product_colors(item)
            images = item.get('images', []) if isinstance(item, dict) else []
            if error or not isinstance(images, list):
                continue
            for name, image_index in colors.items():
                if name not in color_map or type(image_index) is not int or not 0 <= image_index < len(images):
                    continue
                if not isinstance(images[image_index], str) or not images[image_index].strip():
                    continue
                self.assignments.setdefault(index, {})[name] = image_index
                origin = saved.get('origins', {}).get(str(index), {}).get(name, 'manual')
                # 旧版进度全为手工操作，不能把它们误标为自动识别。
                self.origins.setdefault(index, {})[name] = 'auto' if origin == 'auto' else 'manual'
        for key, target in (('cleared', self.cleared), ('reviewed', self.reviewed)):
            for entry in saved.get(key, []):
                if not isinstance(entry, list) or len(entry) != 2 or type(entry[0]) is not int:
                    continue
                index, name = entry
                if 0 <= index < len(self.source_data) and isinstance(name, str):
                    color_map, _ = self._product_colors(self.source_data[index])
                    if name in color_map:
                        target.add((index, name))
        for product_id, colors in saved.get('detections', {}).items():
            try:
                index = int(product_id)
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(self.source_data) or not isinstance(colors, dict):
                continue
            color_map, _ = self._product_colors(self.source_data[index])
            for name, info in colors.items():
                if name in color_map and isinstance(info, dict):
                    self.detections.setdefault(index, {})[name] = info
        for index, name in self.cleared:
            self.assignments.get(index, {}).pop(name, None)
            self.origins.get(index, {}).pop(name, None)

    def _progress_payload(self) -> dict[str, Any]:
        return {
            'version': 2, 'source_sha256': self.source_hash,
            'assignments': {str(index): values for index, values in self.assignments.items()},
            'origins': {str(index): values for index, values in self.origins.items()},
            'detections': {str(index): values for index, values in self.detections.items()},
            'cleared': [list(pair) for pair in sorted(self.cleared)],
            'reviewed': [list(pair) for pair in sorted(self.reviewed)],
        }

    def _color_state(self, product_id: int, name: str) -> dict[str, Any]:
        item = self.source_data[product_id]
        colors, _ = self._product_colors(item)
        images = item.get('images', []) if isinstance(item.get('images'), list) else []
        original_url = colors[name] if isinstance(colors[name], str) else ''
        index = self.assignments.get(product_id, {}).get(name)
        origin = self.origins.get(product_id, {}).get(name, 'manual')
        detection = self.detections.get(product_id, {}).get(name, {})
        url = original_url
        status = 'existing' if url.strip() else 'pending'
        if index is not None:
            url = images[index]
            if origin == 'auto':
                status = 'auto_confirmed' if (product_id, name) in self.reviewed else 'auto_success'
            else:
                status = 'manual_done'
        else:
            index = next((i for i, value in enumerate(images) if value == original_url and original_url.strip()), None)
        if (product_id, name) in self.cleared:
            url, index, status = '', None, 'manual_pending'
        elif not url.strip() and detection:
            status = 'auto_failed'
        labels = {'existing': '原有链接', 'pending': '尚未识别', 'auto_success': '自动识别成功 · 待确认',
                  'auto_confirmed': '自动识别 · 人工已确认', 'manual_done': '人工已调整' if detection else '人工已标注',
                  'manual_pending': '人工已清除 · 待标注', 'auto_failed': '识别未成功 · 待人工复核'}
        return {'name': name, 'url': url, 'assigned_index': index, 'status': status,
                'status_label': labels[status], 'needs_review': status in {'pending', 'auto_failed', 'manual_pending', 'auto_success'},
                'detection': detection}

    def _cells(self, folder: Path, images: list[Any]) -> list[dict[str, Any]]:
        if not folder.is_dir():
            return []
        files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and p.stem.isdecimal()),
                       key=lambda p: (int(p.stem), p.name.casefold()))
        width, height = CONTACT_CELL_SIZE
        sheet_width = CONTACT_SHEET_COLUMNS * width + (CONTACT_SHEET_COLUMNS + 1) * CONTACT_GAP
        rows = (len(files) + CONTACT_SHEET_COLUMNS - 1) // CONTACT_SHEET_COLUMNS
        sheet_height = rows * height + (rows + 1) * CONTACT_GAP
        cells = []
        for position, path in enumerate(files):
            image_index = int(path.stem)
            if image_index >= len(images) or not isinstance(images[image_index], str) or not images[image_index].strip():
                continue
            row, column = divmod(position, CONTACT_SHEET_COLUMNS)
            cells.append({'image_index': image_index,
                          'left': (CONTACT_GAP + column * (width + CONTACT_GAP)) / sheet_width * 100,
                          'top': (CONTACT_GAP + row * (height + CONTACT_GAP)) / sheet_height * 100,
                          'width': width / sheet_width * 100, 'height': height / sheet_height * 100})
        return cells

    def state(self) -> dict[str, Any]:
        with self.lock:
            products = []
            totals = Counter()
            for product_id, item in enumerate(self.source_data):
                if not isinstance(item, dict):
                    continue
                colors_map, error = self._product_colors(item)
                colors = [self._color_state(product_id, name) for name in colors_map]
                counts = Counter(color['status'] for color in colors)
                totals.update(counts)
                md5 = str(item.get('md5') or '')
                images = item.get('images') if isinstance(item.get('images'), list) else []
                folder = _safe_product_folder(self.images_root, md5)
                cells = self._cells(folder, images) if folder else []
                sheet_error = ''
                try:
                    self.sheet_path(product_id)
                    sheet_url = '/api/sheet?id=' + str(product_id)
                except (OSError, ValueError):
                    sheet_url = None
                if not folder or not folder.is_dir():
                    sheet_error = 'MD5 图片文件夹不存在；请先运行 download_images.py。'
                elif not cells:
                    sheet_error = '此商品没有可用的编号图片。'
                elif not sheet_url:
                    sheet_error = '拼图不存在；重启平台会生成。'
                products.append({'id': product_id, 'md5': md5, 'title': str(item.get('title') or ''), 'colors': colors,
                                 'pending': sum(not c['url'].strip() for c in colors), 'counts': dict(counts),
                                 'review_count': sum(c['needs_review'] for c in colors),
                                 'image_count': len(images), 'cells': cells, 'sheet_url': sheet_url,
                                 'sheet_error': sheet_error, 'error': error})
            return {'products': products, 'output': str(self.output_path), 'totals': dict(totals), 'job': dict(self.job)}

    def _build_output(self) -> list[Any]:
        result = copy.deepcopy(self.source_data)
        changed_ids = set(self.assignments) | {index for index, _ in self.cleared}
        for product_id in changed_ids:
            item = result[product_id]
            colors, error = self._product_colors(item)
            if error:
                continue
            original = self.source_data[product_id]
            original_colors, _ = self._product_colors(original)
            images = original.get('images')
            for name in colors:
                if (product_id, name) in self.cleared:
                    colors[name] = ''
                elif name in self.assignments.get(product_id, {}):
                    colors[name] = images[self.assignments[product_id][name]]
            final_urls = {value for value in colors.values() if isinstance(value, str) and value.strip()}
            remaining = [url for url in images if not isinstance(url, str) or url not in final_urls] if isinstance(images, list) else None
            # 更改已有链接时，退回原来只存在于 Color 的图片，防止无声丢失。
            returned = [value for name, value in original_colors.items()
                        if isinstance(value, str) and value.strip() and value != colors[name] and value not in final_urls]
            if remaining is not None:
                for value in returned:
                    if value not in remaining:
                        remaining.append(value)
                item['images'] = remaining
        return result

    def save(self) -> None:
        with self.lock:
            _atomic_json(self.output_path, self._build_output())
            _atomic_json(self.progress_path, self._progress_payload())

    def _validate_product(self, product_id: int, color: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        if type(product_id) is not int or not 0 <= product_id < len(self.source_data):
            raise ValueError('商品序号无效')
        item = self.source_data[product_id]
        colors, error = self._product_colors(item)
        if error or (color is not None and color not in colors):
            raise ValueError('颜色选项不存在，或该商品没有可编辑的 Color 对象')
        return item, colors

    def assign(self, product_id: int, color: str, image_index: int | None) -> None:
        with self.lock:
            item, colors = self._validate_product(product_id, color)
            if image_index is not None:
                images = item.get('images')
                if not isinstance(images, list) or type(image_index) is not int or not 0 <= image_index < len(images):
                    raise ValueError('图片序号超出原 JSON images 数组范围')
                url = images[image_index]
                if not isinstance(url, str) or not url.strip():
                    raise ValueError('该序号没有有效的原始图片 URL')
                folder = _safe_product_folder(self.images_root, item.get('md5'))
                _, issue = _image_for_index(folder, image_index) if folder else (None, 'MD5 图片文件夹不存在')
                if issue:
                    raise ValueError(issue)
                conflicts = [self._color_state(product_id, name) for name in colors if name != color]
                for other in conflicts:
                    if other['url'] == url and other['status'] != 'auto_success':
                        raise ValueError(f'此图片已绑定到 {other["name"]}；请先清除该颜色的绑定')
                # 未确认的自动结果让位于人工选择；已确认结果不会被静默覆盖。
                for other in conflicts:
                    if other['url'] == url:
                        name = other['name']
                        self.assignments.get(product_id, {}).pop(name, None)
                        self.origins.get(product_id, {}).pop(name, None)
                        self.detections.setdefault(product_id, {})[name] = {
                            **other['detection'], 'status': 'review', 'reason': '候选图片已被人工分配给其他颜色，请复核'}
            self.assignments.setdefault(product_id, {}).pop(color, None)
            self.origins.setdefault(product_id, {}).pop(color, None)
            if image_index is None:
                self.cleared.add((product_id, color))
                self.reviewed.discard((product_id, color))
            else:
                self.assignments[product_id][color] = image_index
                self.origins[product_id][color] = 'manual'
                self.reviewed.add((product_id, color))
                self.cleared.discard((product_id, color))
            self.save()

    def confirm(self, product_id: int, color: str | None = None) -> int:
        with self.lock:
            _, colors = self._validate_product(product_id, color)
            names = [color] if color is not None else list(colors)
            confirmed = [name for name in names if self._color_state(product_id, name)['status'] == 'auto_success']
            if not confirmed:
                raise ValueError('没有待确认的自动识别结果')
            self.reviewed.update((product_id, name) for name in confirmed)
            self.save()
            return len(confirmed)

    def _eligible(self, product_id: int) -> list[str]:
        colors, error = self._product_colors(self.source_data[product_id])
        if error:
            return []
        return [name for name in colors if self._color_state(product_id, name)['status'] in {'pending', 'auto_failed', 'auto_success'}]

    def start_recognition(self, product_id: int | None = None) -> None:
        with self.lock:
            if self.job['running']:
                raise ValueError('已有识别任务在运行，请等待完成')
            if product_id is not None:
                self._validate_product(product_id)
            ids = [product_id] if product_id is not None else list(range(len(self.source_data)))
            ids = [index for index in ids if self._eligible(index)]
            self.job = {'running': bool(ids), 'total': len(ids), 'completed': 0, 'current': '', 'error': '', 'elapsed': 0}
            if not ids:
                return
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run_recognition, args=(ids,), daemon=True, name='local-color-recognition')
            self.worker.start()

    def _run_recognition(self, ids: list[int]) -> None:
        started = time.monotonic()
        try:
            for product_id in ids:
                if self.stop_event.is_set():
                    break
                item = self.source_data[product_id]
                with self.lock:
                    self.job['current'] = str(item.get('title') or item.get('md5') or '')
                self._recognize_one(product_id)
                with self.lock:
                    self.job['completed'] += 1
                    self.job['elapsed'] = round(time.monotonic() - started, 1)
        except Exception as exc:
            with self.lock:
                self.job['error'] = f'识别中止：{exc}；可继续人工标注或重新识别'
        finally:
            with self.lock:
                self.job['running'] = False
                self.job['elapsed'] = round(time.monotonic() - started, 1)

    def _recognize_one(self, product_id: int) -> None:
        item = self.source_data[product_id]
        images = item.get('images') if isinstance(item.get('images'), list) else []
        folder = _safe_product_folder(self.images_root, item.get('md5'))
        features = {}
        for index, url in enumerate(images):
            if self.stop_event.is_set():
                return
            if not isinstance(url, str) or not url.strip():
                continue
            path, issue = _image_for_index(folder, index) if folder else (None, 'MD5 图片文件夹不存在')
            if issue or path is None:
                features[index] = {'error': issue or '图片文件不存在'}
                continue
            try:
                stat = path.stat()
                key = (str(path), stat.st_mtime_ns, stat.st_size)
                if key not in self.feature_cache:
                    self.feature_cache[key] = extract_features(path)
                features[index] = self.feature_cache[key]
            except (OSError, ValueError) as exc:
                features[index] = {'error': f'图片无法读取：{exc}'}
        with self.lock:
            if self.stop_event.is_set():
                return
            colors, _ = self._product_colors(item)
            eligible = self._eligible(product_id)
            if not eligible:
                return
            reserved = {self._color_state(product_id, name)['url'] for name in colors if name not in eligible}
            detections = recognize_product(list(colors), features, reserved, images, targets=eligible)
            # 重算只替换尚未人工确认的自动结果；原索引和人工状态始终不动。
            for name in eligible:
                self.assignments.get(product_id, {}).pop(name, None)
                self.origins.get(product_id, {}).pop(name, None)
                info = detections[name]
                self.detections.setdefault(product_id, {})[name] = info
                if info['status'] == 'success':
                    self.assignments.setdefault(product_id, {})[name] = info['image_index']
                    self.origins.setdefault(product_id, {})[name] = 'auto'
            self.save()

    def sheet_path(self, product_id: int) -> Path:
        if type(product_id) is not int or not 0 <= product_id < len(self.source_data):
            raise ValueError('商品序号无效')
        item = self.source_data[product_id]
        md5 = item.get('md5') if isinstance(item, dict) else None
        folder = _safe_product_folder(self.images_root, md5)
        if folder is None:
            raise ValueError('MD5 图片文件夹无效')
        contact_root = (self.images_root / '_contact_sheets').resolve()
        path = (contact_root / (str(md5) + '.jpg')).resolve()
        if not path.is_relative_to(contact_root) or not path.is_file():
            raise FileNotFoundError('拼图不存在')
        return path


def _make_handler(platform: ManualLabelPlatform):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ColorLabel/1.0"

        def _json(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = MANUAL_LABEL_PLATFORM_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/state":
                with platform.lock:
                    self._json(platform.state())
                return
            if parsed.path == "/api/sheet":
                try:
                    product_id = int(parse_qs(parsed.query).get("id", [""])[0])
                    with platform.lock:
                        path = platform.sheet_path(product_id)
                        body = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(body)
                except (ValueError, FileNotFoundError, OSError) as exc:
                    self._json({"error": str(exc)}, 404)
                return
            self._json({"error": "接口不存在"}, 404)

        def do_POST(self) -> None:
            if self.path not in {"/api/assign", "/api/save", "/api/recognize", "/api/confirm"}:
                self._json({"error": "接口不存在"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1024 * 1024:
                    raise ValueError("请求内容过大")
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                if not isinstance(payload, dict):
                    raise ValueError("请求格式无效")
                if self.path == "/api/assign":
                    product_id = payload.get("id")
                    color = payload.get("color")
                    image_index = payload.get("image_index")
                    if type(product_id) is not int or not isinstance(color, str):
                        raise ValueError("商品或颜色参数无效")
                    if image_index is not None and type(image_index) is not int:
                        raise ValueError("图片序号参数无效")
                    with platform.lock:
                        platform.assign(product_id, color, image_index)
                    self._json({"ok": True})
                elif self.path == "/api/recognize":
                    product_id = payload.get("id")
                    if product_id is not None and type(product_id) is not int:
                        raise ValueError("商品序号无效")
                    platform.start_recognition(product_id)
                    self._json({"ok": True})
                elif self.path == "/api/confirm":
                    product_id = payload.get("id")
                    color = payload.get("color")
                    if type(product_id) is not int or (color is not None and not isinstance(color, str)):
                        raise ValueError("商品或颜色参数无效")
                    confirmed = platform.confirm(product_id, color)
                    self._json({"ok": True, "confirmed": confirmed})
                else:
                    with platform.lock:
                        platform.save()
                    self._json({"ok": True, "output": str(platform.output_path)})
            except (ValueError, json.JSONDecodeError, OSError) as exc:
                self._json({"error": str(exc)}, 400)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="本地颜色识别、人工复核与标注商品 Color 图片")
    parser.add_argument("json_file", nargs="?", type=Path, help="商品 JSON 文件")
    parser.add_argument("images_dir_pos", nargs="?", type=Path, help="图片目录；默认 JSON 同目录下的 images/")
    parser.add_argument("--images-dir", type=Path, help="指定图片目录")
    parser.add_argument("--output", type=Path, help="输出 JSON；默认 <原文件名>_manual_labeled.json")
    args = parser.parse_args()
    if args.images_dir and args.images_dir_pos:
        parser.error("图片目录请只用位置参数或 --images-dir 指定一次")
    images_dir = args.images_dir or args.images_dir_pos

    if args.json_file is None:
        try:
            pasted_json = _clean_pasted_path(input("请粘贴商品 JSON 文件路径："))
            if not pasted_json:
                print("未提供 JSON 文件路径，已退出。")
                return 2
            pasted_images = ("" if images_dir is not None else _clean_pasted_path(
                input("请粘贴图片文件夹路径（直接回车使用 JSON 同目录下的 images）：")))
        except (EOFError, KeyboardInterrupt):
            print("输入已取消。")
            return 130
        json_file = Path(pasted_json)
        if pasted_images:
            images_dir = Path(pasted_images)
    else:
        json_file = args.json_file

    json_path = Path(_clean_pasted_path(str(json_file))).expanduser().resolve()
    if not json_path.is_file():
        parser.error(f"JSON 文件不存在：{json_path}")
    images_root = Path(_clean_pasted_path(str(images_dir or json_path.parent / "images"))).expanduser().resolve()
    if not images_root.is_dir():
        parser.error(f"图片目录不存在：{images_root}；请先运行 download_images.py")
    output_path = Path(_clean_pasted_path(str(
        args.output or json_path.with_name(json_path.stem + "_manual_labeled.json")))).expanduser().resolve()
    if output_path == json_path:
        parser.error("输出 JSON 不能覆盖原文件")

    try:
        platform = ManualLabelPlatform(json_path, images_root, output_path)
        print("正在检查并生成缺失或过期的商品拼图…")
        _contact_dir, sheet_count, unreadable_count = create_contact_sheets(images_root)
        if unreadable_count:
            print(f"拼图中有 {unreadable_count} 张图片读取失败，已标出。")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"启动失败：{exc}")
        return 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(platform))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"商品数：{len(platform.source_data)}；本次新生成拼图：{sheet_count}")
    print(f"标注结果将自动保存到：{output_path}")
    print(f"进度文件：{platform.progress_path}")
    print(f"标注平台已启动：{url}")
    print("在页面点击“本地识别全部”，按状态筛选后确认或手动调整；每次修改自动保存。")
    print("按 Ctrl+C 关闭平台。")
    threading.Timer(0.4, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n正在关闭标注平台…")
    finally:
        platform.stop_event.set()
        if platform.worker is not None:
            platform.worker.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
