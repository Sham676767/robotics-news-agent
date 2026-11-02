"""Uppercase timed karaoke with hard cuts and source-bound emphasis cards."""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

from app.caption_phrases import CaptionPhrase, dangling, starts_particle
from app.reel_script import ReelScript
from app.render_inputs import RenderAudio
from app.render_template import RenderTemplate
from app.render_subtitles import ass_header, color, escape_ass, stamp
from app.tts import WordTiming
from app.typography import layout


def clean(text: str) -> str:
    return text.strip('.,:;!?…—–«»"').upper()


def cinematic_phrases(words: tuple[WordTiming, ...], emphasis: tuple[str, ...], theme: RenderTemplate) -> tuple[tuple[CaptionPhrase, bool], ...]:
    spans = {}
    for fragment in emphasis:
        tokens = [clean(word) for word in fragment.split()]
        for i in range(len(words)-len(tokens)+1):
            if [clean(w.word) for w in words[i:i+len(tokens)]] == tokens:
                spans[i] = i+len(tokens)
                break
        else:
            raise ValueError('Emphasis must match complete spoken words')
    @lru_cache(None)
    def best(start: int):
        if start == len(words):return (0, ())
        if starts_particle(words[start].word):return None
        choices=[]
        ends = [spans[start]] if start in spans else range(start+2,min(start+4,len(words))+1)
        for end in ends:
            if dangling(words[end-1].word) or any(start < a < end or a < start < b for a,b in spans.items()):continue
            phrase=CaptionPhrase(words[start:end]);large=start in spans
            try: layout(clean(phrase.text),theme.font,120 if large else 60,120 if large else 60,840,440 if large else 350,max_lines=3)
            except ValueError:continue
            rest=best(end)
            if rest is None:continue
            score=rest[0]+abs(end-start-3)*.2-sum(words[end-1].word.endswith(p) for p in ('.',',','?','!'))
            choices.append((score,((phrase,large),)+rest[1]))
        return min(choices,key=lambda item:item[0]) if choices else None
    result=best(0)
    if result is None:raise ValueError('Cannot split cinematic captions into safe 2–4-word phrases; shorten emphasis or speech')
    return result[1]


def cinematic_subtitles(script: ReelScript, audio: RenderAudio, theme: RenderTemplate, *, brand_handle: str, stub: bool,
                        logo: bool = False, cta_keyword: str = "") -> tuple[str, list[dict]]:
    header=ass_header(theme).replace(',3,18,0,5,', ',1,2,1,5,')
    events,records=[],[]
    emphasis=script.editorial.emphasis if script.editorial else ()
    for index,(phrase,large) in enumerate(cinematic_phrases(audio.words,emphasis,theme)):
        text=clean(phrase.text)
        size=120 if large else 60
        y=760+(index%3)*35
        _,lines=layout(text,theme.font,size,size,840,440 if large else 350,max_lines=3)
        tokens=text.split();cursor=0;rendered=[]
        for line in lines:
            row=[]
            for i in range(cursor,cursor+len(line.split())):
                word=phrase.words[i]
                delay=round((word.start-phrase.start)*1000);end=round((word.end-phrase.start)*1000)
                rgb=color(theme.accent_color) if large or (cta_keyword and clean(word.word) == clean(cta_keyword)) else '&H00FFFFFF'
                row.append(rf'{{\1c{rgb}\1a&H66&\t({delay},{delay+1},\1a&H00&)\t({end},{end+1},\1a&H08&)}}'+escape_ass(tokens[i]))
            rendered.append(' '.join(row));cursor+=len(line.split())
        tags=rf'{{\an7\pos(90,{y})\clip(90,720,930,1320)\fs{size}\bord2\shad1}}'
        events.append(f'Dialogue: 2,{stamp(phrase.start)},{stamp(phrase.end)},Caption,,0,0,0,,{tags}'+r'\N'.join(rendered)+'\n')
        records.append({'kind':'emphasis' if large else 'caption','start':phrase.start,'end':phrase.end,'text':text,
                        'bounds':[90,y,930,min(1320,y+(440 if large else 350))],'font_size':size,
                        'karaoke':True,'words':[asdict(w) for w in phrase.words]})
    if brand_handle:
        for start,end,x,y,size in ((0,audio.duration,180 if logo else 90,300,28),(audio.duration,audio.duration+1.5,540,1060,42)):
            size, brand_lines = layout(brand_handle,theme.font,size,24,750 if logo and start == 0 else 840,160,max_lines=2)
            brand_text = r'\N'.join(escape_ass(line) for line in brand_lines)
            events.append(f'Dialogue: 4,{stamp(start)},{stamp(end)},Expert,,0,0,0,,'+
                          rf'{{\an{7 if start == 0 else 5}\pos({x},{y})\clip(90,250,930,1520)\fs{size}\1c&HFFFFFF&}}'+brand_text+'\n')
            records.append({'kind':'brand','start':start,'end':end,'text':brand_handle,'bounds':[90,250,930,1520]})
    if stub:
        events.append(f'Dialogue: 5,0:00:00.00,{stamp(audio.duration)},Header,,0,0,0,,'+
                      r'{\an7\pos(90,400)\fs28\bord2\clip(90,250,930,1520)}ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ'+'\n')
        records.append({'kind':'stub_notice','start':0,'end':audio.duration,'text':'ТЕСТ: ВЫМЫШЛЕННЫЕ РЕКВИЗИТЫ','bounds':[90,390,930,460]})
    return header+''.join(events),records
