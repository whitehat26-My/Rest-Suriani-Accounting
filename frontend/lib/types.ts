/** TypeScript mirrors of the FastAPI response models.
 *
 * Money arrives as a decimal string rather than a float, because binary floats
 * cannot represent cents exactly. Convert with `toNumber` only for charting and
 * arithmetic that is about to be rounded anyway; never for storage.
 */

export type Direction = "in" | "out" | "neutral";
export type PaymentMethod = "CASH" | "BANK" | "CARD" | "EWALLET" | "CREDIT";
export type Rating = "good" | "watch" | "bad" | "neutral";
export type Severity = "critical" | "warning" | "info" | "positive";
export type StockStatus = "ok" | "low" | "critical";

export interface LedgerEntry {
  id: number;
  account_id: number;
  account_code: string;
  account_name: string;
  side: "DEBIT" | "CREDIT";
  amount: string;
  memo: string;
}

export interface Attachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
}

export interface Transaction {
  id: number;
  reference: string;
  event_type: string;
  txn_date: string;
  amount: string;
  description: string;
  counterparty: string;
  payment_method: PaymentMethod | null;
  source: string;
  raw_input: string;
  notes: string;
  is_reversed: boolean;
  created_at: string;
  entries: LedgerEntry[];
  attachments: Attachment[];
  friendly_summary: string;
  friendly_label: string;
  direction: Direction;
}

export interface DailySummary {
  day: string;
  money_in: string;
  money_out: string;
  net: string;
  cash_on_hand: string;
  transaction_count: number;
  verdict: "good" | "watch" | "bad";
  verdict_message: string;
  low_stock_count: number;
  recent: Transaction[];
}

export interface TrendPoint {
  day: string;
  money_in: string;
  money_out: string;
  net: string;
  cumulative_cash: string;
}

export interface SpendingCategory {
  slug: string;
  label: string;
  emoji: string;
  account_code: string;
}

export interface VoiceParseResult {
  understood: boolean;
  confidence: number;
  kind: Direction | null;
  amount: string | null;
  category: string | null;
  category_label: string | null;
  method: PaymentMethod;
  inventory_item_id: number | null;
  inventory_item_name: string | null;
  inventory_item_unit: string | null;
  quantity: string | null;
  note: string;
  confirmation: string;
  original_text: string;
}

export interface InventoryItem {
  id: number;
  name: string;
  local_name: string;
  category: string;
  unit: string;
  quantity_on_hand: string;
  unit_cost: string;
  reorder_level: string;
  par_level: string;
  emoji: string;
  is_active: boolean;
  stock_value: string;
  stock_ratio: number;
  status: StockStatus;
  days_of_cover: number | null;
}

export interface StockCountResult {
  item_id: number;
  item_name: string;
  expected_quantity: string;
  counted_quantity: string;
  variance: string;
  variance_value: string;
  treated_as: string;
  transaction_reference: string | null;
}

export interface StatementLine {
  label: string;
  amount: string;
  account_code: string | null;
  level: number;
  is_total: boolean;
  is_subtotal: boolean;
  note: string;
}

export interface StatementSection {
  title: string;
  lines: StatementLine[];
  total: string;
}

export interface IncomeStatement {
  business_name: string;
  currency: string;
  period_start: string;
  period_end: string;
  sections: StatementSection[];
  revenue: string;
  cost_of_sales: string;
  gross_profit: string;
  operating_expenses: string;
  operating_profit: string;
  finance_costs: string;
  net_profit: string;
  gross_margin_pct: number;
  net_margin_pct: number;
}

