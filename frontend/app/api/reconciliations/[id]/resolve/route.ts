import { backendFailure, backendFetch, passthrough } from "@/lib/backend-proxy";

export const runtime = "nodejs";
const MAX_RESOLUTION_BYTES = 8 * 1024;

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_RESOLUTION_BYTES) {
    return Response.json(
      { error: { code: "RESOLUTION_TOO_LARGE", message: "Resolution note is too large." } },
      { status: 413 },
    );
  }
  try {
    const upstream = await backendFetch(
      `/api/reconciliations/${encodeURIComponent(id)}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      },
      request.headers.get("cookie"),
    );
    return passthrough(upstream);
  } catch (error) {
    return backendFailure(error);
  }
}
