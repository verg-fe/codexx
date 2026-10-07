# Local Python 3.8 compatibility adapter for r0idamcp; see bundled upstream LICENSE.
class FastMCP:
    def __init__(self, **kwargs):self.functions={}
    def tool(self):
        def register(f):self.functions[f.__name__]=f;return f
        return register
import threading
import asyncio
import functools
import logging
import queue
from typing import Any, Callable, Dict, List, get_type_hints, TypedDict, Optional, TypeVar, Generic
import struct
import sys
import re
import ida_kernwin
import ida_idaapi
import ida_funcs
import idautils
import idaapi
import ida_nalt
import idc
import ida_hexrays
import ida_lines
import ida_xref
import ida_entry
import ida_typeinf
import ida_segment
import ida_ua
import ida_bytes

class IDASyncError(Exception):
    pass

class IDASafety:
    ida_kernwin.MFF_READ
    SAFE_NONE = ida_kernwin.MFF_FAST
    SAFE_READ = ida_kernwin.MFF_READ
    SAFE_WRITE = ida_kernwin.MFF_WRITE
call_stack = queue.LifoQueue()

class Metadata(TypedDict):
    pass

class Function(TypedDict):
    pass

class IDAError(Exception):

    def __init__(self, message):
        super().__init__(message)

    @property
    def message(self):
        return self.args[0]
logger = logging.getLogger(__name__)

def sync_wrapper(ff, safety_mode):
    """
    Call a function ff with a specific IDA safety_mode.
    """
    if safety_mode not in [IDASafety.SAFE_READ, IDASafety.SAFE_WRITE]:
        error_str = 'Invalid safety mode {} over function {}'.format(safety_mode, ff.__name__)
        logger.error(error_str)
        raise IDASyncError(error_str)
    res_container = queue.Queue()

    def runned():
        if not call_stack.empty():
            last_func_name = call_stack.get()
            error_str = 'Call stack is not empty while calling the function {} from {}'.format(ff.__name__, last_func_name)
            raise IDASyncError(error_str)
        call_stack.put(ff.__name__)
        try:
            res_container.put(ff())
        except Exception as x:
            res_container.put(x)
        finally:
            call_stack.get()
    ret_val = idaapi.execute_sync(runned, safety_mode)
    res = res_container.get()
    if isinstance(res, Exception):
        raise res
    return res

def get_image_size():
    try:
        info = idaapi.get_inf_structure()
        omin_ea = info.omin_ea
        omax_ea = info.omax_ea
    except AttributeError:
        import ida_ida
        omin_ea = ida_ida.inf_get_omin_ea()
        omax_ea = ida_ida.inf_get_omax_ea()
    image_size = omax_ea - omin_ea
    header = idautils.peutils_t().header()
    if header and header[:4] == b'PE\x00\x00':
        image_size = struct.unpack('<I', header[80:84])[0]
    return image_size

def idaread(f):
    """
    decorator for marking a function as reading from the IDB.
    schedules a request to be made in the main IDA loop to avoid
      inconsistent results.
    MFF_READ constant via: http://www.openrce.org/forums/posts/1827
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        ff = functools.partial(f, *args, **kwargs)
        ff.__name__ = f.__name__
        return sync_wrapper(ff, idaapi.MFF_READ)
    return wrapper

def idawrite(f):
    """
    decorator for marking a function as modifying the IDB.
    schedules a request to be made in the main IDA loop to avoid IDB corruption.
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        ff = functools.partial(f, *args, **kwargs)
        ff.__name__ = f.__name__
        return sync_wrapper(ff, idaapi.MFF_WRITE)
    return wrapper

def is_window_active():
    """Returns whether IDA is currently active"""
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        return False
    app = QApplication.instance()
    if app is None:
        return False
    for widget in app.topLevelWidgets():
        if widget.isActiveWindow():
            return True
    return False

@idaread
def get_metadata_real():
    """Get metadata about the current IDB"""

    def hash(f):
        try:
            return f().hex()
        except:
            return None
    return {'path': idaapi.get_input_file_path(), 'module': idaapi.get_root_filename(), 'base': hex(idaapi.get_imagebase()), 'size': hex(get_image_size()), 'md5': hash(ida_nalt.retrieve_input_file_md5), 'sha256': hash(ida_nalt.retrieve_input_file_sha256), 'crc32': hex(ida_nalt.retrieve_input_file_crc32()), 'filesize': hex(ida_nalt.retrieve_input_file_size())}

