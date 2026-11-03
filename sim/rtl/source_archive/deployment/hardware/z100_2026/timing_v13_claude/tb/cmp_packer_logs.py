# Compare packer logs per job: good jobs must be identical; fault jobs
# (kind 1 bad beat, 2 cancel) must have outputs that are prefixes of each other
# and identical ERR lines.
import sys
def jobs(path):
    out={}; cur=None
    for ln in open(path):
        ln=ln.rstrip('\n')
        if ln.startswith('JOB'): cur=tuple(map(int,ln.split()[1:])); out[cur]=[]
        elif cur is not None: out[cur].append(ln)
    return out
a,b=jobs(sys.argv[1]),jobs(sys.argv[2]); bad=0; nf=0
assert list(a)==list(b), "job lists differ"
for k in a:
    if k[1] in (1,2):
        nf+=1
        oa=[x for x in a[k] if x.startswith('OUT')]; ob=[x for x in b[k] if x.startswith('OUT')]
        n=min(len(oa),len(ob))
        if oa[:n]!=ob[:n] or [x for x in a[k] if not x.startswith('OUT')]!=[x for x in b[k] if not x.startswith('OUT')]:
            bad+=1; print("FAULT JOB MISMATCH",k)
    elif a[k]!=b[k]: bad+=1; print("GOOD JOB MISMATCH",k)
print(f"jobs={len(a)} fault_jobs={nf} mismatches={bad}")
sys.exit(1 if bad else 0)
