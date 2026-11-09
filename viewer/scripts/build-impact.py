"""Generate a small, genuine DDK impact report; never execute native data work."""
from pathlib import Path
from copy import deepcopy
import hashlib, json
from ddk.catalog_impact import compare_catalogs

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'fixtures/impact'
def encoded(value): return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
def sha(value): return hashlib.sha256(value).hexdigest()
candidate_bytes=(ROOT/'fixtures/watershed/catalog.ddk.json').read_bytes()
candidate=json.loads(candidate_bytes)
base=deepcopy(candidate)
base['version']='0.9.0';base['project']['version']='0.9.0'
base['datasets'][0]['title']='Earlier watershed observations'
base['datasets'][0]['definition']['version']='0.9.0'
# This deliberately authored earlier example predates the new publisher guidance.
# Retaining current definition-bound guidance would leave dangling prior-version targets.
base['extensions']['urn:ddk:catalog:assembly']['projectExtensions']=[]
base['sourceInventory']=[row for row in base['sourceInventory'] if not row['uri'].endswith(':publisher-discovery')]
fields=base['extensions']['urn:ddk:catalog:assembly']['datasetDefinitions']
fields['observations']['description']='Earlier description of the same synthetic observations'
for field in fields['observations']['properties']:
 if field['name']=='note': field['description']='Earlier note description'
baseline_definition_bytes=encoded(fields)
(DEST/'base.definitions.json').write_bytes(baseline_definition_bytes)
old_definition_sha=base['datasets'][0]['definition']['source']['sha256']
for dataset in base['datasets']:
 dataset['definition']['source']['sha256']=sha(baseline_definition_bytes)
for source in base['sourceInventory']:
 if source['sha256']==old_definition_sha: source['sha256']=sha(baseline_definition_bytes)
for product in base['products']:
 for port in product['ports']:
  if port['dataset']=='observations': port['version']='0.9.0'
base_bytes=encoded(base)
(DEST/'base.catalog.ddk.json').write_bytes(base_bytes)
report=compare_catalogs(base,candidate)
report_bytes=encoded(report)
(DEST/'impact.report.json').write_bytes(report_bytes)
receipt={'format':'ddk-viewer-impact-binding/1','mode':'fixture','scope':'Definition metadata changes between an explicitly authored prior snapshot and the current watershed fixture. No native data execution.', 'owner':'ddk.catalog_impact.compare_catalogs','ddkSource':'fb70ab825243235b4ecf77c5ebb8c636d0d06e2d','ddkWheelSha256':'7c4c6bb481316c95e13c5518089f90c71664ca7387c09eb1ae0f94219fe267b8','baseCatalogSha256':sha(base_bytes),'candidateCatalogSha256':sha(candidate_bytes),'reportSha256':sha(report_bytes)}
(DEST/'binding.json').write_bytes(encoded(receipt))
(ROOT/'src/server/impact-pin.ts').write_text('export const impactPins = '+json.dumps([{'catalogId':'watershed','directory':'fixtures/impact','bindingSha256':sha(encoded(receipt))}],indent=2)+' as const;\n')
print(json.dumps({'decision':report.get('decision'),'changed':len(report.get('impact',{}).get('changed',[])),'binding':receipt},indent=2))