def get_function(address, *, raise_error=True):
    fn = idaapi.get_func(address)
    if fn is None:
        if raise_error:
            raise IDAError(f'No function found at address {hex(address)}')
        return None
    try:
        name = fn.get_name()
    except AttributeError:
        name = ida_funcs.get_func_name(fn.start_ea)
    return {'address': hex(fn.start_ea), 'name': name, 'size': hex(fn.end_ea - fn.start_ea)}
DEMANGLED_TO_EA = {}

def create_demangled_to_ea_map():
    for ea in idautils.Functions():
        demangled = idaapi.demangle_name(idc.get_name(ea, 0), idaapi.MNG_NODEFINIT)
        if demangled:
            DEMANGLED_TO_EA[demangled] = ea

def parse_address(address):
    try:
        return int(address, 0)
    except ValueError:
        for ch in address:
            if ch not in '0123456789abcdefABCDEF':
                raise IDAError(f'Failed to parse address: {address}')
        raise IDAError(f'Failed to parse address (missing 0x prefix): {address}')

def _resolve_function_ea(function_address_str, function_name, operation_description):
    """
    Resolves an address from either a string address or a function name.
    One of function_address_str or function_name must be non-empty.
    This EA can then be used with idaapi.get_func() to get the function context.
    """
    if not function_address_str and (not function_name):
        raise IDAError(f'For {operation_description}, either function_address or function_name must be provided.')
    resolved_ea = idaapi.BADADDR
    if function_address_str:
        try:
            resolved_ea = parse_address(function_address_str)
        except IDAError as e:
            if not function_name:
                raise IDAError(f"Invalid function_address '{function_address_str}' for {operation_description} and no function_name provided: {e}")
            pass
    if resolved_ea == idaapi.BADADDR and function_name:
        resolved_ea = idaapi.get_name_ea(idaapi.BADADDR, function_name)
        if resolved_ea == idaapi.BADADDR:
            if not DEMANGLED_TO_EA:
                create_demangled_to_ea_map()
            if function_name in DEMANGLED_TO_EA:
                resolved_ea = DEMANGLED_TO_EA[function_name]
    if resolved_ea == idaapi.BADADDR:
        error_message_parts = [f'For {operation_description}, failed to resolve address. Input was:']
        if function_address_str:
            error_message_parts.append(f"  - function_address: '{function_address_str}'")
        if function_name:
            error_message_parts.append(f"  - function_name: '{function_name}'")
        raise IDAError('\n'.join(error_message_parts))
    return resolved_ea

@idaread
def get_function_by_name_real(name):
    """Get a function by its name"""
    function_address = idaapi.get_name_ea(idaapi.BADADDR, name)
    if function_address == idaapi.BADADDR:
        if len(DEMANGLED_TO_EA) == 0:
            create_demangled_to_ea_map()
        if name in DEMANGLED_TO_EA:
            function_address = DEMANGLED_TO_EA[name]
        else:
            raise IDAError(f'No function found with name {name}')
    return get_function(function_address)

@idaread
def get_function_by_address_real(address):
    """Get a function by its address"""
    return get_function(parse_address(address))

@idaread
def get_current_address_real():
    """Get the address currently selected by the user"""
    return hex(idaapi.get_screen_ea())

@idaread
def get_current_function_real():
    """Get the function currently selected by the user"""
    return get_function(idaapi.get_screen_ea())

class ConvertedNumber(TypedDict):
    pass

def convert_number_real(text, size):
    """Convert a number (decimal, hexadecimal) to different representations"""
    try:
        value = int(text, 0)
    except ValueError:
        raise IDAError(f'Invalid number: {text}')
    if not isinstance(size, int) or size <= 0:
        raise IDAError(f'Invalid size: {size}. Must be a positive integer greater than 0.')
    try:
        bytes_val = value.to_bytes(size, 'little', signed=True)
    except OverflowError:
        raise IDAError(f'Number {text} is too big for {size} bytes')
    ascii_str = ''
    for byte_char in bytes_val.rstrip(b'\x00'):
        if byte_char >= 32 and byte_char <= 126:
            ascii_str += chr(byte_char)
        else:
            ascii_str = None
            break
    return {'decimal': str(value), 'hexadecimal': hex(value), 'bytes': bytes_val.hex(' '), 'ascii': ascii_str, 'binary': bin(value)}
T = TypeVar('T')

class Page(TypedDict, Generic[T]):
    pass

def paginate(data, offset, count):
    if count == 0:
        count = len(data)
    next_offset = offset + count
    if next_offset >= len(data):
        next_offset = None
    return {'data': data[offset:offset + count], 'next_offset': next_offset}

