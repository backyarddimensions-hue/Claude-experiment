import json,collections,sys
d=json.load(open(sys.argv[1]))
F=d['functions']; print('tables',d['tables'])
ex=[f for f in F if f['exported']]
print('all',len(F),'exported',len(ex))
def klass(f):
    if f['inferred']: return 'effects'
    return 'pure' if f['pure'] else 'unclassified'
print('exported:',collections.Counter(klass(f) for f in ex)); print('all:',collections.Counter(klass(f) for f in F))
print('exported w/ unresolved', sum(1 for f in ex if f.get('unresolved')), 'all unresolved sites', sum(len(f.get('unresolved',[])) for f in F))
c=collections.Counter()
for f in ex:
    if klass(f)=='unclassified':
        for r in f['impure_reasons']: c[r]+=1
print('reasons(exported unclassified):',c.most_common())
c=collections.Counter()
for f in F:
    for e in f.get('impure_examples',[]):
        if e.startswith('unclassified-external') and 'via ' not in e: c[e.split(': ')[1].split(' at ')[0]]+=1
print('unclassified externals:',c.most_common(70))
for f in F:
    for u in f.get('unresolved',[]): print('UNRES',f['id'],u)
