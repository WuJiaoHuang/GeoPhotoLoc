"""Standalone offline map; never includes camera references."""
import argparse
from pathlib import Path
from geophotoloc.app.refinement_demo import load_refinement_case,build_refinement_map
from run_stage52 import OUT

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--case',default='photo_02');args=parser.parse_args()
 result=load_refinement_case(args.case)
 target=OUT/'demo'/f'refinement_{args.case}.html';target.parent.mkdir(exist_ok=True)
 build_refinement_map(result,offline=True).save(target)
 target.write_text('\n'.join(line.rstrip() for line in target.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
 print(target.relative_to(Path.cwd()))

if __name__=='__main__':main()