@idaread
def list_functions_real(offset, count):
    """List all functions in the database (paginated)"""
    functions = [get_function(address) for address in idautils.Functions()]
    return paginate(functions, offset, count)

class String(TypedDict):
    pass

def get_strings():
    strings = []
    for item in idautils.Strings():
        string_type = 'C' if item.strtype == 0 else 'Unicode'
        try:
            string = str(item)
            if string:
                strings.append({'address': hex(item.ea), 'length': item.length, 'type': string_type, 'string': string})
        except:
            continue
    return strings

@idaread
def list_strings_real(offset, count):
    """List all strings in the database (paginated)"""
    strings = get_strings()
    return paginate(strings, offset, count)

@idaread
def search_strings_regex_real(pattern_str, offset, count):
    """Search for strings that satisfy a regular expression."""
    strings = get_strings()
    try:
        pattern = re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        raise IDAError(f'Invalid regular expression syntax: {e}')
    try:
        matched_strings = [s for s in strings if s['string'] and re.search(pattern, s['string'])]
    except Exception as e:
        raise IDAError(f'Regular expression matching failed: {e}')
    return paginate(matched_strings, offset, count)

@idaread
def search_strings_substring_real(pattern, offset, count):
    """Search for strings containing the given pattern (case-insensitive)."""
    strings = get_strings()
    matched_strings = [s for s in strings if s['string'] and pattern.lower() in s['string'].lower()]
    return paginate(matched_strings, offset, count)

def decompile_checked(address):
    if not ida_hexrays.init_hexrays_plugin():
        raise IDAError('Hex-Rays decompiler is not available')
    error = ida_hexrays.hexrays_failure_t()
    cfunc = ida_hexrays.decompile_func(idaapi.get_func(address), error, ida_hexrays.DECOMP_WARNINGS)
    if not cfunc:
        message = f'Decompilation failed at {hex(address)}'
        if error.str:
            message += f': {error.str}'
        if error.errea != idaapi.BADADDR:
            message += f' (address: {hex(error.errea)})'
        raise IDAError(message)
    return cfunc

@idaread
def decompile_function_real(address, function_name):
    """Decompile a function at the given address or by its name"""
    resolved_ea = _resolve_function_ea(address, function_name, 'decompiling function')
    cfunc = decompile_checked(resolved_ea)
    if is_window_active():
        ida_hexrays.open_pseudocode(cfunc.entry_ea, ida_hexrays.OPF_REUSE)
    sv = cfunc.get_pseudocode()
    pseudocode = ''
    func_object_for_bounds = idaapi.get_func(cfunc.entry_ea)
    for i, sl in enumerate(sv):
        item = ida_hexrays.ctree_item_t()
        current_line_addr = idaapi.BADADDR
        if cfunc.get_line_item(sl.line, 0, False, None, item, None):
            if item.it and item.it.ea != idaapi.BADADDR:
                current_line_addr = item.it.ea
            else:
                ds = item.dstr().split(': ')
                if len(ds) == 2:
                    try:
                        parsed_addr_from_dstr = int(ds[0], 16)
                        if func_object_for_bounds and func_object_for_bounds.start_ea <= parsed_addr_from_dstr < func_object_for_bounds.end_ea:
                            current_line_addr = parsed_addr_from_dstr
                    except ValueError:
                        pass
        if i == 0 and resolved_ea == cfunc.entry_ea and (current_line_addr == idaapi.BADADDR):
            current_line_addr = cfunc.entry_ea
        line_text = ida_lines.tag_remove(sl.line)
        if len(pseudocode) > 0:
            pseudocode += '\n'
        if current_line_addr != idaapi.BADADDR:
            pseudocode += f'/* line: {i}, address: {hex(current_line_addr)} */ {line_text}'
        else:
            pseudocode += f'/* line: {i} */ {line_text}'
    return pseudocode

@idaread
def disassemble_function_real(start_address):
    """Get assembly code (address: instruction; comment) for a function"""
    start = parse_address(start_address)
    func = idaapi.get_func(start)
    if not func:
        raise IDAError(f'No function found containing address {start_address}')
    if is_window_active():
        ida_kernwin.jumpto(start)
    disassembly = ''
    for address in ida_funcs.func_item_iterator_t(func):
        if len(disassembly) > 0:
            disassembly += '\n'
        disassembly += f'{hex(address)}: '
        disassembly += idaapi.generate_disasm_line(address, idaapi.GENDSM_REMOVE_TAGS)
        comment = idaapi.get_cmt(address, False)
        if not comment:
            comment = idaapi.get_cmt(address, True)
        if comment:
            disassembly += f'; {comment}'
    return disassembly

