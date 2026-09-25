export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function apiHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  const key = localStorage.getItem("clippy_api_key");
  if (key) headers.set("X-API-Key", key);
  if (init?.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  return headers;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: apiHeaders(init) });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Keep the HTTP status text when the response is not JSON.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function fileUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  const key = localStorage.getItem("clippy_api_key");
  if (!key) return url;
  return `${url}${url.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(key)}`;
}
