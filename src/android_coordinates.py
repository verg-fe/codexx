"""Fresh Android UI snapshots and explicit image-to-device coordinate mapping."""
import hashlib,json,math,re,struct,time,uuid,sys
from pathlib import Path

JOBS=Path(r'G:\LocalCodex\android-ui-jobs')
TTL=180

def snapshot(adb,screenshot,require_device,query='',limit=40):
    require_device();JOBS.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    path=JOBS/(token+'.png');shot=screenshot(str(path))
    raw=path.read_bytes();width,height=struct.unpack('>II',raw[16:24])
    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or width<1 or height<1:
        raise RuntimeError('Screenshot is not a valid full-size PNG.')
    digest=hashlib.sha256(raw).hexdigest()
    state={'snapshot_id':token,'serial':shot.get('serial'),'created_at':time.time(),'expires_after_seconds':TTL,'width':width,'height':height,'screenshot_path':str(path),'fingerprint':digest,'screenshot_sha256':digest,'attempts':{},'cpu_ocr_attempted':False,'cpu_symbol_attempted':False}
    (JOBS/(token+'.json')).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    from ui_image_gate import register_snapshot
    register_snapshot(path,state)
    return {k:v for k,v in state.items() if k not in ('fingerprint','attempts','screenshot_sha256')} | {'coordinate_system':'Original PNG pixel coordinates; origin top-left. Do not use resized display coordinates directly.','ocr_required_for_text':True,'note':'Screenshot-only capture; no accessibility/UI tree is queried. Call android_ui_ocr on this snapshot for text boxes, or CPU symbol/template matching for glyphs.'}

def _load(token):
    if not re.fullmatch('[0-9a-f]{32}',token or ''):raise ValueError('Invalid snapshot_id.')
    state=json.loads((JOBS/(token+'.json')).read_text(encoding='utf-8'))
    if time.time()-state['created_at']>TTL:raise ValueError('Snapshot expired. Capture a fresh snapshot.')
    return state

def _visual_delta(before_path,after_path,point,radius=64):
    """Compare a guarded tap's local target region and downscaled whole frame."""
    from PIL import Image,ImageChops,ImageStat
    def metrics(a,b):
        diff=ImageChops.difference(a,b).convert('L')
        mean=float(ImageStat.Stat(diff).mean[0])
        changed=diff.point(lambda value:255 if value>24 else 0).histogram()[255]
        return mean,changed/max(1,diff.width*diff.height)
    with Image.open(before_path) as old_image, Image.open(after_path) as new_image:
        old=old_image.convert('RGB');new=new_image.convert('RGB')
        if old.size!=new.size:return {'visual_changed':True,'local_mean_abs_delta':None,'local_changed_ratio':1.0,'global_mean_abs_delta':None,'global_changed_ratio':1.0}
        width,height=old.size;x,y=point
        region=(max(0,x-radius),max(0,y-radius),min(width,x+radius+1),min(height,y+radius+1))
        local_mean,local_ratio=metrics(old.crop(region),new.crop(region))
        size=(160,160)
        global_mean,global_ratio=metrics(old.resize(size,Image.Resampling.BILINEAR),new.resize(size,Image.Resampling.BILINEAR))
    changed=(local_mean>=4.0 and local_ratio>=.015) or (global_mean>=3.0 and global_ratio>=.02)
    return {'visual_changed':changed,'local_mean_abs_delta':round(local_mean,3),'local_changed_ratio':round(local_ratio,5),'global_mean_abs_delta':round(global_mean,3),'global_changed_ratio':round(global_ratio,5)}

def locate(token,query,field='text',match_mode='exact'):
    _load(token)
    if field!='text':raise ValueError('Screenshot localization supports OCR text only; use CPU symbol/template matching for non-text targets.')
    if not query:raise ValueError('Provide exact target text or identifier.')
    if match_mode not in ('exact','contains'):raise ValueError('Unknown match mode.')
    result=ocr(token,query,match_mode)
    matches=result.get('matches',[])
    return {'snapshot_id':token,'matches':matches,'unique':len(matches)==1,'image_size':result.get('image_size'),'coordinate_space':'original_image_pixels','engine':result.get('engine'),'note':'Matches come from CPU OCR on this exact screenshot. Map the unique box center with android_ui_map_point before guarded click; zero or multiple matches must not trigger guessed taps.'}

def ocr(token,query='',match_mode='contains',min_confidence=.35,limit=80):
    state=_load(token)
    path=Path(state['screenshot_path']).resolve(strict=True)
    if not path.is_relative_to(JOBS.resolve()):raise ValueError('Snapshot image is outside the Android UI job folder.')
    from rapidocr_service import recognize
    result=recognize(str(path),query,match_mode,min_confidence,limit,state['screenshot_sha256'],(state['width'],state['height']))
    from ui_image_gate import record_cpu_target_attempt
    record_cpu_target_attempt(path,'ocr')
    result.update({'snapshot_id':token,'screenshot_path':str(path),'coordinate_system':'Original PNG pixels, origin top-left; map OCR center through android_ui_map_point using this snapshot and original image dimensions before clicking.','note':'For a text target, require one unambiguous matching box; map its original-pixel center through android_ui_map_point with display_width/height equal to image_size, then use the returned device_point with android_ui_click and this snapshot_id. Refresh if the screen changes.'})
    return result

