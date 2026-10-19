"""Valida contratos de referencia, fixtures y trazabilidad. No ejecuta SUMO."""
from pathlib import Path
import json,csv,copy,sys
from modelos_contrato import MODELS,Case,Request,Plan,validate_request_against_case,validate_plan_against_case
REPO=Path(__file__).resolve().parents[2]
SCHEMAS=REPO/'schemas'
FIXTURES=REPO/'tests'/'fixtures'
MATRICES=REPO/'documentacion'/'matrices'
checks=[]
def check(name,fn):
    fn();checks.append(name)
def parse(name,data): return MODELS[name].model_validate_json(json.dumps(data))
def reject(name,data):
    try: parse(name,data)
    except ValueError:return
    raise AssertionError('Se aceptó fixture negativo '+name)
def read(name):return json.loads((FIXTURES/name).read_text())
def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
for name in MODELS:
    data=read(name+'.json')
    check('Contrato '+name,lambda n=name,d=data:parse(n,d))
    schema=json.loads((SCHEMAS/(name+'.schema.json')).read_text())
    generated=MODELS[name].model_json_schema();generated['$schema']='https://json-schema.org/draft/2020-12/schema';generated['title']='Contrato '+name+' v1.0'
    check('Esquema sincronizado '+name,lambda s=schema,g=generated: (_ for _ in ()).throw(AssertionError('Schema drift')) if s!=g else None)
case=Case.model_validate(read('case.json'));req=Request.model_validate_json(json.dumps(read('request.json')));plan=Plan.model_validate(read('response.json')['plan'])
check('Solicitud compatible con caso',lambda:validate_request_against_case(req,case))
check('Plan coherente con caso',lambda:validate_plan_against_case(plan,case))
for name in ['scenario_validation','scenario_test']:
    check(name,lambda n=name:parse('scenario',read(n+'.json')))
neg=[]
x=read('request.json');x['demand'][0]['flow_vph']='400';neg.append(('request',x,'número como cadena'))
x=read('request.json');x['demand'][0]['flow_vph']=True;neg.append(('request',x,'booleano como número'))
x=read('label.json');x['evidence_status']='evaluated';neg.append(('label',x,'etiqueta sin corridas'))
x=read('request.json');x['demand'][0]['flow_vph']=-1;neg.append(('request',x,'flujo negativo'))
x=read('request.json');x['demand'][0]['composition']['car']=0.8;neg.append(('request',x,'composición'))
x=read('request.json');x['demand'][0]['flow_vph']=0;neg.append(('request',x,'cero con composición'))
x=read('request.json');x['observation_end']=x['observation_start'];neg.append(('request',x,'intervalo vacío'))
x=read('request.json');x['unknown']=True;neg.append(('request',x,'campo desconocido'))
x=read('request.json');x['demand'].append(copy.deepcopy(x['demand'][0]));neg.append(('request',x,'movimiento duplicado'))
x=read('split.json');x['assignments'][1]['group_id']=x['assignments'][0]['group_id'];neg.append(('split',x,'fuga de grupos'))
x=read('protocol.json');x['seeds']['final'][0]=x['seeds']['search'][0];neg.append(('protocol',x,'semillas solapadas'))
x=read('protocol.json');x['status']='frozen';x['purpose']='main_experiment';neg.append(('protocol',x,'congelación sin criterios'))
x=read('case.json');x['slots'][0]['min_s']=80;neg.append(('case',x,'límites invertidos'))
x=read('case.json');x['green_groups'][0]['slot_ids']=['missing'];neg.append(('case',x,'referencia inexistente'))
x=read('case.json');x['cycle_s']['max']=20;x['cycle_s']['min']=10;neg.append(('case',x,'ciclo imposible'))
x=read('response.json');x['status']='rejected';neg.append(('response',x,'rechazo con plan'))
x=read('response.json');x['plan']=None;neg.append(('response',x,'aceptado sin plan'))
x=read('run_manifest.json');x['status']='succeeded';neg.append(('run_manifest',x,'éxito sin evidencia'))
x=read('model_manifest.json');x['status']='frozen';neg.append(('model_manifest',x,'modelo congelado vacío'))
for name,data,label in neg:check('Rechazo '+label,lambda n=name,d=data:reject(n,d))
# Las reglas cruzadas del caso y el motor SUMO requieren pruebas propias del producto.
def normalization():
    rs=rows(FIXTURES/'aforos.csv');expected=read('expected_normalization.json')
    for movement in ['N_S','E_W']:
        local=[r for r in rs if r['movement_id']==movement];total=sum(int(r['count']) for r in local)
        assert total*3600/900==expected[movement]['flow_vph']
        for r in local:assert abs(int(r['count'])/total-expected[movement][r['vehicle_class']])<1e-9
check('Normalización calculada de aforos',normalization)
omitted=[]
tr=tasks=qa=[]
if MATRICES.is_dir():
    tr=rows(MATRICES/'trazabilidad.csv');tasks=rows(MATRICES/'tareas.csv');qa=rows(MATRICES/'pruebas.csv')
    def trace():
        hu={r['HU'] for r in tr};q={r['id'] for r in qa};t={r['id'] for r in tasks}
        assert hu=={f'HU{x:02}' for x in range(1,15)}
        for r in tr:assert set(r['pruebas'].split(';'))<=q
        for r in tasks:
            assert set(r['historias'].split(';'))<=hu
            for dep in r['dependencias'].split(';'):
                if dep.startswith('DEV'):assert dep in t
        assert set().union(*(set(r['historias'].split(';')) for r in tasks))==hu
        assert len(t)==len(tasks) and len(q)==len(qa)
        # Ciclos de dependencias técnicas
        graph={r['id']:[d for d in r['dependencias'].split(';') if d.startswith('DEV')] for r in tasks}
        active=set();done=set()
        def visit(n):
            assert n not in active, 'dependency cycle'
            if n in done:return
            active.add(n)
            for d in graph[n]:visit(d)
            active.remove(n);done.add(n)
        for n in graph:visit(n)
    check('Cobertura y dependencias de trazabilidad',trace)
else:
    omitted.append('Cobertura y dependencias de trazabilidad (falta documentacion/matrices)')
    print('AVISO: no se encontró documentacion/matrices; se omite la comprobación de trazabilidad',file=sys.stderr)
print(json.dumps({'status':'passed','checks':len(checks),'positive_contracts':9,'negative_fixtures':len(neg),'stories':len(tr),'tasks':len(tasks),'planned_product_tests':len(qa),'scope':'Contratos Pydantic, esquemas sincronizados, fixtures y trazabilidad; sin SUMO ni modelo entrenado','omitted_checks':omitted,'check_names':checks},ensure_ascii=False,indent=2))
