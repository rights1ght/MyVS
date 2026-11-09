export class ApiError extends Error {
  code: string;
  status: number;
  actions: { id: string; label: string }[];

  constructor(message: string, code = "API_ERROR", status = 0, actions: { id: string; label: string }[] = []) {
    super(message);
    this.code = code;
    this.status = status;
    this.actions = actions;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let code = "HTTP_ERROR";
    let actions: { id: string; label: string }[] = [];
    try {
      const body = await response.json();
      if (body?.error) {
        message = body.error.message ?? message;
        code = body.error.code ?? code;
        actions = body.error.actions ?? [];
      } else if (body?.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // keep default message
    }
    throw new ApiError(message, code, response.status, actions);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function formatMb(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value >= 1024) return `${(value / 1024).toFixed(digits)} GB`;
  return `${Math.round(value)} MB`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}
