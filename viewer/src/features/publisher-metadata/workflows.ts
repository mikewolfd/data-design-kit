import type { CatalogSnapshot } from '../../domain/types';
import type { PublisherRecord, PublisherWorkflow } from './schema';

/** Admit tasks only when every input and action is bound to the disclosed catalog. */
export function validWorkflows(
  workflows: PublisherWorkflow[],
  records: PublisherRecord[],
  snapshot: CatalogSnapshot,
) {
  const ids = new Set<string>();
  for (const workflow of workflows) {
    if (ids.has(workflow.id)) return false;
    ids.add(workflow.id);
    const recipe = snapshot.catalog.recipes.find(({ id }) => id === workflow.recipeId);
    if (!recipe || Object.keys(workflow.bindings).length !== Object.keys(recipe.inputs).length)
      return false;
    // This small task form supports text keys. Other recipe parameters keep their full query UI.
    const parameters = recipe.parameters.properties as
      Record<string, { type?: string }> | undefined;
    if (!parameters || Object.values(parameters).some((parameter) => parameter.type !== 'string'))
      return false;
    if (Object.keys(workflow.defaults ?? {}).some((name) => !Object.hasOwn(parameters, name)))
      return false;
    for (const [name, input] of Object.entries(recipe.inputs)) {
      const binding = workflow.bindings[name];
      if (typeof input !== 'string' || !binding) return false;
      const dataset = snapshot.catalog.datasets.find(({ id }) => id === binding.datasetId);
      const version = snapshot.catalog.versions.find(({ id }) => id === binding.versionId);
      const resource = snapshot.catalog.representations.find(
        ({ id }) => id === binding.representationId,
      );
      if (
        !dataset ||
        ![dataset.id, dataset.alias].includes(input) ||
        !version ||
        ![dataset.id, dataset.alias].includes(version.dataset) ||
        resource?.version !== version.id
      )
        return false;
    }
  }
  for (const record of records) {
    if (!record.rowActions && !record.readableFields) continue;
    if (record.target.kind !== 'version') return false;
    const target = record.target;
    const dataset = snapshot.catalog.datasets.find(({ id }) => id === target.datasetId);
    const fields = dataset ? (snapshot.definitions[dataset.alias]?.properties ?? []) : [];
    const textField = (name: string) => {
      const matches = fields.filter((field) => field.name === name);
      return (
        matches.length === 1 &&
        matches[0].logicalType === 'string' &&
        !matches[0].items &&
        !matches[0].properties
      );
    };
    if (record.readableFields?.some((name) => !textField(name))) return false;
    const actionIds = new Set<string>();
    for (const action of record.rowActions ?? []) {
      if (actionIds.has(action.id)) return false;
      actionIds.add(action.id);
      if (action.kind === 'original') {
        if (!Object.values(action.fields).every(textField)) return false;
      } else {
        const workflow = workflows.find(({ id }) => id === action.workflowId);
        const recipe = snapshot.catalog.recipes.find(({ id }) => id === workflow?.recipeId);
        if (!recipe) return false;
        const parameters = recipe.parameters.properties as Record<string, unknown>;
        const required = recipe.parameters.required as string[] | undefined;
        if (
          !Object.values(action.parameters).every(textField) ||
          Object.keys(action.parameters).some((name) => !Object.hasOwn(parameters, name)) ||
          required?.some((name) => !Object.hasOwn(action.parameters, name))
        )
          return false;
      }
    }
  }
  return true;
}