class Xref(TypedDict):
    pass

@idaread
def get_xrefs_to_real(address):
    """Get all cross references to the given address"""
    xrefs = []
    for xref in idautils.XrefsTo(parse_address(address)):
        xrefs.append({'address': hex(xref.frm), 'type': 'code' if xref.iscode else 'data', 'function': get_function(xref.frm, raise_error=False)})
    return xrefs

@idaread
def get_entry_points_real():
    """Get all entry points in the database"""
    result = []
    for i in range(ida_entry.get_entry_qty()):
        ordinal = ida_entry.get_entry_ordinal(i)
        address = ida_entry.get_entry(ordinal)
        func = get_function(address, raise_error=False)
        if func is not None:
            result.append(func)
    return result

@idaread
def get_segments_real():
    segments = []
    n = 0
    seg = ida_segment.getnseg(n)
    while seg:
        segments.append({'start': seg.start_ea, 'end': seg.end_ea, 'name': ida_segment.get_segm_name(seg), 'class': ida_segment.get_segm_class(seg), 'perm': seg.perm, 'bitness': seg.bitness, 'align': seg.align, 'comb': seg.comb, 'type': seg.type, 'sel': seg.sel, 'flags': seg.flags})
        n += 1
        seg = ida_segment.getnseg(n)
    return segments

@idaread
def get_instruction_length_real(address):
    try:
        insn = ida_ua.insn_t()
        length = ida_ua.decode_insn(insn, address)
        if length == 0:
            print(f'Failed to decode instruction at address {hex(address)}')
            return 0
        return length
    except Exception as e:
        print(f'Error getting instruction length: {str(e)}')
        return 0

@idaread
def get_xrefs_to_field_real(struct_name, field_name):
    """Get all cross references to a named struct field (member)"""
    til = ida_typeinf.get_idati()
    if not til:
        raise IDAError('Failed to retrieve type library.')
    tif = ida_typeinf.tinfo_t()
    if not tif.get_named_type(til, struct_name, ida_typeinf.BTF_STRUCT, True, False):
        print(f"Structure '{struct_name}' not found.")
        return []
    idx = ida_typeinf.get_udm_by_fullname(None, struct_name + '.' + field_name)
    if idx == -1:
        print(f"Field '{field_name}' not found in structure '{struct_name}'.")
        return []
    tid = tif.get_udm_tid(idx)
    if tid == ida_idaapi.BADADDR:
        raise IDAError(f"Unable to get tid for structure '{struct_name}' and field '{field_name}'.")
    xrefs = []
    for xref in idautils.XrefsTo(tid):
        xrefs.append({'address': hex(xref.frm), 'type': 'code' if xref.iscode else 'data', 'function': get_function(xref.frm, raise_error=False)})
    return xrefs

@idawrite
def set_comment_real(address, comment):
    """
    Set a comment for a given address in the function disassembly and pseudocode.
    Returns a string indicating whether the comment was set successfully.
    """
    address = parse_address(address)
    if not idaapi.set_cmt(address, comment, False):
        raise IDAError(f'Failed to set disassembly comment at {hex(address)}')
    else:
        print(f'Disassembly comment set successfully at {hex(address)}')
    cfunc = decompile_checked(address)
    if address == cfunc.entry_ea:
        idc.set_func_cmt(address, comment, True)
        cfunc.refresh_func_ctext()
        return 'Comment set successfully for function entry'
    eamap = cfunc.get_eamap()
    if address not in eamap:
        print(f'Failed to set decompiler comment at {hex(address)}')
        return 'Failed to set decompiler comment'
    nearest_ea = eamap[address][0].ea
    if cfunc.has_orphan_cmts():
        cfunc.del_orphan_cmts()
        cfunc.save_user_cmts()
    tl = idaapi.treeloc_t()
    tl.ea = nearest_ea
    for itp in range(idaapi.ITP_SEMI, idaapi.ITP_COLON):
        tl.itp = itp
        cfunc.set_user_cmt(tl, comment)
        cfunc.save_user_cmts()
        cfunc.refresh_func_ctext()
        if not cfunc.has_orphan_cmts():
            return 'Comment set successfully'
        cfunc.del_orphan_cmts()
        cfunc.save_user_cmts()
    print(f'Failed to set decompiler comment at {hex(address)}')
    return 'Failed to set decompiler comment'

