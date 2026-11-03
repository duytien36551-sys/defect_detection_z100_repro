"""Validate packaged split lists and generate a machine-local dataset config on demand."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='optional generated config path outside this submission directory')
    args=parser.parse_args()
    data=ROOT/'data/dataset'
    config=json.loads((data/'data.yaml').read_text(encoding='utf-8'))
    counts={}
    for split in ('test',):
        listing=data/f'{split}.txt'
        items=[line.strip() for line in listing.read_text(encoding='utf-8').splitlines() if line.strip()]
        for item in items:
            image=(listing.parent/item).resolve()
            if not image.is_relative_to(data):raise ValueError(f'Outside dataset: {split}')
            if not image.is_file():raise FileNotFoundError(image)
            parts=list(image.relative_to(data).parts)
            if parts[0]!='images':raise ValueError('Expected images/<split>/<name>')
            parts[0]='labels'
            label=data/Path(*parts).with_suffix('.txt')
            if not label.is_file():raise FileNotFoundError(label)
        counts[split]=len(items)
    selected=json.loads((data/'selected_manifest.json').read_text(encoding='utf-8'))['images']
    assert len(selected)==counts['test']==300
    assert len({r['id'] for r in selected})==300
    for r in selected:
        for kind in ('image','label'):
            assert hashlib.sha256((data/r[kind]).read_bytes()).hexdigest()==r[kind+'_sha256']
    if args.output:
        output=args.output.resolve()
        if output.is_relative_to(ROOT):raise ValueError('Choose a generated output outside the submission directory')
        if output.exists():raise FileExistsError(output)
        config['path']=str(data.resolve())
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status='PASS_DATASET_PATHS_AND_LABELS',images_by_split=counts, curated_showcase=True, representative_test_set=False,
                         generated_config=bool(args.output),training_started=False),indent=2))


if __name__=='__main__':main()