def find_symbol(token,symbol,region=None,min_score=.75):
    state=_load(token)
    path=Path(state['screenshot_path']).resolve(strict=True)
    if not path.is_relative_to(JOBS.resolve()):raise ValueError('Snapshot image is outside the Android UI job folder.')
    from rapidocr_service import find_symbol as detect_symbol
    result=detect_symbol(str(path),symbol,region,min_score,state['screenshot_sha256'],(state['width'],state['height']))
    from ui_image_gate import record_cpu_target_attempt
    record_cpu_target_attempt(path,'symbol')
    result.update({'snapshot_id':token,'screenshot_path':str(path),'coordinate_system':'Original PNG pixels, origin top-left.','note':'Symbol boxes are from this exact snapshot. Only when unique=true, map center through android_ui_map_point with display_width/height equal to image_size, then call android_ui_click with the same snapshot_id. Zero or multiple matches require a narrower region or an observed template; do not guess.'})
    return result

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
    from rapidocr_service import find_template
    result=find_template(str(Path(state['screenshot_path']).resolve(strict=True)),str(path),threshold,
        state['screenshot_sha256'],(state['width'],state['height']))
    from ui_image_gate import record_cpu_target_attempt
    record_cpu_target_attempt(state['screenshot_path'],'symbol')
    result.update({'snapshot_id':token,'note':'CPU template matching runs in the pinned G: Python environment. Matching appearance does not prove meaning; confirm the observed target. Only a unique match from this snapshot may be mapped and passed to android_ui_click.'})
    return result

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
    if candidate_id is not None:raise ValueError('Accessibility candidate IDs are disabled. Use a unique OCR/symbol/template match mapped to device_point.')
    if not isinstance(device_point,list) or len(device_point)!=2 or not all(type(v) is int for v in device_point):raise ValueError('Provide an integer device_point pair mapped from this snapshot.')
    point=device_point;identity=str(point)
    verify=JOBS/(token+'-preclick.png');screenshot(str(verify))
    from PIL import Image
    with Image.open(state['screenshot_path']) as old, Image.open(verify) as new:
        if old.size!=new.size:raise ValueError('Screenshot dimensions changed; refresh snapshot. No tap performed.')
    before_delta=_visual_delta(state['screenshot_path'],str(verify),point)
    if before_delta['visual_changed']:raise ValueError('Screen or target changed since snapshot; refresh and OCR again. No tap performed.')
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
    after_state=_load(after['snapshot_id'])
    visual_delta=_visual_delta(verify,after_state['screenshot_path'],point)
    changed=visual_delta['visual_changed']
    failures={k:v for k,v in failures.items() if time.time()-v.get('time',0)<600}
    if changed:failures.pop(failure_key,None)
    else:failures[failure_key]={'count':previous.get('count',0)+1,'time':time.time()}
    failures_path.write_text(json.dumps(failures),encoding='utf-8')
    matched=False
    if expected_text:
        ocr_result=ocr(after_state['snapshot_id'],expected_text,'exact',.35,40)
        matched=bool(ocr_result.get('matches'))
    return {'input_sent':True,'device_point':point,'visual_region_changed':visual_delta['visual_changed'],'visual_change':visual_delta,'target_state_changed':changed,'expected_text':expected_text,'expected_text_visible_after':matched if expected_text else None,'expected_state_verified':bool(matched and changed) if expected_text else None,'after':after,'note':'Input command success is not task success. Inspect the fresh screenshot and OCR evidence; do not retry from memory.'}

