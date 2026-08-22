import { CommandCenterApiError, getAccessContext } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const context = await getAccessContext();
    return Response.json(context, {
      headers: {
        "Cache-Control": "no-store, max-age=0",
        Pragma: "no-cache",
      },
    });
  } catch (error) {
    if (error instanceof CommandCenterApiError) {
      return Response.json(
        { detail: error.message, correlation_id: error.correlationId },
        {
          status: error.status,
          headers: { "Cache-Control": "no-store, max-age=0" },
        },
      );
    }
    return Response.json(
      { detail: "Não foi possível revalidar a identidade funcional." },
      { status: 502, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
