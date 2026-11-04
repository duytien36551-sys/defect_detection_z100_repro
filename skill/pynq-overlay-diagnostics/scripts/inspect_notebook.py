#!/usr/bin/env python3
"""Read PYNQ notebook code without executing it or trusting saved outputs."""
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

def inspect(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Notebook exceeds 32 MiB limit')
    notebook = json.loads(raw.decode('utf-8-sig'))
    if notebook.get('nbformat') != 4 or not isinstance(notebook.get('cells'), list):
        raise ValueError('Expected nbformat 4 notebook')
    calls, issues, imports = [], [], []
    for index, cell in enumerate(notebook['cells']):
        if cell.get('cell_type') != 'code':
            continue
        source = cell.get('source', '')
        if isinstance(source, list):
            source = ''.join(source)
        if not isinstance(source, str):
            raise ValueError('Invalid notebook source')
        # Line removal preserves line numbering; unsupported cells remain unknown.
        lines = source.splitlines()
        if lines and lines[0].lstrip().startswith('%%'):
            magic = lines[0].strip()
            if magic.split()[0] not in ('%%time', '%%timeit', '%%capture'):
                issues.append({'cell': index, 'code': 'CELL_NOT_PARSED', 'detail': 'Unsupported cell magic: ' + magic})
                continue
        cleaned = '\n'.join('' if line.lstrip().startswith(('%', '!')) else line for line in lines)
        if any(line.lstrip().startswith(('%', '!')) for line in lines):
            issues.append({'cell': index, 'code': 'MAGICS_NOT_EXECUTED', 'detail': 'Magic/shell lines excluded from AST inspection.'})
        try:
            tree = ast.parse(cleaned)
        except SyntaxError as error:
            issues.append({'cell': index, 'code': 'CELL_NOT_PARSED', 'detail': str(error)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append({'cell': index, 'module': node.module, 'names': [n.name for n in node.names]})
            elif isinstance(node, ast.Import):
                imports.append({'cell': index, 'module': None, 'names': [n.name for n in node.names]})
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                leaf = name.rsplit('.', 1)[-1]
                if leaf in ('Overlay', 'Bitstream', 'allocate', 'Xlnk', 'cma_array', 'transfer', 'wait', 'wait_async', 'flush', 'invalidate', 'sync_to_device', 'sync_from_device', 'download', 'freebuffer'):
                    args = [ast.unparse(v) for v in node.args]
                    keywords = {kw.arg or '**': ast.unparse(kw.value) for kw in node.keywords}
                    calls.append({'cell': index, 'line': node.lineno, 'call': name, 'args': args, 'keywords': keywords})
                    if leaf == 'Overlay' and keywords.get('download') != 'False':
                        issues.append({'cell': index, 'code': 'OVERLAY_MAY_PROGRAM_PL', 'detail': 'Executing this Overlay call may program PL; inspect the selected build and current hardware before execution.'})
                    if leaf in ('Xlnk', 'cma_array'):
                        issues.append({'cell': index, 'code': 'LEGACY_ALLOCATION', 'detail': 'Legacy Xlnk allocation; adapt to pynq.allocate and the actual installed PYNQ version.'})
                    if leaf == 'wait':
                        issues.append({'cell': index, 'code': 'WAIT_BOUND_NOT_PROVEN', 'detail': 'PYNQ DMA wait may poll indefinitely; this static call does not establish an external timeout or TLAST correctness.'})
    return {'schema': 'pynq-notebook-inspection-v1', 'status': 'STATIC_INSPECTION_COMPLETE', 'sha256': hashlib.sha256(raw).hexdigest(), 'file': Path(path).name, 'hardware_execution': False, 'saved_outputs_used_as_evidence': False, 'imports': imports, 'pynq_related_calls': calls, 'findings': issues, 'limits': ['AST matching is syntactic, not symbolic execution: aliases, dynamically built calls and register writes require manual review.', 'Call order, buffer ownership, TLAST, driver cache maintenance and output quality are not runtime-verified.', 'Saved notebook outputs and execution_count do not establish a current hardware run.']}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notebook', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args(argv)
    if args.notebook.resolve() == args.out.resolve():
        p.error('--out cannot overwrite notebook')
    try:
        report = inspect(args.notebook)
        code = 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        report = {'status': 'INVALID_INPUT', 'hardware_execution': False, 'error': str(error)}
        code = 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.out)}, ensure_ascii=False))
    return code

if __name__ == '__main__':
    sys.exit(main())
