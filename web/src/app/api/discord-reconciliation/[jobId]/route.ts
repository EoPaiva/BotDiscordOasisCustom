import { CommandCenterApiError, commandCenterFetch } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  if (!/^\d+$/.test(jobId)) {
    return Response.json({ detail: "Job inválido." }, { status: 400 });
  }
  try {
    const result = await commandCenterFetch<unknown>(
      `/v1/discord/identity/reconciliations/${jobId}`,
    );
    return Response.json(result, { headers: { "Cache-Control": "no-store, max-age=0" } });
  } catch (error) {
    if (error instanceof CommandCenterApiError) {
      return Response.json(
        { detail: error.message, correlation_id: error.correlationId },
        { status: error.status, headers: { "Cache-Control": "no-store, max-age=0" } },
      );
    }
    return Response.json({ detail: "Falha ao consultar a reconciliação." }, { status: 502 });
  }
}