def refresh_decompiler_widget():
    widget = ida_kernwin.get_current_widget()
    if widget is not None:
        vu = ida_hexrays.get_widget_vdui(widget)
        if vu is not None:
            vu.refresh_ctext()

def refresh_decompiler_ctext(function_address):
    error = ida_hexrays.hexrays_failure_t()
    cfunc = ida_hexrays.decompile_func(idaapi.get_func(function_address), error, ida_hexrays.DECOMP_WARNINGS)
    if cfunc:
        cfunc.refresh_func_ctext()

@idawrite
def rename_local_variable_real(function_address, function_name, old_name, new_name):
    """Rename a local variable in a function with name conflict checking"""
    resolved_ea = _resolve_function_ea(function_address, function_name, 'renaming local variable')
    func = idaapi.get_func(resolved_ea)
    if not func:
        input_spec = f"address '{function_address}'" if function_address else ''
        if function_name:
            if input_spec:
                input_spec += ' or '
            input_spec += f"name '{function_name}'"
        return f'Error: No function found for {input_spec} (resolved to {hex(resolved_ea)})'
    func_ea = func.start_ea
    if not new_name:
        if not ida_hexrays.rename_lvar(func_ea, old_name, ''):
            return f"Error: Failed to rename local variable '{old_name}' to default name in function {hex(func_ea)}"
        refresh_decompiler_ctext(func_ea)
        return f"Success: Local variable '{old_name}' renamed to default name in function {hex(func_ea)}"
    cfunc = ida_hexrays.decompile(func_ea)
    if not cfunc:
        return f'Error: Failed to decompile function at {hex(func_ea)}'
    lvars = cfunc.get_lvars()
    for lvar in lvars:
        if lvar.name == new_name and lvar.name != old_name:
            return f"Error: Variable name '{new_name}' already exists in function {hex(func_ea)}"
    if not ida_hexrays.rename_lvar(func_ea, old_name, new_name):
        return f"Error: Failed to rename local variable '{old_name}' to '{new_name}' in function {hex(func_ea)}"
    refresh_decompiler_ctext(func_ea)
    return f"Success: Local variable '{old_name}' renamed to '{new_name}' in function {hex(func_ea)}"

class my_modifier_t(ida_hexrays.user_lvar_modifier_t):

    def __init__(self, var_name, new_type):
        ida_hexrays.user_lvar_modifier_t.__init__(self)
        self.var_name = var_name
        self.new_type = new_type

    def modify_lvars(self, lvars):
        for lvar_saved in lvars.lvvec:
            if lvar_saved.name == self.var_name:
                lvar_saved.type = self.new_type
                return True
        return False

@idawrite
def set_local_variable_type_real(function_address, function_name, variable_name, new_type):
    """Set a local variable's type"""
    resolved_ea = _resolve_function_ea(function_address, function_name, 'setting local variable type')
    func = idaapi.get_func(resolved_ea)
    if not func:
        input_spec = f"address '{function_address}'" if function_address else ''
        if function_name:
            if input_spec:
                input_spec += ' or '
            input_spec += f"name '{function_name}'"
        raise IDAError(f'No function found for {input_spec} (resolved to {hex(resolved_ea)})')
    func_ea = func.start_ea
    try:
        new_tif = ida_typeinf.tinfo_t()
        if ida_typeinf.parse_decl(new_tif, None, new_type + ';', ida_typeinf.PT_SIL) is None:
            try:
                new_tif = ida_typeinf.tinfo_t(new_type, None, ida_typeinf.PT_SIL)
                if not new_tif.is_valid():
                    raise IDAError(f'Failed to parse type (constructor): {new_type}')
            except Exception as e_constr:
                raise IDAError(f'Failed to parse type with parse_decl and constructor: {new_type}. Details: {e_constr}')
    except Exception as e_parse:
        raise IDAError(f'Failed to parse type: {new_type}. Details: {e_parse}')
    if not ida_hexrays.rename_lvar(func_ea, variable_name, variable_name):
        cfunc = ida_hexrays.decompile(func_ea)
        if not cfunc:
            raise IDAError(f'Failed to decompile function at {hex(func_ea)} to find local variable: {variable_name}')
        if not ida_hexrays.rename_lvar(func_ea, variable_name, variable_name):
            raise IDAError(f'Failed to find or prime local variable for type change: {variable_name} in function {hex(func_ea)}')
    modifier = my_modifier_t(variable_name, new_tif)
    if not ida_hexrays.modify_user_lvars(func_ea, modifier):
        raise IDAError(f'Failed to modify local variable type: {variable_name} in function {hex(func_ea)}')
    refresh_decompiler_ctext(func_ea)
    return f"Successfully changed type of variable '{variable_name}' in function at {hex(func_ea)} to '{new_type}'"

