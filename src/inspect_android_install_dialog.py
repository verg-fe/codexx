"""Read Android accessibility nodes without tapping or changing the device UI."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).parent))
import local_mcp_servers as local
xml=local._accessibility_tree()['xml']
out=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test\install-dialog-tree.xml')
out.write_text(xml,encoding='utf-8')
root=ET.fromstring(xml)
nodes=[]
for node in root.iter('node'):
    row={key:node.attrib.get(key,'') for key in ('class','text','content-desc','resource-id','clickable','bounds')}
    if any(row.values()): nodes.append(row)
print('\n'.join(f"{n['class']} | {n['text']} | {n['content-desc']} | {n['resource-id']} | {n['clickable']} | {n['bounds']}" for n in nodes))