def schemas():
    from screen_coordinates import SCHEMA,OCR_SCHEMA,SYMBOL_SCHEMA
    from vision_crop import SCHEMAS
    token={'type':'string'}
    return [SCHEMA,OCR_SCHEMA,SYMBOL_SCHEMA,*SCHEMAS,
        ('android_ui_ocr','Run local CPU OCR on this exact fresh Android snapshot; returns recognized text, confidence and bounding boxes in original PNG pixels. Use a unique match, map its center through android_ui_map_point with this same snapshot_id, then guarded click.',{'type':'object','properties':{'snapshot_id':token,'query':{'type':'string','default':''},'match_mode':{'type':'string','enum':['contains','exact'],'default':'contains'},'min_confidence':{'type':'number','minimum':0,'maximum':1,'default':.35},'limit':{'type':'integer','minimum':1,'maximum':120,'default':80}},'required':['snapshot_id']}),
        ('android_ui_find_symbol','Find a symbol in this fresh screenshot using CPU OpenCV. For an add icon use symbol="plus" (not OCR query "+") and limit region to its visible toolbar; returns original-pixel boxes and scores. Require one unique candidate, map through android_ui_map_point, then guarded click.',{'type':'object','properties':{'snapshot_id':token,'symbol':{'type':'string','enum':['plus','circled_plus','ellipsis_horizontal','ellipsis_vertical'],'description':'Use plus for a + glyph; circled_plus only when visibly enclosed by a ring.'},'region':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4,'description':'Optional narrow [left,top,right,bottom] search region in original screenshot pixels.'},'min_score':{'type':'number','minimum':.2,'maximum':1,'default':.75}},'required':['snapshot_id','symbol']}),
        ('android_ui_prepare_vision','For an unfamiliar symbol: crop a fresh snapshot and losslessly compress PNG, preserving offset and pixels. Automatically allows CPU vision of the crop; map through android_ui_map_prepared_point then guarded click.',{'type':'object','properties':{'snapshot_id':token,'crop':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},'reason':token},'required':['snapshot_id','crop','reason']}),
        ('android_ui_map_prepared_point','Map normalized crop coordinates back to the device using saved crop metadata; no manual offset calculation. Pass device_point and snapshot_id to android_ui_click for freshness checks.',{'type':'object','properties':{'view_id':token,'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number','default':1},'display_height':{'type':'number','default':1}},'required':['view_id','x','y']}),
        ('android_ui_request_vision','Explicit CPU vision fallback only after CPU OCR for text or CPU symbol/template matching for glyphs has run on this exact fresh snapshot and failed. The server rejects requests without same-snapshot CPU evidence. Grants a hash-bound 180-second image read; then call view_image on that exact path.',{'type':'object','properties':{'image_path':token,'reason':token},'required':['image_path','reason']}),
        ('android_ui_snapshot','Capture a fresh original-size PNG screenshot on G: only. Does not query UIAutomator/accessibility data. For text, call android_ui_ocr on this snapshot; for glyphs use CPU symbol/template matching.',{'type':'object','properties':{}}),
        ('android_ui_locate','Find text using CPU OCR on this exact fresh screenshot; returns original-pixel boxes and ambiguity. Does not inspect UIAutomator/accessibility data.',{'type':'object','properties':{'snapshot_id':token,'query':token,'field':{'type':'string','enum':['text'],'default':'text'},'match_mode':{'type':'string','enum':['exact','contains'],'default':'exact'}},'required':['snapshot_id','query']}),
        ('android_ui_icon_template','Save a known icon crop from original-pixel screenshot bounds on G: for later CPU matching.',{'type':'object','properties':{'snapshot_id':token,'bounds':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4}},'required':['snapshot_id','bounds']}),
        ('android_ui_icon_find','CPU template matching for previously observed icons or symbols; returns centers, confidence and ambiguity without a vision model.',{'type':'object','properties':{'snapshot_id':token,'template_path':token,'threshold':{'type':'number','default':.92}},'required':['snapshot_id','template_path']}),
        ('android_ui_map_point','Map a point on resized/cropped image content to original device pixels; display dimensions must exclude margins.',{'type':'object','properties':{'snapshot_id':token,'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number'},'display_height':{'type':'number'},'crop':{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}},'required':['snapshot_id','x','y','display_width','display_height']}),
        ('android_ui_click','Validate screenshot freshness, tap one OCR/symbol/template point mapped through this snapshot, then return fresh screenshot evidence. Does not assert business success.',{'type':'object','properties':{'snapshot_id':token,'device_point':{'type':'array','items':{'type':'integer'},'minItems':2,'maxItems':2},'use_root':{'type':'boolean','default':False},'expected_text':{'type':'string','default':''}},'required':['snapshot_id','device_point']})]

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
    if name=='android_ui_ocr':return ocr(args['snapshot_id'],args.get('query',''),args.get('match_mode','contains'),args.get('min_confidence',.35),args.get('limit',80))
    if name=='android_ui_find_symbol':return find_symbol(args['snapshot_id'],args['symbol'],args.get('region'),args.get('min_score',.75))
    if name=='android_ui_icon_template':return icon_template(args['snapshot_id'],args['bounds'])
    if name=='android_ui_icon_find':return icon_find(args['snapshot_id'],args['template_path'],args.get('threshold',.92))
    if name=='android_ui_map_point':return map_point(args['snapshot_id'],args['x'],args['y'],args['display_width'],args['display_height'],args.get('crop'))
    if name=='android_ui_click':return click(adb,screenshot,require_device,args['snapshot_id'],args.get('candidate_id'),args.get('device_point'),args.get('use_root',False),args.get('expected_text',''))
    raise ValueError('Unknown Android coordinate tool.')
