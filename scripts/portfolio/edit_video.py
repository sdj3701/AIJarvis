from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parents[2] / "artifacts" / "portfolio-video"
FFMPEG = HERE / 'tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
RAW = HERE / 'take-final.mp4'
FONT = Path(r'C:\Windows\Fonts')
W, H = 1920, 1080

def font(size, bold=False, latin=False):
    name = 'bahnschrift.ttf' if latin else ('malgunbd.ttf' if bold else 'malgun.ttf')
    return ImageFont.truetype(str(FONT / name), size)

def run(args):
    subprocess.run([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-y', *map(str,args)], check=True)

def contact_sheet():
    times = [0, 9, 11, 13, 18, 74, 77, 80, 90]
    sheet = Image.new('RGB',(1224, 900),'#080F19')
    d = ImageDraw.Draw(sheet)
    for i,t in enumerate(times):
        p=HERE/f'check-{t}.jpg'
        run(['-ss',t,'-i',RAW,'-frames:v',1,'-vf','scale=408:270',p])
        sheet.paste(Image.open(p),(i%3*408,i//3*300+30))
        d.text((i%3*408+12,i//3*300+5),f'{t}s',font=font(18,latin=True),fill='#72E9F2')
    sheet.save(HERE/'raw-contact-sheet.jpg')

SCENES = [
    dict(label='PERSONAL AI ASSISTANT', title=['JARVIS'], title_size=110,
         body=['내 PC에서 만나는', '개인 AI 비서.'], body_size=44,
         tag='LOCAL AI  /  WINDOWS', number='00 — INTRO',
         start=0, duration=5, crop=(0,32,1226,778), size=(1190,756), pos=(650,176)),
    dict(label='01 / DOCUMENT SEARCH', title=['문서를 찾고,','답을 얻다.'], title_size=60,
         body=['로컬 문서를 검색해', '관련 내용을 답변으로.'], body_size=30,
         tag='SQLite FTS5  +  RRF', number='01 — SEARCH',
         start=9, duration=10, crop=(302,110,914,684), size=(1170,876), pos=(670,128)),
    dict(label='02 / NATURAL LANGUAGE', title=['말 한마디로','실행 요청.'], title_size=60,
         body=['“계산기 켜줘”', '처음 실행하는 앱은', '사용자 승인 후 진행.'], body_size=30,
         tag='REQUEST  /  APPROVAL', number='02 — ACTION',
         start=73, duration=9, crop=(302,110,914,684), size=(1170,876), pos=(670,128)),
    dict(label='JARVIS / PERSONAL PROJECT', title=['검색에서','실행까지.'], title_size=74,
         body=['Python · Ollama', 'SQLite FTS5 · RRF'], body_size=30,
         tag='WINDOWS PERSONAL AI', number='03 — JARVIS',
         start=1, duration=6, crop=(307,200,450,500), size=(702,780), pos=(1040,170)),
]

def card(scene, i):
    im=Image.new('RGB',(W,H))
    px=im.load()
    for y in range(H):
        for x in range(W):
            glow=max(0,1-((x-1310)**2/(1100**2)+(y-500)**2/(850**2)))
            px[x,y]=(int(6+3*glow),int(12+14*glow),int(21+20*glow))
    d=ImageDraw.Draw(im)
    for x in range(650,W,64):
        d.line((x,105,x,1005),fill='#102432',width=1)
    for y in range(125,1006,64):
        d.line((650,y,W-65,y),fill='#102432',width=1)
    d.rounded_rectangle((76,54,87,65),radius=3,fill='#55E0E9')
    d.text((105,42),'JARVIS / PROJECT FILM',font=font(23,latin=True),fill='#D6E6EC')
    d.text((1530,44),'30 SEC  /  2026',font=font(22,latin=True),fill='#7898A9')
    d.line((80,101,1840,101),fill='#244251',width=2)
    d.text((80,196),scene['label'],font=font(23,latin=True),fill='#53D8E4')
    y=266
    for line in scene['title']:
        d.text((75,y),line,font=font(scene['title_size'],bold=True,latin=(line=='JARVIS')),fill='#F1F7FA')
        y+=scene['title_size']+18
    y=max(y+42,495)
    for line in scene['body']:
        d.text((80,y),line,font=font(scene['body_size']),fill='#AFC7D4')
        y+=scene['body_size']+19
    tag_y=max(720,y+38)
    d.rounded_rectangle((80,tag_y,560,tag_y+54),radius=9,outline='#2D5966',width=2,fill='#10252F')
    d.text((100,tag_y+14),scene['tag'],font=font(23,latin=True),fill='#76E4E9')
    d.text((80,932),scene['number'],font=font(22,latin=True),fill='#708E9E')
    d.line((80,1018,1840,1018),fill='#244251',width=2)
    d.text((80,1036),'실제 실행 화면 · 촬영용 샘플 문서 · 대기 구간 편집',font=font(20),fill='#7993A2')
    if i==3:
        d.text((80,854),'github.com/sdj3701/AIJarvis',font=font(24,latin=True),fill='#A6C6D2')
    x,y=scene['pos']; vw,vh=scene['size']
    d.rectangle((x-2,y-2,x+vw+2,y+vh+2),outline='#2B6572',width=2)
    path=HERE/f'card-{i}.png'
    im.save(path)
    return path

def edit():
    outputs=[]
    for i,scene in enumerate(SCENES):
        background=card(scene,i)
        x,y,cw,ch=scene['crop']; sw,sh=scene['size']; ox,oy=scene['pos']; dur=scene['duration']
        filt=f'[0:v]setpts=PTS-STARTPTS,crop={cw}:{ch}:{x}:{y},scale={sw}:{sh}:flags=lanczos,fps=30,tpad=stop_mode=clone:stop_duration=0.2,setsar=1[screen];[1:v][screen]overlay={ox}:{oy}:shortest=1'
        if i==0:
            filt+=',fade=t=in:st=0:d=0.3'
        if i==3:
            filt+=f',fade=t=out:st={dur-0.4}:d=0.4'
        filt+=',format=yuv420p[out]'
        output=HERE/f'scene-{i}.mp4'
        run(['-ss',scene['start'],'-t',dur,'-i',RAW,'-loop','1','-framerate','30','-i',background,
             '-filter_complex',filt,'-map','[out]','-t',dur,'-frames:v',dur*30,'-r','30','-c:v','libx264',
             '-preset','medium','-crf','18','-an',output])
        outputs.append(output)
        print(f'Scene {i+1}/4 encoded',flush=True)
    listing=HERE/'concat.txt'
    listing.write_text(''.join(f"file '{p.as_posix()}'\n" for p in outputs),encoding='utf-8')
    run(['-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart',HERE/'Jarvis_30s_Portfolio.mp4'])
    run(['-ss','7','-i',HERE/'Jarvis_30s_Portfolio.mp4','-frames:v','1',HERE/'Jarvis_30s_Preview.jpg'])
    print('Created Jarvis_30s_Portfolio.mp4',flush=True)

if __name__=='__main__':
    import sys
    if '--inspect' in sys.argv:
        contact_sheet()
    else:
        edit()