@idawrite
def rename_global_variable_real(old_name, new_name):
    """Rename a global variable"""
    ea = idaapi.get_name_ea(idaapi.BADADDR, old_name)
    if not idaapi.set_name(ea, new_name):
        raise IDAError(f'Failed to rename global variable {old_name} to {new_name}')
    refresh_decompiler_ctext(ea)
    return f"Success: global variable '{old_name}' renamed to '{new_name}' in function {hex(ea)}"

@idawrite
def set_global_variable_type_real(variable_name, new_type):
    """Set a global variable's type"""
    ea = idaapi.get_name_ea(idaapi.BADADDR, variable_name)
    tif = ida_typeinf.tinfo_t(new_type, None, ida_typeinf.PT_SIL)
    if not tif:
        raise IDAError(f'Parsed declaration is not a variable type')
    if not ida_typeinf.apply_tinfo(ea, tif, ida_typeinf.PT_SIL):
        raise IDAError(f'Failed to apply type')
    return f"Successfully changed type of variable '{variable_name}' in function at {hex(ea)} to '{new_type}'"

@idawrite
def rename_function_real(function_address, function_name, new_name):
    """Rename a function with name conflict checking."""
    resolved_ea = _resolve_function_ea(function_address, function_name, 'renaming function')
    func = idaapi.get_func(resolved_ea)
    if not func:
        input_spec = f"address '{function_address}'" if function_address else ''
        if function_name:
            if input_spec:
                input_spec += ' or '
            input_spec += f"name '{function_name}'"
        raise IDAError(f'No function found for {input_spec} (resolved to {hex(resolved_ea)}).')
    current_func_ea = func.start_ea
    old_name = idaapi.get_name(current_func_ea)
    if new_name and new_name != old_name:
        existing_ea = idaapi.get_name_ea(idaapi.BADADDR, new_name)
        if existing_ea != idaapi.BADADDR and existing_ea != current_func_ea:
            conflicting_item_type = 'a global symbol'
            conflicting_item_name = idaapi.get_name(existing_ea)
            if idaapi.get_func(existing_ea):
                conflicting_item_type = f"function '{conflicting_item_name}'"
            return f"Error: Name '{new_name}' is already used by {conflicting_item_type} at {hex(existing_ea)}."
    if not idaapi.set_name(current_func_ea, new_name if new_name else '', idaapi.SN_CHECK):
        if not idaapi.set_name(current_func_ea, new_name if new_name else ''):
            raise IDAError(f"Failed to rename function {hex(current_func_ea)} from '{old_name}' to '{new_name or 'default name'}'. This could be due to invalid characters in the new name or other IDA restrictions.")
    refresh_decompiler_ctext(current_func_ea)
    actual_new_name = idaapi.get_name(current_func_ea)
    return f"Successfully renamed function from '{old_name}' to '{actual_new_name}' at {hex(current_func_ea)}"

@idawrite
def set_function_prototype_real(function_address, function_name, prototype):
    """Set a function's prototype"""
    resolved_ea = _resolve_function_ea(function_address, function_name, 'setting function prototype')
    func = idaapi.get_func(resolved_ea)
    if not func:
        input_spec = f"address '{function_address}'" if function_address else ''
        if function_name:
            if input_spec:
                input_spec += ' or '
            input_spec += f"name '{function_name}'"
        raise IDAError(f'No function found for {input_spec} (resolved to {hex(resolved_ea)})')
    func_ea = func.start_ea
    try:
        tif = ida_typeinf.tinfo_t()
        parsed_decl = prototype
        if not parsed_decl.strip().endswith(';'):
            pass
        temp_tif = ida_typeinf.tinfo_t()
        prototype_to_parse = prototype.strip()
        if not prototype_to_parse.endswith(';'):
            prototype_to_parse += ';'
        if ida_typeinf.parse_decl(temp_tif, None, prototype_to_parse, ida_typeinf.PT_SIL) is None:
            raise IDAError(f"Failed to parse prototype string: '{prototype}'. parse_decl returned None.")
        if not temp_tif.is_func():
            raise IDAError(f"Parsed declaration '{prototype}' is not a function type.")
        if not ida_typeinf.apply_tinfo(func_ea, temp_tif, ida_typeinf.PT_SIL):
            raise IDAError(f"Failed to apply type information for prototype '{prototype}' to function at {hex(func_ea)}.")
        refresh_decompiler_ctext(func_ea)
        return f"Successfully set prototype for function at {hex(func_ea)} to '{prototype}'"
    except Exception as e:
        raise IDAError(f"Failed to set function prototype '{prototype}' at {(hex(func_ea) if func else resolved_ea)}: {str(e)}")

