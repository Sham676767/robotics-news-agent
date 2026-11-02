"""Locked-camera effects and branded ending; image generation never happens here."""
from __future__ import annotations

from pathlib import Path


def video_graph(duration: float, fire_box: tuple[float, ...], light_box: tuple[float, ...], *, logo: bool) -> str:
    x,y,w,h=(round(value*size) for value,size in zip(fire_box,(1080,1920,1080,1920)))
    lx,ly,lw,lh=(round(value*size) for value,size in zip(light_box,(1080,1920,1080,1920)))
    graph=("[0:v]scale=1080:1920:force_original_aspect_ratio=increase:out_range=tv,crop=1080:1920,setsar=1,fps=30,"
           "eq=gamma=1.12,vignette=PI/14,format=gbrp[scene];"
           "[3:v]scale=1080:1920,format=gbrp[dust];[scene][dust]blend=all_mode=screen:all_opacity=0.22[dusted];"
           "[5:v]split=2[firemask][lightmask];"
           f"[4:v]scale={w}:{h},format=rgb24[fire];[firemask]scale={w}:{h},format=gray[mask];"
           "[fire][mask]alphamerge[flame];"
           "color=black:s=1080x1920:r=30,format=rgb24[canvas];"
           f"[canvas][flame]overlay={x}:{y}:shortest=1:format=rgb,format=gbrp[fireframe];"
           "[dusted][fireframe]blend=all_mode=screen:all_opacity=0.18[firelit];"
           f"[firelit]split[base][patch];[patch]crop={lw}:{lh}:{lx}:{ly},"
           "eq=brightness='0.015*sin(2*PI*t/3)':eval=frame,format=rgb24[lit];"
           f"[lightmask]scale={lw}:{lh},format=gray[soft];[lit][soft]alphamerge[light];"
           f"[base][light]overlay={lx}:{ly}:shortest=1:format=rgb,format=gbrp,split=2[original][fade];"
           f"[fade]fade=t=out:st={duration-1.5:.6f}:d=1.5[faded];"
           "[original][faded]blend=all_expr='A*0.25+B*0.75',format=yuv420p,setparams=range=limited,ass=subtitles.ass:fontsdir=fonts[text];")
    if logo:
        graph+=("[6:v]split=2[small][large];[small]scale=70:70:force_original_aspect_ratio=decrease[s];"
                "[large]scale=180:180:force_original_aspect_ratio=decrease[l];"
                f"[text][s]overlay=90:300:enable='lt(t,{duration-1.5:.6f})'[watermarked];"
                f"[watermarked][l]overlay=(W-w)/2:820:enable='gte(t,{duration-1.5:.6f})'[v];")
    else:
        graph+='[text]null[v];'
    return graph


def overlay_inputs(root: Path) -> list[str]:
    paths=[root/'dust_loop/loop.mp4',root/'fire_loop/loop.mp4',root/'fire_loop/mask.png']
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('Missing cinematic overlays; run tools/build_cinematic_overlays.py')
    return ['-stream_loop','-1','-i',str(paths[0].resolve()),'-stream_loop','-1','-i',str(paths[1].resolve()),
            '-loop','1','-framerate','30','-i',str(paths[2].resolve())]
