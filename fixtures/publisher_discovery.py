"""Publisher-authored guidance for synthetic examples, emitted into the pinned catalog.

The viewer does not read this module. Application facts remain in their publisher sources.
"""

def dataset_target(dataset):
    definition = dataset['definition']
    return {
        'kind': 'dataset', 'datasetId': dataset['id'],
        'definition': {
            'contractId': definition['contractId'], 'version': definition['version'],
            'object': definition['object'], 'sourceSha256': definition['source']['sha256'],
        },
    }


def build_discovery(slug, datasets, versions, representations, data_files, root):
    primary, secondary = datasets
    water = slug == 'watershed'
    subject = 'Water-quality examples' if water else 'Grant-award examples'
    evidence = [{'label': 'Definitions of these synthetic examples', 'record': primary['definition']['source']}]
    publisher = {'name': 'DDK viewer example publisher'}
    scope = {
        'geography': 'Synthetic station labels; no real geographic coverage is claimed.' if water else 'Geographic coverage is not supplied for this example.',
        'population': 'Authored example records only.',
        'inclusion': 'Listed example records, preserving missing, null, empty and repeated values.',
        'exclusions': 'Real-world records and source-population completeness are outside this example.',
    }
    records = []
    for dataset in datasets:
        is_primary = dataset is primary
        records.append({
            'target': dataset_target(dataset),
            'alternateNames': [{'name': (
                'Example water measurements' if water and is_primary else
                'Example monitoring stations' if water else
                'Example funding awards' if is_primary else 'Example funding programs'
            ), 'kind': 'alternate'}],
            'variantDescription': (
                'Instrument observations with their nested readings' if water and is_primary else
                'Station names keyed by station code' if water else
                'Award records with separately listed payments' if is_primary else
                'Program names keyed by program code'
            ),
            'topics': [{'id': f'urn:ddk-viewer:topic:{slug}', 'label': subject}],
            'coverage': scope,
            'dates': [{'kind': 'metadataUpdated', 'value': '2026-11-07'}],
            'updateFrequency': 'No scheduled updates; these are authored examples.',
            'publishers': [publisher],
            'citation': {
                'text': f"DDK viewer example publisher. {dataset['title']}. Synthetic demonstration data.",
                'originalIdentifier': dataset['id'],
            },
            'history': [{
                'kind': 'note', 'date': '2026-11-07',
                'description': 'Added human-readable field labels and example guidance. Native field names and stored record values are unchanged.',
                'evidence': evidence,
            }],
            'unknowns': [
                {'fact': 'Observation period', 'reason': 'The authored records contain no observation date.'},
                {'fact': 'Reuse terms', 'reason': 'No resource licence or reuse terms are supplied with this example.'},
                {'fact': 'Data support contact', 'reason': 'No data support route is supplied with this example.'},
            ],
        })
    records[0]['cautions'] = [{
        'summary': 'Nested readings are separate occurrences.' if water else 'Award amounts and payment amounts describe different things.',
        'details': (
            'Do not treat the number of readings as the number of observations. Repeated nested readings and flags remain separate; no depth unit or flag vocabulary is supplied.' if water else
            'Currency is not supplied for amount or payments[].amount. The example does not define payment timing or reconciliation to the award amount; do not add award and payment amounts together.'
        ), 'evidence': evidence,
    }]
    if water:
        records[0]['preparedViews'] = [{
            'id': 'urn:ddk-viewer:fixture:watershed:view:observations-by-station',
            'question': 'How many returned observations refer to each station code?',
            'kind': 'valueCounts', 'field': [{'field': 'station_code'}],
        }]
    records[1]['cautions'] = [{
        'summary': 'Choose the matching release before looking up names.',
        'details': 'The declared relationship uses codes within the same release. A declared link does not establish that every record has a match.',
        'evidence': evidence,
    }]
    by_alias = {dataset['alias']: dataset for dataset in datasets}
    by_version = {version['id']: version for version in versions}
    files = {item['identity']: item for item in data_files}
    for representation in representations:
        version = by_version[representation['version']]
        dataset = by_alias[version['dataset']]
        resource = {
            'purpose': 'Original JSON records for this exact synthetic data version.',
            'accessRequirements': 'This local viewer reads registered example records. No account or remote service is required for these examples.',
            'requestLimits': 'Read one bounded page at a time. The request limit is shown in View data; a page download contains only the returned records.',
        }
        if representation['id'] in files:
            resource['byteSize'] = (root / files[representation['id']]['path']).stat().st_size
        else:
            resource['purpose'] = 'Illustrative unavailable or unresolved resource; no example records are supplied for this reference.'
            resource['accessRequirements'] = 'No records can be read here without an available retained resource.'
        records.append({
            'target': {'kind': 'representation', 'datasetId': dataset['id'], 'versionId': version['id'], 'representationId': representation['id']},
            'resource': resource,
            'unknowns': [{'fact': 'Resource-specific reuse terms', 'reason': 'Not supplied.'}],
        })
    question = (
        'How can I connect example measurements to station names?' if water else
        'How can I find the program named by an example grant award?'
    )
    return {
        'schemaVersion': 1,
        'records': records,
        'guides': [{
            'id': f'urn:ddk-viewer:fixture:{slug}:guide:lookup',
            'title': 'Connect measurements to stations' if water else 'Connect awards to programs',
            'question': question,
            'summary': 'Start with the records, then use Related data to inspect the declared code relationship. Choose versions in the same release. This guide demonstrates the process with synthetic examples and makes no real-world coverage claim.',
            'author': publisher, 'reviewedOn': '2026-11-07', 'coverage': scope,
            'reviewTrigger': 'Review this guide when a linked definition, matching rule, data version, resource or access capability changes. Recheck the question with a participant before treating the guide as validated.',
            'links': [
                {'label': 'Start with measurements' if water else 'Start with awards', 'purpose': 'Open the record description, fields and available versions.', 'target': dataset_target(primary)},
                {'label': 'Understand station names' if water else 'Understand program names', 'purpose': 'Open the lookup dataset and its code definition; this does not perform a join.', 'target': dataset_target(secondary)},
            ],
            'evidence': evidence,
        }],
    }
