"""Fresh Android UI snapshots and explicit image-to-device coordinate mapping."""
import hashlib,json,math,re,struct,time,uuid,sys
from pathlib import Path
import xml.etree.ElementTree as ET

JOBS=Path(r'G:\LocalCodex\android-ui-jobs')
TTL=180

def _tree(adb):
    code,out=adb('shell','uiautomator','dump','/sdcard/mycodex-ui.xml',timeout=30)
    if code:raise RuntimeError('UI tree dump failed: '+out[:300])
    code,xml=adb('shell','cat','/sdcard/mycodex-ui.xml',timeout=10)
    if code or '<hierarchy' not in xml:raise RuntimeError('UI tree unavailable; do not guess coordinates.')
    return xml

def _fingerprint(xml):
    tree=ET.fromstring(xml)
    values=[{k:n.get(k,'') for k in ('package','class','resource-id','text','content-desc','bounds','clickable','enabled','focused','scrollable')} for n in tree.iter('node')]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False).encode()).hexdigest()

def _candidates(xml,width,height):
    tree=ET.fromstring(xml);parents={c:p for p in tree.iter() for c in p};rows=[]
    for n in tree.iter('node'):
        label=n.get('text') or n.get('content-desc') or ''
        if not label and n.get('clickable')!='true':continue
        target=n
        while target.get('clickable')!='true' and target in parents:target=parents[target]
        if target.tag!='node' or target.get('clickable')!='true':target=n
        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',target.get('bounds',''))
        if not bounds:continue
        l,t,r,b=map(int,bounds.groups())
        if target is not n and (r-l)*(b-t)>width*height*.5:
            target=n
            bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.get('bounds',''))
            if not bounds:continue
            l,t,r,b=map(int,bounds.groups())
        if not (0<=l<r<=width and 0<=t<b<=height):continue
        if not label and (r-l)*(b-t)>width*height*.9:continue
        if target.get('enabled')=='false':continue
        rows.append({'id':len(rows)+1,'text':n.get('text',''),'description':n.get('content-desc',''),'resource_id':n.get('resource-id',''),'package':n.get('package',''),'bounds':[l,t,r,b],'center':[(l+r)//2,(t+b)//2],'clickable':target.get('clickable')=='true'})
    return rows

def snapshot(adb,screenshot,require_device,query='',limit=40):
    require_device();JOBS.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    xml=_tree(adb)
    path=JOBS/(token+'.png');shot=screenshot(str(path))
    raw=path.read_bytes();width,height=struct.unpack('>II',raw[16:24])
    rows=_candidates(xml,width,height)
    (JOBS/(token+'.xml')).write_text(xml,encoding='utf-8')
    state={'snapshot_id':token,'serial':shot.get('serial'),'created_at':time.time(),'expires_after_seconds':TTL,'width':width,'height':height,'screenshot_path':str(path),'fingerprint':_fingerprint(xml),'screenshot_sha256':hashlib.sha256(raw).hexdigest(),'candidates':rows,'attempts':{}}
    try:
        from PIL import Image,ImageDraw
        img=Image.open(path).convert('RGB');draw=ImageDraw.Draw(img)
        for row in rows:
            if row['clickable']:
                draw.rectangle(row['bounds'],outline='#ff3030',width=3)
                x,y=row['center'];draw.rectangle((x-18,y-14,x+22,y+14),fill='#ffff00');draw.text((x-14,y-10),str(row['id']),fill='black')
        annotated=JOBS/(token+'-numbered.png');img.save(annotated);state['numbered_image_path']=str(annotated)
    except ImportError:state['numbered_image_note']='Pillow unavailable; use original screenshot and candidate bounds.'
    (JOBS/(token+'.json')).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    from ui_image_gate import register_snapshot
    register_snapshot(path,state)
    visible=[r for r in rows if not query or any(query in r[k] for k in ('text','description','resource_id'))]
    limit=max(1,min(int(limit),120))
    return {k:v for k,v in state.items() if k not in ('fingerprint','attempts','screenshot_sha256','candidates')} | {'candidates':visible[:limit],'query':query,'candidates_truncated':len(visible)>limit,'coordinate_system':'Original PNG pixel coordinates; origin top-left. Do not use resized display coordinates directly.','candidate_count':len(rows),'matching_candidate_count':len(visible),'note':'Use query to reduce output. android_ui_locate searches the full saved candidate list.'}

def _load(token):
    if not re.fullmatch('[0-9a-f]{32}',token or ''):raise ValueError('Invalid snapshot_id.')
    state=json.loads((JOBS/(token+'.json')).read_text(encoding='utf-8'))
    if time.time()-state['created_at']>TTL:raise ValueError('Snapshot expired. Capture a fresh snapshot.')
    return state

def locate(token,query,field='text',match_mode='exact'):
    state=_load(token)
    if field not in ('text','description','resource_id'):raise ValueError('Unknown selector field.')
    if not query:raise ValueError('Provide exact target text or identifier.')
    if match_mode not in ('exact','contains'):raise ValueError('Unknown match mode.')
    matches=[r for r in state['candidates'] if (r[field]==query if match_mode=='exact' else query in r[field])]
    return {'snapshot_id':token,'matches':matches,'unique':len(matches)==1,'note':'Select a unique candidate_id; zero or multiple matches must not trigger guessed taps.'}

def icon_template(token,bounds):
    state=_load(token)
    if len(bounds)!=4 or not all(type(v) is int for v in bounds):raise ValueError('Provide four integer original-pixel bounds.')
    l,t,r,b=bounds
    if not (0<=l<r<=state['width'] and 0<=t<b<=state['height']) or min(r-l,b-t)<8 or max(r-l,b-t)>512:raise ValueError('Icon crop must be inside screenshot and between 8 and 512 pixels.')
    from PIL import Image
    path=JOBS/('icon-'+uuid.uuid4().hex+'.png')
    with Image.open(state['screenshot_path']) as image:image.crop(bounds).save(path)
    return {'template_path':str(path),'original_bounds':bounds,'note':'Template represents this observed appearance, not a universal semantic icon classifier.'}

def icon_find(token,template_path,threshold=.92):
    state=_load(token);path=Path(template_path).resolve()
    if not path.is_relative_to(JOBS.resolve()) or not path.is_file():raise ValueError('Use a template PNG created under G:/LocalCodex/android-ui-jobs.')
    if not .75<=threshold<=1:raise ValueError('Threshold must be between 0.75 and 1.')
    libs=r'G:\LocalCodex\tools\android-ui-libs'
    if libs not in sys.path:sys.path.insert(0,libs)
    import cv2,numpy as np
    began=time.perf_counter()
    raw=cv2.imdecode(np.frombuffer(Path(state['screenshot_path']).read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE)
    template=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE)
    if template is None or min(template.shape)<8 or max(template.shape)>512 or template.std()<4:raise ValueError('Template lacks a distinct visual pattern or is too large.')
    matches=[]
    for scale in (.8,1,1.2):
        small=cv2.resize(template,None,fx=scale,fy=scale)
        h,w=small.shape
        if h>raw.shape[0] or w>raw.shape[1]:continue
        scores=cv2.matchTemplate(raw,small,cv2.TM_CCOEFF_NORMED)
        for unused in range(21):
            _,score,_,pos=cv2.minMaxLoc(scores)
            if not math.isfinite(score) or score<threshold:break
            x,y=pos;cx,cy=x+w//2,y+h//2
            if not any(abs(cx-p['center'][0])<min(w,p['bounds'][2]-p['bounds'][0])//2 and abs(cy-p['center'][1])<min(h,p['bounds'][3]-p['bounds'][1])//2 for p in matches):matches.append({'bounds':[x,y,x+w,y+h],'center':[cx,cy],'score':round(score,5),'scale':scale})
            scores[max(0,y-h//2):min(scores.shape[0],y+h//2+1),max(0,x-w//2):min(scores.shape[1],x+w//2+1)]=-1
    matches.sort(key=lambda p:p['score'],reverse=True)
    return {'snapshot_id':token,'matches':matches[:20],'unique':len(matches)==1,'truncated':len(matches)>20,'cpu_match_ms':round((time.perf_counter()-began)*1000,1),'note':'Matching appearance does not prove meaning. Confirm target identity; multiple matches require disambiguation. Use center with android_ui_click for freshness checks.'}

def map_point(token,x,y,display_width,display_height,crop=None):
    state=_load(token)
    vals=[x,y,display_width,display_height]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vals):raise ValueError('Coordinates and dimensions must be finite numbers.')
    if display_width<=0 or display_height<=0 or not 0<=x<display_width or not 0<=y<display_height:raise ValueError('Point outside displayed image content.')
    l,t,r,b=crop if crop is not None else [0,0,state['width'],state['height']]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (l,t,r,b)) or not (0<=l<r<=state['width'] and 0<=t<b<=state['height']):raise ValueError('Invalid crop in original image pixels.')
    dx=min(state['width']-1,int(l+x*(r-l)/display_width));dy=min(state['height']-1,int(t+y*(b-t)/display_height))
    return {'snapshot_id':token,'device_point':[dx,dy],'original_size':[state['width'],state['height']],'crop':[l,t,r,b],'note':'Display size must describe image content excluding margins. This mapping does not confirm target identity.'}

def click(adb,screenshot,require_device,token,candidate_id=None,device_point=None,use_root=False,expected_text=''):
    require_device();state=_load(token)
    current=_tree(adb)
    if _fingerprint(current)!=state['fingerprint']:raise ValueError('UI changed since snapshot. No tap performed; refresh snapshot.')
    visual=candidate_id is None
    if not visual:
        rows=[r for r in state['candidates'] if r['id']==candidate_id and r['clickable']]
        if len(rows)!=1:raise ValueError('Select one clickable candidate_id.')
        point=rows[0]['center'];identity=str(candidate_id)
    else:
        if not isinstance(device_point,list) or len(device_point)!=2 or not all(type(v) is int for v in device_point):raise ValueError('Provide a candidate_id or integer device_point pair.')
        point=device_point;identity=str(point)
        verify=JOBS/(token+'-preclick.png');screenshot(str(verify))
        from PIL import Image
        px,py=point
        region=(max(0,px-48),max(0,py-48),min(state['width'],px+49),min(state['height'],py+49))
        with Image.open(state['screenshot_path']) as old, Image.open(verify) as new:
            if old.size!=new.size or old.convert('RGB').crop(region).tobytes()!=new.convert('RGB').crop(region).tobytes():raise ValueError('Visual target region changed; refresh snapshot. No tap performed.')
    x,y=point
    if not 0<=x<state['width'] or not 0<=y<state['height']:raise ValueError('Tap outside device screenshot.')
    failures_path=JOBS/'unchanged-clicks.json'
    failures=json.loads(failures_path.read_text(encoding='utf-8')) if failures_path.is_file() else {}
    failure_key=state['fingerprint']+':'+str(point)
    previous=failures.get(failure_key,{})
    if previous.get('count',0)>=2 and time.time()-previous.get('time',0)<600:raise ValueError('Two taps at this target left the same UI unchanged. Diagnose instead of guessing or retrying.')
    if state['attempts'].get(identity,0)>=2:raise ValueError('Two attempts already used for this target. Diagnose instead of retrying.')
    state['attempts'][identity]=state['attempts'].get(identity,0)+1
    (JOBS/(token+'.json')).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    args=('shell','su','-c',f'input tap {x} {y}') if use_root else ('shell','input','tap',str(x),str(y))
    code,out=adb(*args,timeout=10)
    if code:raise RuntimeError('Tap command failed: '+out[:500])
    time.sleep(.6)
    after=snapshot(adb,screenshot,require_device)
    changed=_load(after['snapshot_id'])['fingerprint']!=state['fingerprint']
    failures={k:v for k,v in failures.items() if time.time()-v.get('time',0)<600}
    if changed:failures.pop(failure_key,None)
    else:failures[failure_key]={'count':previous.get('count',0)+1,'time':time.time()}
    failures_path.write_text(json.dumps(failures),encoding='utf-8')
    matched=bool(expected_text) and any(r['text']==expected_text for r in _load(after['snapshot_id'])['candidates'])
    before_match=bool(expected_text) and any(r['text']==expected_text for r in state['candidates'])
    return {'input_sent':True,'device_point':point,'ui_tree_changed':changed,'expected_text':expected_text,'expected_state_verified':bool(matched and (changed or not before_match)) if expected_text else None,'after':after,'note':'Input command success is not task success. Inspect after snapshot and expected state; unchanged UI is not proof of a successful click.'}

def schemas():
    from screen_coordinates import SCHEMA
    from vision_crop import SCHEMAS
    token={'type':'string'}
    return [SCHEMA,*SCHEMAS,
        ('android_ui_prepare_vision','For an unfamiliar symbol: crop a fresh snapshot and losslessly compress PNG, preserving offset and pixels. Automatically allows CPU vision of the crop; map through android_ui_map_prepared_point then guarded click.',{'type':'object','properties':{'snapshot_id':token,'crop':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},'reason':token},'required':['snapshot_id','crop','reason']}),
        ('android_ui_map_prepared_point','Map normalized crop coordinates back to the device using saved crop metadata; no manual offset calculation. Pass device_point and snapshot_id to android_ui_click for freshness checks.',{'type':'object','properties':{'view_id':token,'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number','default':1},'display_height':{'type':'number','default':1}},'required':['view_id','x','y']}),
        ('android_ui_request_vision','Explicit CPU vision fallback for an unfamiliar/custom target after checking controls and known templates. Grants a hash-bound 180-second image read; then call view_image on that exact path.',{'type':'object','properties':{'image_path':token,'reason':token},'required':['image_path','reason']}),
        ('android_ui_snapshot','Capture fresh original-size PNG, numbered image and UI bounds on G:. Pass target query to reduce tokens and avoid CPU vision when controls are found.',{'type':'object','properties':{'query':{'type':'string','default':''},'limit':{'type':'integer','default':40}}}),
        ('android_ui_locate','Find text, description or resource id in a fresh snapshot; return candidate coordinates and ambiguity.',{'type':'object','properties':{'snapshot_id':token,'query':token,'field':{'type':'string','enum':['text','description','resource_id'],'default':'text'},'match_mode':{'type':'string','enum':['exact','contains'],'default':'exact'}},'required':['snapshot_id','query']}),
        ('android_ui_icon_template','Save a known icon crop from original-pixel screenshot bounds on G: for later CPU matching.',{'type':'object','properties':{'snapshot_id':token,'bounds':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4}},'required':['snapshot_id','bounds']}),
        ('android_ui_icon_find','CPU template matching for previously observed icons or symbols; returns centers, confidence and ambiguity without a vision model.',{'type':'object','properties':{'snapshot_id':token,'template_path':token,'threshold':{'type':'number','default':.92}},'required':['snapshot_id','template_path']}),
        ('android_ui_map_point','Map a point on resized/cropped image content to original device pixels; display dimensions must exclude margins.',{'type':'object','properties':{'snapshot_id':token,'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number'},'display_height':{'type':'number'},'crop':{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}},'required':['snapshot_id','x','y','display_width','display_height']}),
        ('android_ui_click','Validate snapshot freshness, tap one candidate or explicitly mapped device point, then return fresh evidence. Does not assert business success.',{'type':'object','properties':{'snapshot_id':token,'candidate_id':{'type':'integer'},'device_point':{'type':'array','items':{'type':'integer'},'minItems':2,'maxItems':2},'use_root':{'type':'boolean','default':False},'expected_text':{'type':'string','default':''}},'required':['snapshot_id']})]

