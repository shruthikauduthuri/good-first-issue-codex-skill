"""Compare configured inference endpoints against identical synthetic GitHub fixtures."""
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service.agent import run_find
from service.schemas import FindRequest
from service.errors import classify
from fixture import FakeGitHub


def evaluate(case,config):
    gh=FakeGitHub()
    gh.issue.update(title=case['title'],body=case['body'])
    gh.issue['labels']=[{'name':'help wanted' if case['difficulty']=='hard' else 'good first issue'}]
    if case['scenario']=='assigned':gh.issue['assignees']=[{'login':'contributor'}]
    if case['scenario']=='claimed':gh.comments=[{'body':"I'll take this"}]
    if case['scenario']=='inactive':gh.active=False
    if case['scenario']=='no_guide':gh.guide=False
    started=time.monotonic()
    try:
        result=run_find(FindRequest(description=case['prompt'],language='Python',count=1),config=config,github=gh)
        expected=case['scenario']=='eligible'
        passed=(len(result.results)==1 and result.results[0].difficulty==case['difficulty']) if expected else not result.results
        return dict(id=case['id'],status='success',passed=passed,metrics=result.metrics,result_count=len(result.results))
    except Exception as exc:
        _,code,_=classify(exc)
        return dict(id=case['id'],status='error',passed=False,error_category=code,elapsed_seconds=round(time.monotonic()-started,3))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--provider',required=True)
    p.add_argument('--base-url',required=True)
    p.add_argument('--model',required=True)
    p.add_argument('--key-env',default='AKAMAI_API_KEY')
    p.add_argument('--env-file',type=Path)
    p.add_argument('--case',action='append')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.env_file:
        for line in args.env_file.read_text().splitlines():
            k,sep,v=line.partition('=')
            if sep and not k.strip().startswith('#'):os.environ[k.strip()]=v.strip().strip('\"\'')
    if not args.base_url.startswith('https://') or not os.getenv(args.key_env):p.error('HTTPS endpoint and configured key environment variable required')
    config={'base_url':args.base_url,'model':args.model,'AKAMAI_API_KEY':os.environ[args.key_env],'GITHUB_TOKEN':'fixture-only'}
    cases=json.loads(Path(__file__).with_name('cases.json').read_text())
    if args.case:cases=[c for c in cases if c['id'] in args.case]
    if not cases:p.error('No matching cases')
    report={'provider':args.provider,'model':args.model,'dataset':'synthetic-github-v1','results':[]}
    for case in cases:
        row=evaluate(case,config);report['results'].append(row)
        print(case['id'],row['status'],'pass' if row['passed'] else 'fail',flush=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        time.sleep(2)
    print('Passed:',sum(r['passed'] for r in report['results']),'/',len(cases))

if __name__=='__main__':main()
