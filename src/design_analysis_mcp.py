"""Evidence-oriented mesh and simulation result checks for local design jobs."""
from __future__ import annotations

import json
from pathlib import Path
import time

from mcp.server.fastmcp import FastMCP
import trimesh

server = FastMCP('mycodex-design-analysis')


@server.tool()
def stl_inspect(path: str, expected_unit: str = '', expected_dimensions_mm: list[float] | None = None) -> dict:
    """Read a real STL and report bounds, watertightness, normals, components and unit evidence.

    STL itself does not encode units. A matching .units.json sidecar is required to
    assert physical scale; otherwise the output explicitly leaves scale unverified.
    """
    file = Path(path).expanduser().resolve(strict=True)
    if file.suffix.lower() != '.stl':
        raise ValueError('输入必须是 STL 文件。')
    mesh = trimesh.load(file, force='mesh', process=True)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError('STL 未包含可用三角网格。')
    bounds = mesh.bounds.tolist()
    extents = mesh.extents.tolist()
    sidecar = file.with_suffix('.units.json')
    units = None
    if sidecar.is_file():
        units = json.loads(sidecar.read_text(encoding='utf-8-sig'))
    valid_unit = bool(units and units.get('unit') in ('mm', 'cm', 'm', 'in') and units.get('source_parameters'))
    expected_match = None
    if expected_dimensions_mm is not None:
        if len(expected_dimensions_mm) != 3 or any(float(x) <= 0 for x in expected_dimensions_mm):
            raise ValueError('expected_dimensions_mm 必须是 3 个正数。')
        if valid_unit and units.get('unit') == 'mm':
            expected_match = all(abs(float(extents[i]) - float(expected_dimensions_mm[i])) <= max(0.05, float(expected_dimensions_mm[i]) * 0.002) for i in range(3))
    degenerate_count=int(len(mesh.faces)-len(mesh.nondegenerate_faces()))
    report = {
        'path': str(file), 'bytes': file.stat().st_size,
        'faces': int(len(mesh.faces)), 'vertices': int(len(mesh.vertices)),
        'bounds_in_stl_units': bounds, 'extents_in_stl_units': extents,
        'is_watertight': bool(mesh.is_watertight), 'is_winding_consistent': bool(mesh.is_winding_consistent),
        'body_count': int(mesh.body_count), 'volume_in_cubic_stl_units': float(mesh.volume),
        'degenerate_faces': degenerate_count,
        'unit_sidecar': str(sidecar) if sidecar.is_file() else None,
        'unit_evidence_valid': valid_unit, 'declared_unit': units.get('unit') if valid_unit else None,
        'expected_unit': expected_unit or None,
        'expected_unit_match': (units.get('unit') == expected_unit) if valid_unit and expected_unit else None,
        'expected_dimensions_mm': expected_dimensions_mm,
        'expected_dimensions_match': expected_match,
        'physical_scale_status': 'verified_from_sidecar' if valid_unit else 'unknown_stl_has_no_unit_metadata',
        'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    report['printable_mesh_basics_pass'] = report['is_watertight'] and report['is_winding_consistent'] and report['body_count'] == 1
    output = file.with_suffix('.inspection.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report['report_path'] = str(output)
    return report


@server.tool()
def compare_fem_runs(run_a_manifest: str, run_b_manifest: str) -> dict:
    """Compare two mesh-refinement FEM runs with identical physical setup."""
    paths = [Path(run_a_manifest).expanduser().resolve(strict=True), Path(run_b_manifest).expanduser().resolve(strict=True)]
    runs = [json.loads(path.read_text(encoding='utf-8-sig')) for path in paths]
    required = ('solver', 'geometry', 'material', 'units', 'boundary_conditions', 'load', 'mesh', 'max_displacement', 'max_von_mises')
    for index, run in enumerate(runs):
        missing = [key for key in required if not run.get(key)]
        if missing:
            raise ValueError(f'第 {index+1} 个 FEM 清单缺少 {missing}，无法做量级或收敛比较。')
        if run['solver'].get('status') != 'completed' or not run['solver'].get('result_file'):
            raise ValueError(f'第 {index+1} 个 FEM 求解没有完成或没有结果文件。')
        result_file = Path(run['solver']['result_file']).expanduser().resolve(strict=True)
        if result_file.stat().st_size == 0:
            raise ValueError(f'第 {index+1} 个 FEM 结果文件为空。')
        mesh = run['mesh']
        if not isinstance(mesh, dict) or float(mesh.get('max_element_size_mm') or 0) <= 0:
            raise ValueError(f'第 {index+1} 个 FEM 清单没有有效的网格尺寸。')
        if int(mesh.get('node_count') or 0) <= 0:
            raise ValueError(f'第 {index+1} 个 FEM 清单没有实际网格节点数。')
    a, b = runs
    comparable = all(a[key] == b[key] for key in ('geometry', 'material', 'units', 'boundary_conditions', 'load'))
    if not comparable:
        raise ValueError('两次网格收敛 FEM 的几何、材料、单位、约束或载荷不一致；不能将差异归因于网格。')
    if a['mesh'] == b['mesh'] or int(a['mesh']['node_count']) == int(b['mesh']['node_count']):
        raise ValueError('网格参数或实际节点数没有变化；不能报告为网格收敛对照。')
    disp_a=float(a['max_displacement']['value']); disp_b=float(b['max_displacement']['value'])
    stress_a=float(a['max_von_mises']['value']); stress_b=float(b['max_von_mises']['value'])
    result={'comparable': True, 'comparison_kind': 'mesh_refinement',
            'same_geometry_material_load_supports_units': True,
            'mesh_a': a['mesh'], 'mesh_b': b['mesh'],
            'max_displacement_a': a['max_displacement'], 'max_displacement_b': b['max_displacement'],
            'max_von_mises_a': a['max_von_mises'], 'max_von_mises_b': b['max_von_mises'],
            'displacement_relative_change': abs(disp_b-disp_a)/max(abs(disp_a),1e-15),
            'stress_relative_change': abs(stress_b-stress_a)/max(abs(stress_a),1e-15),
            'result_files': [a['solver']['result_file'], b['solver']['result_file']],
            'interpretation': 'Numerical comparison only; engineering safety still requires an independent analytical or qualified review.'}
    destination=paths[1].with_name(paths[1].stem+'-mesh-comparison.json')
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['report_path']=str(destination)
    return result


@server.tool()
def compare_design_iterations(run_before_manifest: str, run_after_manifest: str) -> dict:
    """Compare saved FEM design iterations with identical load/material setup and explicit geometry change."""
    paths = [Path(run_before_manifest).expanduser().resolve(strict=True), Path(run_after_manifest).expanduser().resolve(strict=True)]
    runs = [json.loads(path.read_text(encoding='utf-8-sig')) for path in paths]
    required = ('solver', 'geometry', 'material', 'units', 'boundary_conditions', 'load', 'mesh', 'max_displacement', 'max_von_mises')
    for index, run in enumerate(runs):
        missing = [key for key in required if not run.get(key)]
        if missing:
            raise ValueError(f'第 {index+1} 个设计迭代清单缺少 {missing}。')
        if run['solver'].get('status') != 'completed' or not run['solver'].get('result_file'):
            raise ValueError(f'第 {index+1} 个设计迭代求解未完成或缺少结果文件。')
        result_file = Path(run['solver']['result_file']).expanduser().resolve(strict=True)
        if result_file.stat().st_size == 0:
            raise ValueError(f'第 {index+1} 个 FEM 结果文件为空。')
        if int(run['mesh'].get('node_count') or 0) <= 0:
            raise ValueError(f'第 {index+1} 个设计迭代缺少实际网格节点数。')
    before, after = runs
    for key in ('material', 'units', 'boundary_conditions', 'load'):
        if before[key] != after[key]:
            raise ValueError(f'设计迭代的 {key} 不一致；不能将差异归因于几何修改。')
    if before['geometry'] == after['geometry']:
        raise ValueError('两次几何参数相同；该工具要求真实的设计改动。')
    disp_a=float(before['max_displacement']['value']); disp_b=float(after['max_displacement']['value'])
    stress_a=float(before['max_von_mises']['value']); stress_b=float(after['max_von_mises']['value'])
    result={'comparable': True, 'comparison_kind': 'design_iteration', 'geometry_before': before['geometry'],
            'geometry_after': after['geometry'], 'mesh_before': before['mesh'], 'mesh_after': after['mesh'],
            'max_displacement_before': before['max_displacement'], 'max_displacement_after': after['max_displacement'],
            'max_von_mises_before': before['max_von_mises'], 'max_von_mises_after': after['max_von_mises'],
            'displacement_relative_change': abs(disp_b-disp_a)/max(abs(disp_a),1e-15),
            'stress_relative_change': abs(stress_b-stress_a)/max(abs(stress_a),1e-15),
            'result_files': [before['solver']['result_file'], after['solver']['result_file']],
            'interpretation': 'Numerical comparison only; engineering safety still requires an independent analytical or qualified review.'}
    destination=paths[1].with_name(paths[1].stem+'-design-comparison.json')
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['report_path']=str(destination)
    return result


@server.tool()
def artifact_inventory(job_directory: str) -> dict:
    """List files produced in a design job, including saved CAD, solver, mesh and screenshot artifacts."""
    root=Path(job_directory).expanduser().resolve(strict=True)
    if not root.is_dir():raise ValueError('任务目录不是文件夹。')
    files=[]
    for path in sorted(root.rglob('*')):
        if path.is_file():
            files.append({'path':str(path),'bytes':path.stat().st_size,'suffix':path.suffix.lower()})
            if len(files)>=500:break
    return {'job_directory':str(root),'files':files,'truncated':len(files)>=500,
            'evidence_types':{ext:sum(1 for item in files if item['suffix']==ext) for ext in sorted({item['suffix'] for item in files})}}


if __name__ == '__main__':
    server.run('stdio')