export interface BalanceSheet {
  business_name: string;
  currency: string;
  as_of: string;
  sections: StatementSection[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  balances: boolean;
  difference: string;
}

export interface CashFlow {
  business_name: string;
  currency: string;
  period_start: string;
  period_end: string;
  sections: StatementSection[];
  net_operating: string;
  net_investing: string;
  net_financing: string;
  net_change: string;
  opening_cash: string;
  closing_cash: string;
  reconciles: boolean;
}

export interface TrialBalanceRow {
  code: string;
  name: string;
  type: string;
  debit: string;
  credit: string;
}

export interface TrialBalance {
  as_of: string;
  rows: TrialBalanceRow[];
  total_debit: string;
  total_credit: string;
  balanced: boolean;
}

export interface Metric {
  key: string;
  label: string;
  value: number | null;
  display: string;
  unit: string;
  rating: Rating;
  benchmark: string;
  explanation: string;
}

export interface Suggestion {
  severity: Severity;
  title: string;
  message: string;
  action: string;
  metric_key: string;
}

export interface FinancialEvaluation {
  period_start: string;
  period_end: string;
  health_score: number;
  health_grade: string;
  headline: string;
  working_capital: string;
  current_ratio: number | null;
  quick_ratio: number | null;
  cash_runway_days: number | null;
  average_daily_burn: string;
  metrics: Metric[];
  suggestions: Suggestion[];
  trend: TrendPoint[];
}

export interface ExpenseBreakdownItem {
  account_code: string;
  label: string;
  friendly_label: string;
  amount: string;
  percentage: number;
}

export interface AccountantDashboard {
  period_start: string;
  period_end: string;
  income_statement: IncomeStatement;
  balance_sheet: BalanceSheet;
  cash_flow: CashFlow;
  evaluation: FinancialEvaluation;
  expense_breakdown: ExpenseBreakdownItem[];
  revenue_by_day: TrendPoint[];
  inventory_value: string;
  low_stock: InventoryItem[];
}

export interface AccountBalance {
  id: number;
  code: string;
  name: string;
  friendly_name: string;
  type: string;
  normal_balance: string;
  cash_flow_section: string;
  statement_group: string;
  is_contra: boolean;
  is_active: boolean;
  debits: string;
  credits: string;
  balance: string;
}

export interface PreviewLeg {
  account_code: string;
  side: "DEBIT" | "CREDIT";
  amount: string;
  memo: string;
}


// ---------------------------------------------------------------------------
// Payroll
// ---------------------------------------------------------------------------
export type EmploymentType = "PERMANENT" | "PART_TIME" | "CASUAL";
export type PayBasis = "MONTHLY" | "DAILY" | "HOURLY";
export type PayrollStatus = "DRAFT" | "APPROVED" | "PAID";
export type StatutoryBody = "EPF" | "SOCSO" | "EIS" | "TAX";

export interface EmployeeRecord {
  id: number;
  name: string;
  nickname: string;
  position: string;
  employment_type: EmploymentType;
  pay_basis: PayBasis;
  base_rate: string;
  fixed_allowance: string;
  overtime_rate: string;
  contributes_statutory: boolean;
  is_local: boolean;
  date_of_birth: string | null;
  ic_number: string;
  epf_number: string;
  socso_number: string;
  tax_number: string;
  bank_name: string;
  bank_account: string;
  joined_on: string | null;
  left_on: string | null;
  is_active: boolean;
}

export interface PayslipRow {
  id: number;
  employee_id: number;
  employee_name: string;
  position: string;
  pay_basis: PayBasis;

  days_worked: string;
  hours_worked: string;
  overtime_hours: string;

  basic_pay: string;
  overtime_pay: string;
  allowances: string;
  bonus: string;
  gross_pay: string;

  epf_employee: string;
  socso_employee: string;
  eis_employee: string;
  tax_deduction: string;
  other_deductions: string;
  total_deductions: string;

  epf_employer: string;
  socso_employer: string;
  eis_employer: string;
  employer_contributions: string;
  employer_cost: string;

  net_pay: string;
  note: string;
}

export interface PayrollTotals {
  basic_pay: string;
  overtime_pay: string;
  allowances: string;
  bonus: string;
  gross_pay: string;
  epf_employee: string;
  epf_employer: string;
  socso_employee: string;
  socso_employer: string;
  eis_employee: string;
  eis_employer: string;
  tax_deduction: string;
  other_deductions: string;
  employee_deductions: string;
  employer_contributions: string;
  employer_cost: string;
  net_pay: string;
}

export interface PayrollRun {
  id: number;
  reference: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: PayrollStatus;
  notes: string;
  accrual_transaction_id: number | null;
  payment_transaction_id: number | null;
  headcount: number;
  payslips: PayslipRow[];
  totals: PayrollTotals;
  ad_hoc_wage_warnings: string[];
}

export interface PayrollRunSummary {
  id: number;
  reference: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: PayrollStatus;
  headcount: number;
  gross_pay: string;
  employer_cost: string;
  net_pay: string;
}

export interface PayrollOverview {
  runs: PayrollRunSummary[];
  current: PayrollRun | null;
  employees: EmployeeRecord[];
  outstanding_statutory: Record<string, string>;
  period_wage_cost: string;
  period_employer_contributions: string;
  rules_label: string;
}

/** The fields a payroll clerk may edit; everything else is derived. */
export interface PayslipEdit {
  days_worked?: string;
  hours_worked?: string;
  overtime_hours?: string;
  allowances?: string;
  bonus?: string;
  tax_deduction?: string;
  other_deductions?: string;
  note?: string;
}