def parse_decls_ctypes(decls, hti_flags):
    if sys.platform == 'win32':
        import ctypes
        assert isinstance(decls, str), 'decls must be a string'
        assert isinstance(hti_flags, int), 'hti_flags must be an int'
        c_decls = decls.encode('utf-8')
        c_til = None
        ida_dll = ctypes.CDLL('ida')
        ida_dll.parse_decls.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
        ida_dll.parse_decls.restype = ctypes.c_int
        messages = []

        @ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p)
        def magic_printer(fmt, arg1):
            if fmt.count(b'%') == 1 and b'%s' in fmt:
                formatted = fmt.replace(b'%s', arg1)
                messages.append(formatted.decode('utf-8'))
                return len(formatted) + 1
            else:
                messages.append(f'unsupported magic_printer fmt: {repr(fmt)}')
                return 0
        errors = ida_dll.parse_decls(c_til, c_decls, magic_printer, hti_flags)
    else:
        errors = ida_typeinf.parse_decls(None, decls, False, hti_flags)
        messages = []
    return (errors, messages)

@idawrite
def declare_c_type_real(c_declaration):
    """Create or update a local type from a C declaration"""
    flags = ida_typeinf.PT_SIL | ida_typeinf.PT_EMPTY | ida_typeinf.PT_TYP
    errors, messages = parse_decls_ctypes(c_declaration, flags)
    pretty_messages = '\n'.join(messages)
    if errors > 0:
        raise IDAError(f'Failed to parse type:\n{c_declaration}\n\nErrors:\n{pretty_messages}')
    return f'success\n\nInfo:\n{pretty_messages}'
mcp = FastMCP(name='myServer')

@mcp.tool()
def check_connection():
    """Checks the connection status with the IDA Pro MCP server and retrieves the loaded module name."""
    try:
        metadata = get_metadata_real()
        return f"Successfully connected to IDA Pro (open file: {metadata['module']})"
    except Exception as e:
        if sys.platform == 'darwin':
            shortcut = 'Ctrl+Option+M'
        else:
            shortcut = 'Ctrl+Alt+M'
        return f'Failed to connect to IDA Pro! Did you run Edit -> Plugins -> MCP ({shortcut}) to start the server?'

@mcp.tool()
def get_project_metadata():
    """Retrieves metadata about the currently IDA-Pro project."""
    return get_metadata_real()

@mcp.tool()
def get_function_info_by_name(name):
    """Retrieves details (address, name, size) for a function using its name (mangled or demangled)."""
    return get_function_by_name_real(name)

@mcp.tool()
def get_function_info_by_address(address):
    """Retrieves info (address, name, size) for a function using its starting address."""
    return get_function_by_address_real(address)

@mcp.tool()
def get_current_address():
    """Gets the address currently selected (under the cursor) in the IDA user interface."""
    return get_current_address_real()

@mcp.tool()
def get_current_function():
    """Gets details (address, name, size) of the function containing the currently selected in IDA window."""
    return get_current_function_real()

@mcp.tool()
def convert_number(text, size):
    """Converts a number string (hex/dec) into various representations: decimal, hexadecimal, bytes (hex), potential ASCII, and binary."""
    return convert_number_real(text, size)

@mcp.tool()
def list_functions(offset, count):
    """Lists functions defined in the analysis database, with support for pagination."""
    return list_functions_real(offset, count)

@mcp.tool()
def list_strings(offset, count):
    """Lists string literals found in the analysis database, with support for pagination."""
    return list_strings_real(offset, count)

@mcp.tool()
def search_strings_regex(pattern_str, offset, count):
    """Searches for string literals matching a given regular expression (case-insensitive), returning results paginated."""
    return search_strings_regex_real(pattern_str, offset, count)

@mcp.tool()
def search_strings_substring(pattern, offset, count):
    """Searches for string literals containing a given substring (case-insensitive), returning results paginated."""
    return search_strings_substring_real(pattern, offset, count)

@mcp.tool()
def decompile_function(function_address, function_name):
    """Decompiles the function specified by function_address or function_name."""
    return decompile_function_real(function_address, function_name)

@mcp.tool()
def disassemble_function(start_address):
    """Retrieves the disassembly listing for a function, specified by its start address."""
    return disassemble_function_real(start_address)

