import json
from utils.multiprocessor import local_mt

def check(line):
    datum = json.loads(line)
    if 'tvqa' in datum['video']:
        return line
    try:
        datum['video']
        return line
    except:
        print(datum['video'], 'not exists')

lines = open('mvbench.jsonl').readlines()
existed_lines = local_mt(lines, check, desc='check', num_workers=8)
existed_lines = [line for line in existed_lines if line is not None]

with open('mvbench_video_existed.jsonl', 'w') as f:
    f.writelines(existed_lines)