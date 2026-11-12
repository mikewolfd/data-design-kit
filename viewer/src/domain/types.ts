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
export type CatalogImport = {
  id: string;
  audience: 'local' | 'public';
  lockSha256: string;
};
export type CatalogConceptField = {
  catalog?: string;
  dataset: string;
  path: FieldPath;
};
export type CatalogConcept = {
  concept: string;
  definition: string;
  conceptKind?: 'identifier' | 'attribute';
  iriTemplate?: string;
  fields: CatalogConceptField[];
  description?: string;
  exactMatch?: string[];
  closeMatch?: string[];
  canonicalUrls?: string[];
};
export type CatalogPurposeDescription = {
  purpose?: string;
  usage?: string;
  limitations?: string;
};
export type CatalogAgentContext = {
  instructions?: string;
  verifiedStatements?: { question: string; [key: string]: unknown }[];
  constraints?: { constraint: string; [key: string]: unknown }[];
};
export type CatalogDatasetContract = {
  description?: CatalogPurposeDescription;
  context?: CatalogAgentContext;
  slaProperties?: { property: string; value: unknown; [key: string]: unknown }[];
  tags?: string[];
  canonicalUrls?: string[];
};
export type CatalogDatasetOrigin =
  | 'publisher'
  | 'third_party'
  | 'derived'
  | 'aggregation'
  | 'model';
export type CatalogDataset = {
  alias: string;
  id: string;
  title?: string;
  rowMeaning?: string;
  role?: string;
  origin?: CatalogDatasetOrigin;
  model?: { id: string; version: string };
  methodColumn?: string;
  status?: string;
  description?: string;
  tags?: string[];
  context?: CatalogAgentContext;
  contract?: CatalogDatasetContract;
  definition: {
    contractId: string;
    version: string;
    object: string;
    source: RecordRef & { sha256: string };
  };
};
export type CatalogCoverageKind =
  | 'true_range'
  | 'window'
  | 'sampled'
  | 'derived'
  | 'not_a_range'
  | 'empty';
export type CatalogCoverageStage =
  | 'expected'
  | 'discovered'
  | 'fetched'
  | 'extracted'
  | 'published';
export type CatalogCoverageBounds = {
  field: string;
  min: string | number | ExactNumber;
  max: string | number | ExactNumber;
};
export type CatalogVersionDates = {
  publishedAt?: string;
  retrievedAt?: string;
  sourceUpdatedAt?: string;
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
  dates?: CatalogVersionDates;
  coverage?: {
    scope: string;
    unit: string;
    status: string;
    kind?: CatalogCoverageKind;
    stage?: CatalogCoverageStage;
    observed?: ExactValue;
    expected?: ExactValue;
    bounds?: CatalogCoverageBounds;
    record: RecordRef;
  }[];
};
export type CatalogRepresentationMember = {
  path: string;
  sha256: string;
  byteSize?: number;
  rowCount?: number;
  rowRange?: [number, number];
};
export type CatalogRepresentation = {
  id: string;
  version: string;
  kind: 'file' | 'table' | 'service';
  availability: 'available' | 'unavailable' | 'unknown';
  location?: string;
  mediaType?: string;
  byteSize?: number;
  rowCount?: number;
  members?: CatalogRepresentationMember[];
  record: RecordRef;
};
export type UnresolvedRelationshipReason =
  | 'scope_boundary'
  | 'design_optional'
  | 'polymorphic_key'
  | 'publisher_defect'
  | 'unmeasured';
export type CatalogRelationshipJoinMetrics = {
  matchedRows?: number;
  totalSourceRows?: number;
  floorPct?: number | ExactNumber;
  basis: string;
  record: RecordRef;
};
export type CatalogRelationship = {
  id: string;
  source: { dataset: string; paths: FieldPath[] };
  target:
    | { catalog?: string; dataset: string; paths: FieldPath[]; external?: never }
      | {
          external: string;
          externalDataset?: string;
          externalKeyFields?: string[];
          limitations?: string;
          catalog?: never;
          dataset?: never;
          paths?: never;
        };
  match: string;
  rule?: { id: string; version: string };
  cardinality: string;
  scope: string;
  resolution: string;
  unresolvedReason?: UnresolvedRelationshipReason;
  joinMetrics?: CatalogRelationshipJoinMetrics;
  meaning: string;
  nulls: string;
  scopeDescription?: string;
};
export type CatalogRecipeInput = string | { catalog: string; dataset: string };
export type CatalogRecipe = {
  id: string;
  title?: string;
  notes?: string[];
  sql: string;
  dialect: string;
  inputs: Record<string, CatalogRecipeInput>;
  relationships: string[];
  contextualRelationships?: string[];
  parameters: Record<string, unknown>;
  parameterOrder?: string[];
  resultGrain?: string;
  resultDataset?: string;
};
export type CatalogProductionStep = {
  id: string;
  kind: 'sql' | 'view' | 'export' | 'report';
  sqlSha256?: string;
};
export type CatalogProduction = {
  alias: string;
  kind?: 'component' | 'design' | 'job';
  identity: { id: string; version: string };
  definition: RecordRef;
  inputs: string[];
  outputs: string[];
  steps?: CatalogProductionStep[];
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
export type CatalogAudience = 'public' | 'local';
export type Catalog = {
  specVersion: '0.1';
  kind: 'catalog';
  id: string;
  version: string;
  audience: CatalogAudience;
  project: { id: string; version: string };
  imports?: Record<string, CatalogImport>;
  concepts?: CatalogConcept[];
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
  productions: CatalogProduction[];
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
  catalogId?: string;
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
export type QueryEngineProvenance = {
  id: string;
  version: string;
  binarySha256?: string;
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
    engine?: QueryEngineProvenance;
    consumedBindings?: Record<string, ExactBinding>;
    elapsedMs?: number;
  };
};
export type EvidenceResult = {
  record: RecordRef;
  document: unknown;
  scope: string;
};