@mcp.tool()
def get_xrefs_to(address):
    """Finds all code and data cross-references (Xrefs) that point *to* the given address."""
    return get_xrefs_to_real(address)

@mcp.tool()
def get_entry_points():
    """Lists all defined program entry point functions in the analysis database."""
    return get_entry_points_real()

@mcp.tool()
def set_comment(address, comment):
    """Sets or updates a comment at a specific address. For line comments, the line address is presented in the decompiled code."""
    return set_comment_real(address, comment)

@mcp.tool()
def rename_local_variable(function_address, function_name, old_name, new_name):
    """Renames a local variable in a function. Identified by function_address or function_name."""
    return rename_local_variable_real(function_address, function_name, old_name, new_name)

@mcp.tool()
def set_local_variable_type(function_address, function_name, variable_name, new_type):
    """Sets the data type of a local variable in the function. Identified by function_address or function_name, if provid one, the other one must be empty string("")."""
    return set_local_variable_type_real(function_address, function_name, variable_name, new_type)

@mcp.tool()
def rename_global_variable(old_name, new_name):
    """Renames a global variable (data location) or function identified by its current name."""
    return rename_global_variable_real(old_name, new_name)

@mcp.tool()
def set_global_variable_type(variable_name, new_type):
    """Sets the data type of a global variable identified by its name."""
    return set_global_variable_type_real(variable_name, new_type)

@mcp.tool()
def rename_function(function_address, function_name, new_name):
    """Renames the function. Identified by function_address or function_name."""
    return rename_function_real(function_address, function_name, new_name)

@mcp.tool()
def set_function_prototype(function_address, function_name, prototype):
    """Sets the C-style function prototype for the function. Identified by function_address or function_name, if provid one, the other one must be empty string."""
    return set_function_prototype_real(function_address, function_name, prototype)

@mcp.tool()
def declare_c_type(c_declaration):
    """Declares or updates a local type (struct, union, enum, typedef) within IDA's type system using a C declaration string."""
    return declare_c_type_real(c_declaration)

@mcp.tool()
def get_segments():
    """Retrieves information about all memory segments defined in the analysis database (e.g., .text, .data)."""
    return get_segments_real()

@mcp.tool()
def get_machine_instruction_length(address):
    """Gets the length (in bytes) of the machine instruction located at the given address."""
    parsed_address = parse_address(address)
    return get_instruction_length_real(parsed_address)

@mcp.tool()
@idaread
def get_bytes(address, size):
    """Reads a sequence of byte values from the specified address. Returns a list of integers (0-255)."""
    parsed_ea = parse_address(address)
    try:
        result = [ida_bytes.get_byte(parsed_ea + i) for i in range(size)]
        return result
    except Exception as e:
        print(f'Error in get_bytes: {str(e)}')
        raise IDAError(f'Failed to read bytes at {hex(parsed_ea)}: {str(e)}') from e

@mcp.tool()
def get_xrefs_to_field(struct_name, field_name):
    """Get all cross references to a named struct field (member)"""
    return get_xrefs_to_field_real(struct_name, field_name)
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
_config=json.loads(Path(r"D:\LocalCodex\tools\ida-mcp\connection.json").read_text(encoding="utf-8"))
class _Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        if self.headers.get("Authorization")!="Bearer "+_config["token"]:
            self.send_error(403);return
        try:
            size=int(self.headers.get("Content-Length","0"))
            if not 0<size<1000000:raise ValueError("Invalid request size")
            req=json.loads(self.rfile.read(size))
            result=mcp.functions[req["name"]](**req.get("arguments",{}))
            answer={"result":result}
        except Exception as exc:answer={"error":str(exc)}
        raw=json.dumps(answer,ensure_ascii=False).encode("utf-8")
        self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
_server=None
def start_server():
    global _server
    if _server is None:
        _server=ThreadingHTTPServer(("127.0.0.1",26868),_Handler)
        threading.Thread(target=_server.serve_forever,daemon=True).start()
        print("Codexx IDA bridge ready: 127.0.0.1:26868")
class CodexxIDA(idaapi.plugin_t):
    flags=idaapi.PLUGIN_KEEP
    comment="Local r0idamcp compatibility bridge"
    help=""
    wanted_name="Codexx IDA MCP"
    wanted_hotkey=""
    def init(self):
        try:start_server();return idaapi.PLUGIN_KEEP
        except Exception as exc:print("Codexx IDA bridge: "+str(exc));return idaapi.PLUGIN_SKIP
    def run(self,arg):start_server()
    def term(self):pass
def PLUGIN_ENTRY():return CodexxIDA()
