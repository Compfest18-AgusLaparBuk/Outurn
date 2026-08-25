import { backendFailure, backendFetch, passthrough } from "@/lib/backend-proxy";

export const runtime = "nodejs";

export async function GET() {
  try {
    return passthrough(await backendFetch("/api/health/ready"));
  } catch (error) {
    return backendFailure(error);
  }
}
