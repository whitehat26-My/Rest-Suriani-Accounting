/** Thin typed client for the FastAPI backend.
 *
 * In development, `next.config.mjs` rewrites `/api/*` to the backend, so the
 * browser only ever talks to its own origin and there is no CORS preflight.
 */
import type {
  AccountBalance,
  AccountantDashboard,
  DailySummary,
  FinancialEvaluation,
  InventoryItem,
  PreviewLeg,
  SpendingCategory,
  StockCountResult,
  EmployeeRecord,
  PayrollOverview,
  PayrollRun,
  PayrollRunSummary,
  PayslipEdit,
  Transaction,
  TrendPoint,
  VoiceParseResult,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    // A network failure here almost always means the backend is not running,
    // so say that rather than surfacing "Failed to fetch".
    throw new ApiError(
      "Cannot reach the server. Check that the backend is running on port 8000.",
      0,
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      /* Response had no JSON body; keep the generic message. */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Grandma Mode
// ---------------------------------------------------------------------------
export interface QuickEntryPayload {
  kind: "in" | "out";
  amount: string;
  method?: string;
  category?: string | null;
  note?: string;
  counterparty?: string;
  raw_input?: string;
  source?: string;
  attachment_ids?: number[];
  inventory_item_id?: number | null;
  quantity?: string | null;
}

export const api = {
  dailySummary: (day?: string) =>
    request<DailySummary>(`/api/insights/daily${day ? `?day=${day}` : ""}`),

  weekTrend: (days = 7) => request<TrendPoint[]>(`/api/insights/week?days=${days}`),

  spendingCategories: () =>
    request<SpendingCategory[]>("/api/accounts/spending-categories"),

  quickEntry: (payload: QuickEntryPayload) =>
    post<Transaction>("/api/transactions/quick", payload),

  parseSpeech: (text: string) =>
    post<VoiceParseResult>("/api/transactions/parse", { text }),

  reverse: (id: number, reason: string) =>
    post<Transaction>(
      `/api/transactions/${id}/reverse?reason=${encodeURIComponent(reason)}`,
    ),

  uploadReceipt: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: number; url: string; filename: string }>("/api/uploads", {
      method: "POST",
      body: form,
    });
  },

  // -------------------------------------------------------------------------
  // Inventory
  // -------------------------------------------------------------------------
  inventory: (lowOnly = false) =>
    request<InventoryItem[]>(`/api/inventory${lowOnly ? "?low_only=true" : ""}`),

  countStock: (
    counts: { item_id: number; counted_quantity: string; treat_shortfall_as?: string }[],
    note = "",
  ) => post<StockCountResult[]>("/api/inventory/count", { counts, note }),

  // -------------------------------------------------------------------------
  // Accountant Mode
  // -------------------------------------------------------------------------
  dashboard: (period = "month") =>
    request<AccountantDashboard>(`/api/insights/dashboard?period=${period}`),

  evaluation: (period = "month") =>
    request<FinancialEvaluation>(`/api/insights/evaluation?period=${period}`),

  accounts: () => request<AccountBalance[]>("/api/accounts"),

  recentTransactions: (limit = 12) =>
    request<Transaction[]>(`/api/transactions/recent?limit=${limit}`),

  previewEntries: (payload: Record<string, unknown>) =>
    post<PreviewLeg[]>("/api/transactions/preview", payload),

  // -------------------------------------------------------------------------
  // Payroll
  // -------------------------------------------------------------------------
  payrollOverview: (period = "month") =>
    request<PayrollOverview>(`/api/payroll/overview?period=${period}`),

  payrollRuns: () => request<PayrollRunSummary[]>("/api/payroll/runs"),

  payrollRun: (id: number) => request<PayrollRun>(`/api/payroll/runs/${id}`),

  createPayrollRun: (payload: {
    period_start: string;
    period_end: string;
    pay_date?: string;
    default_days_worked?: string;
    notes?: string;
  }) => post<PayrollRun>("/api/payroll/runs", payload),

  updatePayslip: (payslipId: number, payload: PayslipEdit) =>
    request<PayrollRun>(`/api/payroll/payslips/${payslipId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  approvePayrollRun: (id: number) => post<PayrollRun>(`/api/payroll/runs/${id}/approve`),

  payPayrollRun: (id: number, method = "BANK") =>
    post<PayrollRun>(`/api/payroll/runs/${id}/pay?method=${method}`),

  remitStatutory: (body: string, amount: string) =>
    post<Transaction>("/api/payroll/remit", { body, amount }),

  employees: (includeInactive = false) =>
    request<EmployeeRecord[]>(
      `/api/payroll/employees${includeInactive ? "?include_inactive=true" : ""}`,
    ),

  createEmployee: (payload: Record<string, unknown>) =>
    post<EmployeeRecord>("/api/payroll/employees", payload),

  updateEmployee: (id: number, payload: Record<string, unknown>) =>
    request<EmployeeRecord>(`/api/payroll/employees/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};
