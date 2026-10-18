"""Map resized/cropped image points without confusing image and screen pixels."""
import math
from pathlib import Path

def map_point(image_path,x,y,display_width=1,display_height=1,crop=None,physical_capture_bounds=None):
    from PIL import Image
    path=Path(image_path)
    if not path.is_absolute() or not path.is_file():raise ValueError('Provide an existing absolute screenshot path.')
    with Image.open(path) as image:width,height=image.size
    vals=[x,y,display_width,display_height]
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vals):raise ValueError('Coordinates must be finite numbers.')
    if display_width<=0 or display_height<=0 or not 0<=x<display_width or not 0<=y<display_height:raise ValueError('Point must be inside displayed image content, excluding margins.')
    l,t,r,b=crop if crop is not None else [0,0,width,height]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (l,t,r,b)) or not (0<=l<r<=width and 0<=t<b<=height):raise ValueError('Crop must use original-image pixel bounds.')
    ix=l+x*(r-l)/display_width;iy=t+y*(b-t)/display_height
    result={'image_size':[width,height],'image_point':[min(width-1,int(ix)),min(height-1,int(iy))],'image_path':str(path),'coordinate_space':'original image pixels'}
    if physical_capture_bounds is not None:
        a,c,d,e=physical_capture_bounds
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (a,c,d,e)) or d<=a or e<=c:raise ValueError('Invalid physical screen capture bounds.')
        result.update(physical_screen_point=[int(a+ix*(d-a)/width),int(c+iy*(e-c)/height)],physical_capture_bounds=physical_capture_bounds,note='Use only with a click API accepting physical screen pixels. If the API uses logical DPI coordinates, convert according to that API; do not assume they are identical.')
    else:result['note']='Image coordinates only. For desktop clicking, obtain actual physical capture bounds from the screenshot backend; never guess monitor/window origin or DPI scaling.'
    return result

SCHEMA=('screen_map_point','Map a normalized or resized/cropped screenshot point to original pixels and optional known physical desktop capture bounds; supports negative monitor origins.',{'type':'object','properties':{'image_path':{'type':'string'},'x':{'type':'number'},'y':{'type':'number'},'display_width':{'type':'number','default':1},'display_height':{'type':'number','default':1},'crop':{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4},'physical_capture_bounds':{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}},'required':['image_path','x','y']})

OCR_SCHEMA=('screen_ocr','Run local CPU OCR on the exact screenshot file. Returns text, confidence, and bounding boxes in original image pixels; feed the box center through screen_map_point using the same screenshot dimensions/crop before a guarded click.',{'type':'object','properties':{'image_path':{'type':'string'},'query':{'type':'string','default':''},'match_mode':{'type':'string','enum':['contains','exact'],'default':'contains'},'min_confidence':{'type':'number','minimum':0,'maximum':1,'default':0.35},'limit':{'type':'integer','minimum':1,'maximum':120,'default':80}},'required':['image_path']})

SYMBOL_SCHEMA=('screen_find_symbol','Find a symbol in this exact screenshot using local CPU OpenCV. For an add icon use symbol="plus" (not OCR query "+") and limit region to its visible toolbar. Returns original-image boxes and scores; click only a unique candidate mapped through screen_map_point.',{'type':'object','properties':{'image_path':{'type':'string'},'symbol':{'type':'string','enum':['plus','circled_plus','ellipsis_horizontal','ellipsis_vertical'],'description':'Use plus for a + glyph; circled_plus only when visibly enclosed by a ring.'},'region':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4,'description':'Optional narrow [left,top,right,bottom] search region in original screenshot pixels.'},'min_score':{'type':'number','minimum':0.2,'maximum':1,'default':0.75}},'required':['image_path','symbol']})

def ocr_image(image_path,query='',match_mode='contains',min_confidence=0.35,limit=80):
    from rapidocr_service import recognize
    result=recognize(image_path,query,match_mode,min_confidence,limit)
    from ui_image_gate import record_cpu_target_attempt
    record_cpu_target_attempt(image_path,'ocr')
    result['image_path']=str(Path(image_path).expanduser().resolve())
    result['coordinate_note']='bbox and center use original screenshot pixels, origin top-left. Map the center through screen_map_point with the same image_path, displayed content size and crop; never click resized display coordinates directly.'
    return result

def find_symbol_image(image_path,symbol,region=None,min_score=0.75):
    from rapidocr_service import find_symbol
    result=find_symbol(image_path,symbol,region,min_score)
    from ui_image_gate import record_cpu_target_attempt
    record_cpu_target_attempt(image_path,'symbol')
    result['image_path']=str(Path(image_path).expanduser().resolve())
    result['coordinate_note']='Symbol boxes and centers use original screenshot pixels. Map the unique center through screen_map_point with this exact image. If zero or multiple matches remain, do not click by guess; narrow the region or use an observed icon template.'
    return result
