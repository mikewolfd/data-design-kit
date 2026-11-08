/** Direct DDK facts, plus the viewer's bounded read requests and exact-value transport. */
export type ExactNumber = { $number: string };
export type EscapedObject = { $object: [string, ExactValue][] };
export type ExactValue =
  | null
  | boolean
  | string
  | number
  | ExactNumber
  | EscapedObject
  | ExactValue[]
  | { [key: string]: ExactValue };
export type ExactObject = { [key: string]: ExactValue };
export type FieldStep = { field: string } | { each: true };
export type FieldPath = FieldStep[];
export type RecordRef = { uri: string; sha256?: string };
export type ExactReference = { scheme: string; authority: string; value: ExactValue };
export type CatalogField = {
  name: string;
  logicalType?: string;
  physicalType?: string;
  description?: string;
  businessName?: string;
  required?: boolean;
  nullable?: boolean;
  properties?: CatalogField[];
  items?: CatalogField;
  [key: string]: unknown;
};
export type CatalogDataset = {
  alias: string;
  id: string;
  title?: string;
  rowMeaning?: string;
  role?: string;
  definition: {
    contractId: string;
    version: string;
    object: string;
    source: RecordRef & { sha256: string };
  };
};
export type CatalogVersion = {
  id: string;
  dataset: string;
  reference?: ExactReference;
  referenceDisclosure?: 'withheld';
  retention: 'present' | 'missing' | 'unknown';
  scope: string;
  record: RecordRef;
  sources: string[];
  coverage?: {
    scope: string;
    unit: string;
    status: string;
    observed?: ExactValue;
    expected?: ExactValue;
    record: RecordRef;
  }[];
};
export type CatalogRepresentation = {
  id: string;
  version: string;
  kind: 'file' | 'table' | 'service';
  availability: 'available' | 'unavailable' | 'unknown';
  location?: string;
  mediaType?: string;
  record: RecordRef;
};
export type CatalogRelationship = {
  id: string;
  source: { dataset: string; paths: FieldPath[] };
  target:
    | { dataset: string; paths: FieldPath[]; external?: never }
    | { external: string; dataset?: never; paths?: never };
  match: string;
  rule?: { id: string; version: string };
  cardinality: string;
  scope: string;
  resolution: string;
  meaning: string;
  nulls: string;
  scopeDescription?: string;
};
export type CatalogRecipe = {
  id: string;
  title?: string;
  notes?: string[];
  sql: string;
  dialect: string;
  inputs: Record<string, string>;
  relationships: string[];
  contextualRelationships?: string[];
  parameters: Record<string, unknown>;
  parameterOrder?: string[];
  resultGrain?: string;
  resultDataset?: string;
};
export type CatalogCheck = {
  subject: string;
  rule: { id: string; version: string };
  evaluator: { id: string; version: string };
  scope: string;
  status: 'passed' | 'failed' | 'unknown' | 'not_run';
  record?: RecordRef;
  reason?: string;
};
export type Catalog = {
  specVersion: '0.1';
  kind: 'catalog';
  id: string;
  version: string;
  audience: 'public' | 'local';
  project: { id: string; version: string };
  sourceInventory: { uri: string; sha256: string; role: string }[];
  adapters: { id: string; version: string; [key: string]: unknown }[];
  products: {
    id: string;
    alias: string;
    version: string;
    definition: RecordRef;
    ports: { dataset: string; direction: string; [key: string]: unknown }[];
  }[];
  datasets: CatalogDataset[];
  identities: {
    dataset: string;
    kind: string;
    scope: string;
    meaning: string;
    fields: { path: FieldPath; virtual: boolean; physicalType: string }[];
  }[];
  relationships: CatalogRelationship[];
  recipes: CatalogRecipe[];
  versions: CatalogVersion[];
  sources: {
    id: string;
    reference: ExactReference;
    content?: ExactReference;
    outcome: string;
    scope: string;
    record: RecordRef;
  }[];
  representations: CatalogRepresentation[];
  releases: {
    id: string;
    reference: ExactReference;
    members: string[];
    membership: 'complete' | 'partial' | 'unknown';
    record: RecordRef;
  }[];
  selections: {
    authority: string;
    purpose: string;
    release: string;
    observedAt: string;
    record: RecordRef;
  }[];
  runs: {
    id: string;
    reference: ExactReference;
    inputs: string[];
    outputs: string[];
    outcome: string;
    observedAt: string;
    record: RecordRef;
    inputCoverage: { status: string; scope: string };
    [key: string]: unknown;
  }[];
  checks: CatalogCheck[];
  files: { path: string; role: string; sha256: string }[];
  productions: {
    alias: string;
    identity: { id: string; version: string };
    definition: RecordRef;
    inputs: string[];
    outputs: string[];
  }[];
  currentSelection?: { authority: string; purpose: string };
  extensions?: Record<string, unknown>;
  disclosurePolicy?: RecordRef;
};
export type ReportCheck = {
  id: string;
  requirement: string;
  group: string;
  subject: string;
  status: 'passed' | 'failed' | 'unknown' | 'not_run';
  required: boolean;
  applicable: boolean;
  evidence: 'declared' | 'inferred' | 'executed';
  reason?: string;
  diagnostics: unknown[];
  evidenceRecords?: unknown[];
};
export type CatalogReport = {
  specVersion: '0.1';
  kind: 'report';
  id: string;
  version: string;
  decision: 'passed' | 'failed' | 'incomplete' | 'error';
  checks: ReportCheck[];
  scope: Record<string, unknown>;
  coverage: Record<string, unknown>;
  lock: { verified: boolean; path?: string };
  tools: Record<string, unknown>;
  operationalErrors: unknown[];
  limits: Record<string, unknown>;
  [key: string]: unknown;
};
export type CatalogLock = {
  specVersion: '0.1';
  kind: 'lock';
  id: string;
  version: string;
  project: string;
  files: { path: string; sha256: string; role: string; identity?: string }[];
  tools: Record<string, unknown>;
  standards: Record<string, string>;
  extensions?: Record<string, unknown>;
  catalogOptions?: { audience: 'public' | 'local'; exports: string[]; [key: string]: unknown };
};
export type CatalogSummary = {
  id: string;
  title: string;
  description: string;
  mode: 'fixture' | 'application';
  exampleData?: 'synthetic' | 'authored';
  audience: 'public' | 'local';
  admission?: 'not_loaded' | 'admitted';
};
export type CatalogListResult = {
  catalogs: CatalogSummary[];
  unavailable: { id: string; code: string; reason: string }[];
};
export type CatalogSnapshot = CatalogSummary & {
  catalog: Catalog;
  report: CatalogReport;
  lock: CatalogLock;
  identity: { catalogSha256: string; reportSha256: string; lockSha256: string };
  capabilities: {
    read: boolean;
    query: boolean;
    evidence?: boolean;
    readDatasetIds?: readonly string[];
    queryRecipeIds?: readonly string[];
    description?: string;
    reason?: string;
  };
  definitions: Record<string, CatalogField>;
};
export type ExactBinding = {
  datasetId: string;
  versionId: string;
  representationId: string;
  releaseId?: string;
};
export type ReadRequest = ExactBinding & {
  catalogId: string;
  catalogSha256: string;
  cursor?: string;
  limit?: number;
  filter?: { path: FieldPath; equals: ExactValue };
};
export type QueryRequest = {
  catalogId: string;
  catalogSha256: string;
  recipeId: string;
  bindings: Record<string, ExactBinding>;
  parameters: Record<string, ExactValue>;
  limit?: number;
  releaseId?: string;
};
export type ReadResult = {
  status: 'ok' | 'refused' | 'unknown';
  reason?: string;
  binding: ExactBinding;
  rows: ExactObject[];
  columns: string[];
  returned: number;
  total?: number;
  hasMore?: boolean;
  continuation?: 'more' | 'complete' | 'unknown';
  nextCursor?: string;
  rowPositions?: number[];
  rowOrder?: 'source-row' | 'query-result';
  attempt?: RecordRef;
  transport: 'ddk-exact-json-v1';
  readEvidence?: {
    kind: 'fixture' | 'owner';
    consumed: ExactBinding;
    record?: RecordRef;
    details?: ExactObject;
  };
  release?: { id: string; membership: string; selected?: boolean };
};
export type QueryResult = Omit<ReadResult, 'binding'> & {
  bindings: Record<string, ExactBinding>;
  execution?: {
    kind: 'fixture' | 'owner';
    recipeId: string;
    sqlSha256: string;
    inputs: string[];
    contextualRelationships: string[];
    record?: RecordRef;
  };
};
export type EvidenceResult = {
  record: RecordRef;
  document: unknown;
  scope: string;
};
