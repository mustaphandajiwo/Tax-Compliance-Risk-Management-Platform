/**
 * Typed client for the NGSIRS Compliance Risk Management Platform API.
 *
 * `schema.ts` is generated from ../openapi.json by `pnpm gen:api`; never edit it by hand.
 * `views.ts` holds hand-written shapes for endpoints whose OpenAPI response is an open object
 * (no response_model on the FastAPI route). Replace them with generated types once the API declares them.
 */
import createClient, { type Client, type Middleware } from "openapi-fetch";
import type { components, operations, paths } from "./schema";

export type { components, operations, paths };
export * from "./views";

export type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type DevUser = Schemas["DevUser"];
export type FindingSummary = Schemas["FindingSummary"];
export type FindingDetail = Schemas["FindingDetail"];
export type FindingPage = Schemas["FindingPage"];
export type CaseOut = Schemas["CaseOut"];
export type CaseDetail = Schemas["CaseDetail"];
export type ImportBatchOut = Schemas["ImportBatchOut"];
export type EvaluationRunOut = Schemas["EvaluationRunOut"];
export type ErrorBody = Schemas["ErrorBody"];
export type ReviewDecision = Schemas["ReviewRequest"]["decision"];
export type FindingOutcome = Schemas["CaseClose"]["finding_outcome"];
export type QuarantineResolutionCode = Schemas["QuarantineResolution"]["resolution"];
export type IdentityDecisionCode = Schemas["IdentityDecision"]["decision"];

export type ApiClient = Client<paths>;

export interface ClientOptions {
  baseUrl: string;
  /** Returns the current bearer token, or null when signed out. */
  getToken: () => string | null;
}

export function createApiClient({ baseUrl, getToken }: ClientOptions): ApiClient {
  const client = createClient<paths>({ baseUrl });
  const auth: Middleware = {
    onRequest({ request }) {
      const token = getToken();
      if (token && !request.headers.has("Authorization")) {
        request.headers.set("Authorization", `Bearer ${token}`);
      }
      return request;
    },
  };
  client.use(auth);
  return client;
}
