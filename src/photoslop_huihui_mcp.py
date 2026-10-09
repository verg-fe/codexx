"""CPU-only Photoslop engine adapter with Chinese guidance and useful MCP errors."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_OPENGL'] = 'software'
os.environ['QT_QUICK_BACKEND'] = 'software'
import argparse
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from photoslop import server as engine
from photoslop.errors import ToolError as EngineError


def invoke(fn, **args):
    try:
        return fn(**args)
    except EngineError as exc:
        raise ToolError(str(exc)) from exc


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=r'G:\LocalCodex\image-jobs')
    args=parser.parse_args()
    engine.configure(root=args.root)
    server=MCPServer('photoslop',instructions=(
        '本地 CPU 图片编辑。先 list_operations 查询操作名称和参数，再 edit_image 执行，'
        '最后 document_info 检查文件。PNG/JPEG/WebP/BMP 可输出平面图，ORA 保存图层。'
        '此接入不承诺 PSD 兼容或 Photoshop 全功能。所有路径位于 '+args.root+'。'
        '调用前必须把输入文件暂存到 G:\\LocalCodex\\image-jobs 下，并将 input/output 指向该目录中的实际文件；'
        '不要把任意会话目录或临时附件路径直接传入。'
        '默认拒绝覆盖，请输出到新文件名。operations 为按顺序执行的列表，'
        '每项 {op: 操作名, value: 参数字符串}，无参数操作 value 为空字符串。'
        '不调用云端模型或 GPU 图形界面。工具错误含稳定代码，请据此最小修复后再调用。'))

    @server.tool()
    def list_operations() -> dict:
        """查询当前 CPU 图像引擎支持的操作及参数。"""
        return invoke(engine.list_operations)

    @server.tool()
    def document_info(input: str) -> dict:
        """只读检查 G:\\LocalCodex\\image-jobs 下的图片或 ORA 文件；先将输入暂存到允许目录。"""
        return invoke(engine.document_info,input=input)

    @server.tool()
    def edit_image(operations: list[dict] | None = None, input: str | None = None,
                   new: str | None = None, dpi: int = 72, output: str | None = None,
                   info: bool = False, export_artboards: str | None = None) -> dict:
        """CPU 编辑并保存图片；input 或 new 二选一，new 示例 800x600。
        operations 示例 [{"op":"resize","value":"400x300"}]。
        output 保存到 G:\\LocalCodex\\image-jobs 下的新文件；.ora 保留图层，.png 导出平面图；info=True 返回检查信息。
        """
        return invoke(engine.edit_image,operations=operations or [],input=input,new=new,dpi=dpi,
                      output=output,info=info,export_artboards=export_artboards)
    server.run(transport='stdio')


if __name__=='__main__': main()
