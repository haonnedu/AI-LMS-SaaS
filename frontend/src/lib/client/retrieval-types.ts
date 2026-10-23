import type { components } from "@/lib/api/generated";

// Aliases over the generated OpenAPI types (regenerate with `npm run api:generate`).
type Schemas = components["schemas"];
export type RetrievalResponse = Schemas["RetrievalResultDTO"];
export type RetrievalItem = RetrievalResponse["items"][number];
export type CitationDetail = Schemas["CitationPreviewDTO"];
export type EmbeddingRun = Schemas["EmbeddingRunDTO"];
export type EmbeddingRunList = Schemas["EmbeddingRunListDTO"];
export type EmbedResponse = { job: Schemas["JobDTO"] };