def dispatch(name,args,adb,screenshot,require_device):
    if name=='android_ui_prepare_vision':
        from vision_crop import prepare
        from ui_image_gate import request_vision
        state=_load(args['snapshot_id'])
        if not str(args['reason']).strip():raise ValueError('Explain why controls/templates are insufficient.')
        view=prepare(state['screenshot_path'],args['crop'],output_dir=JOBS)
        view['snapshot_id']=state['snapshot_id']
        (JOBS/(view['view_id']+'-view.json')).write_text(json.dumps(view,ensure_ascii=False),encoding='utf-8')
        request_vision(view['image_path'],args['reason'])
        return view
    if name=='android_ui_map_prepared_point':
        from vision_crop import load,map_view
        state=load(args['view_id'],JOBS);snapshot_state=_load(state['snapshot_id'])
        if state['source_sha256']!=snapshot_state['screenshot_sha256']:raise ValueError('Source does not match snapshot.')
        mapped=map_view(args['view_id'],args['x'],args['y'],args.get('display_width',1),args.get('display_height',1),JOBS)
        return mapped | {'snapshot_id':state['snapshot_id'],'device_point':mapped['image_point'],'next':'Use android_ui_click with this snapshot_id and device_point; do not use a raw shell tap.'}
    if name=='android_ui_request_vision':
        from ui_image_gate import request_vision
        return request_vision(args['image_path'],args['reason'])
    if name=='android_ui_snapshot':return snapshot(adb,screenshot,require_device,args.get('query',''),args.get('limit',40))
    if name=='android_ui_locate':return locate(args['snapshot_id'],args['query'],args.get('field','text'),args.get('match_mode','exact'))
    if name=='android_ui_icon_template':return icon_template(args['snapshot_id'],args['bounds'])
    if name=='android_ui_icon_find':return icon_find(args['snapshot_id'],args['template_path'],args.get('threshold',.92))
    if name=='android_ui_map_point':return map_point(args['snapshot_id'],args['x'],args['y'],args['display_width'],args['display_height'],args.get('crop'))
    if name=='android_ui_click':return click(adb,screenshot,require_device,args['snapshot_id'],args.get('candidate_id'),args.get('device_point'),args.get('use_root',False),args.get('expected_text',''))
    raise ValueError('Unknown Android coordinate tool.')
