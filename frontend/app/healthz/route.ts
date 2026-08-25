import { backendFailure, backendFetch, passthrough } from "@/lib/backend-proxy";

export const runtime = "nodejs";

export async function GET() {
  try {
    return passthrough(await backendFetch("/healthz"));
  } catch (error) {
    return backendFailure(error);
  }
}
