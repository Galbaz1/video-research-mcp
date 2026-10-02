"""A self-contained first-party lesson page with state-derived SVG and own glyph cells."""

import base64
import json

from .education_domain import CAPTION_BOX, DIAGRAM_BOX, caption_lines, primitives
from .education_frames import TITLES
from .education_glyphs import PATTERNS, cells


def _label(text):
    """Use the same authored cell rectangles for visible page controls."""
    marks = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for x, y, w, h in cells(text, scale=1))
    return f'<svg role="img" aria-label="{text}" viewBox="0 0 {len(text) * 6} 9">{marks}</svg>'


def page_bytes(spec, audio):
    """Embed admitted source data, WAV and graphics; no URL, package, font or CDN dependencies."""
    data = {"spec": spec.model_dump(mode="json"), "glyphs": PATTERNS, "titles": TITLES,
            "primitives": [primitives(s) for s in spec.storyboard.scenes],
            "captions": [caption_lines(c.text) for c in spec.script.captions],
            "diagram_box": DIAGRAM_BOX, "caption_box": CAPTION_BOX}
    payload = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    controls = "".join(f'<button id="scene-{s.id}" data-scene="{i}" aria-label="Scene {s.id}">{_label(s.id.upper())}</button>'
                       for i, s in enumerate(spec.storyboard.scenes))
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Verifying a diagram against its rule</title>'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><style>'
            'body{margin:24px;background:#182030;color:#eef4fa}main{max-width:640px;margin:auto}'
            'svg{display:block;width:100%;fill:#eef4fa}button{background:#182030;border:2px solid #48ccbc;padding:8px;min-width:90px}'
            'button[aria-pressed=true]{background:#304050}button svg{height:18px}nav{display:flex;gap:8px;flex-wrap:wrap}'
            'label{display:block;margin-top:12px}label svg{height:18px;width:360px;max-width:100%}input[type=range]{width:100%}'
            'output svg{height:26px}#samples svg{height:22px}audio{display:none}</style><main>'
            '<svg id="lesson" role="img" viewBox="0 0 640 360" aria-label="Lesson scene"></svg><nav>' + controls +
            f'<button id="reset" aria-label="Reset">{_label("RESET")}</button>'
            f'<button id="play" aria-label="Play supplied audio">{_label("PLAY")}</button></nav>'
            f'<label for="seek">{_label("SEEK SECONDS")}<input id="seek" type="range" min="0" max="6" step="0.0833333333333333" value="0"></label>'
            '<output id="position" aria-live="polite"></output>'
            f'<label for="input-reflection">{_label("INPUT REFLECTION")}<input id="input-reflection" type="checkbox" checked></label>'
            f'<label for="shift">{_label("SHIFT H: -1 TO 1")}<input id="shift" type="range" min="-1" max="1" step="1" value="0"></label>'
            '<output id="equation" aria-live="polite"></output><section id="samples" aria-label="Current numeric sample values"></section>'
            f'<div>{_label("VIEWPORT X=-2..2 Y=0..4 MAY CLIP")}</div>'
            f'<audio id="narration" preload="metadata" src="data:audio/wav;base64,{base64.b64encode(audio).decode()}"></audio>'
            f'<script id="lesson-data" type="application/json">{payload}</script><script>')
    return (html + SCRIPT + '</script></main></html>').encode()


