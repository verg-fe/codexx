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
