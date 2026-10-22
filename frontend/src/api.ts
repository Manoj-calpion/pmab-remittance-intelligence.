const TOKEN_KEY = "pmab_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    setToken(null);
    if (!path.endsWith("/auth/login")) window.location.assign("/login");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const message = payload?.error?.message || "The request could not be completed.";
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type BatchFileResult = {
  filename: string;
  status: string;
  lifecycle: string;
  file_id: string | null;
  message: string;
  sha256: string | null;
  reconciliation_status: string | null;
  claim_count?: number;
};

export type BatchResult = {
  job_id: string;
  stats: Record<string, number>;
  results: BatchFileResult[];
};

export function uploadBatch(files: File[], onProgress?: (ratio: number) => void): Promise<BatchResult> {
  return new Promise((resolve, reject) => {
    const body = new FormData();
    for (const file of files) body.append("files", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/remittances/batch");
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed before the server responded."));
    xhr.onload = () => {
      const payload = JSON.parse(xhr.responseText || "{}");
      if (xhr.status === 401) {
        setToken(null);
        window.location.assign("/login");
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(xhr.status, payload?.error?.message || "Upload failed."));
        return;
      }
      resolve(payload as BatchResult);
    };
    xhr.send(body);
  });
}

export async function downloadReport(report: string, format: "csv" | "xlsx" | "pdf"): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`/api/v1/reports/${report}?format=${format}`, { headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payload?.error?.message || "Export failed.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report}.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}

export async function downloadErrorReport(fileId: string, filename: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`/api/v1/remittances/${fileId}/error-report`, { headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payload?.error?.message || "Error report failed.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filename}-errors.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