SCRIPT = r"""
'use strict';
const data=JSON.parse(document.getElementById('lesson-data').textContent);
const state={seconds:0,reflection:true,shift:0};
const node=id=>document.getElementById(id), audio=node('narration');
const ns='http://www.w3.org/2000/svg';
function element(tag,attrs){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));return e;}
function glyphs(text,x,y,scale=2){const g=element('g',{'aria-label':text});for(let i=0;i<text.length;i++){const rows=data.glyphs[text[i].toUpperCase()].split('/');rows.forEach((row,r)=>{[...row].forEach((bit,c)=>{if(bit==='1')g.append(element('rect',{x:x+(i*6+c)*scale,y:y+r*scale,width:scale,height:scale,fill:'#eef4fa'}));});});}return g;}
function value(x){return ((state.reflection?-1:1)*(x-state.shift))**2;}
function equation(){let inner=state.shift===0?'x':`x ${state.shift>0?'-':'+'} ${Math.abs(state.shift)}`;if(state.reflection)inner=state.shift===0?'-x':`-(${inner})`;return `y = ${inner==='x'?'x':`(${inner})`}^2`;}
function readout(id,text){const root=node(id);root.replaceChildren();root.setAttribute('aria-label',text);root.dataset.value=text;const svg=element('svg',{viewBox:`0 0 ${text.length*12} 18`,role:'img','aria-label':text});svg.append(glyphs(text,0,0));root.append(svg);}
function draw(){
 const index=Math.min(2,Math.floor(state.seconds/2)), scene=data.spec.storyboard.scenes[index], svg=node('lesson');
 svg.replaceChildren();svg.dataset.scene=scene.id;svg.dataset.seconds=String(state.seconds);svg.setAttribute('aria-label',`${scene.id} at ${state.seconds.toFixed(2)} seconds`);
 svg.append(element('rect',{x:0,y:0,width:640,height:360,fill:'#182030'}));
 const defs=element('defs',{}),clip=element('clipPath',{id:'viewport'});clip.append(element('rect',{x:48,y:54,width:544,height:204}));defs.append(clip);svg.append(defs);
 const diagram=element('g',{'clip-path':'url(#viewport)'});
 for(const primitive of data.primitives[index]){
  const points=index===1&&primitive.kind==='curve'?Array.from({length:33},(_,i)=>{const x=-2+i/8;return [320+80*x,240-40*value(x)];}):primitive.points;
  diagram.append(element('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#48ccbc','stroke-width':3}));
 }
 svg.append(diagram);svg.append(glyphs(data.titles[index],48,16));svg.append(glyphs(index===1?equation():scene.equation,48,36));
 svg.append(element('rect',{x:24,y:282,width:592,height:60,fill:'none',stroke:'#48ccbc','stroke-width':2}));
 data.captions[index].forEach((line,i)=>svg.append(glyphs(line,40,294+i*20)));
 if(index===0){[['A',60,224],['B',330,224],['C',330,60]].forEach(v=>svg.append(glyphs(...v)));}
 node('seek').value=String(state.seconds);node('input-reflection').checked=state.reflection;node('shift').value=String(state.shift);
 document.querySelectorAll('[data-scene]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.scene)===index)));
 readout('position',`SCENE ${scene.id.toUpperCase()} TIME ${state.seconds.toFixed(2)}`);readout('equation',equation());
 const samples=[-1,0,1].map(x=>({x,y:value(x)}));node('samples').replaceChildren();node('samples').dataset.points=JSON.stringify(samples);
 for(const point of samples){const output=document.createElement('output');output.setAttribute('aria-label',`X=${point.x} Y=${point.y}`);const s=element('svg',{viewBox:'0 0 180 18'});s.append(glyphs(`X=${point.x} Y=${point.y}`,0,0));output.append(s);node('samples').append(output);}
}
function seek(seconds){state.seconds=Math.max(0,Math.min(6,Number(seconds)));if(audio.readyState>=1)audio.currentTime=state.seconds;draw();}
document.querySelectorAll('[data-scene]').forEach(b=>b.addEventListener('click',()=>seek(Number(b.dataset.scene)*2)));
node('seek').addEventListener('input',e=>seek(e.target.value));
node('input-reflection').addEventListener('change',e=>{state.reflection=e.target.checked;draw();});
node('shift').addEventListener('input',e=>{state.shift=Number(e.target.value);draw();});
node('reset').addEventListener('click',()=>{audio.pause();state.reflection=true;state.shift=0;seek(0);});
node('play').addEventListener('click',()=>{if(audio.paused)audio.play().catch(()=>node('play').setAttribute('aria-label','Supplied audio playback unavailable'));else audio.pause();});
audio.addEventListener('loadedmetadata',()=>{audio.currentTime=state.seconds;});
audio.addEventListener('timeupdate',()=>{state.seconds=audio.currentTime;draw();});
draw();
"""
