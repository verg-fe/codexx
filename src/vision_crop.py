"""Lossless cropped UI input with explicit mapping back to its source."""
import hashlib,json,math,re,time,uuid
from pathlib import Path
JOBS=Path(r'G:\LocalCodex\vision-crops')

def prepare(image_path,crop,physical_capture_bounds=None,output_dir=None):
    from PIL import Image
    source=Path(image_path).resolve()
    if not source.is_file():raise ValueError('An existing screenshot is required.')
    with Image.open(source) as image:
        width,height=image.size
        if not isinstance(crop,list) or len(crop)!=4 or not all(type(v) is int for v in crop):raise ValueError('Crop must contain four integer original-image pixel bounds.')
        l,t,r,b=crop
        if not 0<=l<r<=width or not 0<=t<b<=height:raise ValueError('Crop outside original image.')
        if physical_capture_bounds is not None:
            if len(physical_capture_bounds)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in physical_capture_bounds):raise ValueError('Invalid physical capture bounds.')
            a,c,d,e=physical_capture_bounds
            if d<=a or e<=c:raise ValueError('Invalid physical capture bounds.')
        directory=Path(output_dir) if output_dir else JOBS
        directory.mkdir(parents=True,exist_ok=True)
        token=uuid.uuid4().hex;target=directory/(token+'-crop.png')
        image.crop(crop).save(target,format='PNG',optimize=True,compress_level=9)
    state={'view_id':token,'created_at':time.time(),'image_path':str(target),'original_path':str(source),'original_size':[width,height],'encoded_size':[r-l,b-t],'crop':crop,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'view_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'physical_capture_bounds':physical_capture_bounds,'original_file_bytes':source.stat().st_size,'cropped_file_bytes':target.stat().st_size,'pixels_retained':(r-l)*(b-t)/(width*height),'compression':'lossless PNG; retained pixels are not resized'}
    (directory/(token+'-view.json')).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    return state | {'note':'Coordinates must be relative to this crop, preferably normalized 0..1; map using view_id. Compression does not guarantee a smaller file than an already lossy original. Target meaning still needs verification.'}

def load(view_id,directory=None):
    if not re.fullmatch('[0-9a-f]{32}',str(view_id)):raise ValueError('Invalid view_id.')
    state=json.loads((Path(directory or JOBS)/(view_id+'-view.json')).read_text(encoding='utf-8'))
    if time.time()-state['created_at']>180:raise ValueError('Cropped view expired; capture a fresh screenshot.')
    for path,key in ((state['original_path'],'source_sha256'),(state['image_path'],'view_sha256')):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=state[key]:raise ValueError('Image changed; prepare a fresh crop.')
    return state

def map_view(view_id,x,y,display_width=1,display_height=1,directory=None):
    from screen_coordinates import map_point
    state=load(view_id,directory)
    result=map_point(state['original_path'],x,y,display_width,display_height,state['crop'],state['physical_capture_bounds'])
    return result | {'view_id':view_id,'encoded_size':state['encoded_size'],'crop':state['crop']}

SCHEMAS=[
 ('screen_prepare_vision','Crop original screenshot to a target area and losslessly compress PNG without resizing retained pixels. Save crop offset and optional known desktop physical capture bounds on G:.',{'type':'object','properties':{'image_path':{'type':'string'},'crop':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},'physical_capture_bounds':{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}},'required':['image_path','crop']}),
 ('screen_map_prepared_point','Map a point relative to a prepared crop back to original image and known desktop physical coordinates. Default x,y normalized 0..1; rejects expired or changed source/crop.',{'type':'object','properties':{'view_id':{'type':'string'},'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number','default':1},'display_height':{'type':'number','default':1}},'required':['view_id','x','y']})]
