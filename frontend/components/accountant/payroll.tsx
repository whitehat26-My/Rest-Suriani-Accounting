"use client";

/**
 * The payroll panel.
 *
 * A run is shown as one wide table because that is how payroll is actually
 * read - across a row, from what someone worked to what they take home, with
 * the employer's own cost at the end. The table scrolls inside its own
 * container rather than pushing the page sideways.
 *
 * Three columns of the table are inputs and the rest are derived, so only a
 * draft run is editable. Once a run is approved it has been posted to the
 * ledger, and the table becomes a record rather than a form.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { money, ratingColor, ratingGlyph, shortDate, toNumber } from "@/lib/format";
import type {
  PayrollOverview,
  PayrollRun,
  PayrollStatus,
  PayslipEdit,
  PayslipRow,
} from "@/lib/types";

const STATUS_STYLE: Record<PayrollStatus, { label: string; rating: string; hint: string }> = {
  DRAFT: {
    label: "Draft",
    rating: "watch",
    hint: "Nothing has been posted to the ledger yet. Edit freely.",
  },
  APPROVED: {
    label: "Approved",
    rating: "good",
    hint: "Posted to the ledger. The wages are owed but not yet handed over.",
  },
  PAID: {
    label: "Paid",
    rating: "good",
    hint: "Take-home pay has left the bank. Statutory money is remitted separately.",
  },
};

const BODY_LABEL: Record<string, string> = {
  EPF: "EPF · KWSP",
  SOCSO: "SOCSO · PERKESO",
  EIS: "EIS · PERKESO",
  TAX: "PCB · LHDN",
};

function firstOfMonth(d: Date): string {
  return new Date(d.getFullYear(), d.getMonth(), 1).toLocaleDateString("en-CA");
}

function endOfMonth(d: Date): string {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toLocaleDateString("en-CA");
}

export function PayrollPanel({ period }: { period: string }) {
  const [data, setData] = useState<PayrollOverview | null>(null);
  const [run, setRun] = useState<PayrollRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await api.payrollOverview(period);
      setData(overview);
      setRun(overview.current);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load payroll.");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  async function guarded(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  const selectRun = (id: number) =>
    guarded(async () => setRun(await api.payrollRun(id)));

  const createRun = () =>
    guarded(async () => {
      const now = new Date();
      const created = await api.createPayrollRun({
        period_start: firstOfMonth(now),
        period_end: endOfMonth(now),
        notes: "Monthly payroll",
      });
      setRun(created);
      setData(await api.payrollOverview(period));
    });

  const editPayslip = (payslipId: number, patch: PayslipEdit) =>
    guarded(async () => setRun(await api.updatePayslip(payslipId, patch)));

  const approve = () =>
    guarded(async () => {
      if (!run) return;
      setRun(await api.approvePayrollRun(run.id));
      setData(await api.payrollOverview(period));
    });

  const pay = () =>
    guarded(async () => {
      if (!run) return;
      setRun(await api.payPayrollRun(run.id));
      setData(await api.payrollOverview(period));
    });

  const remit = (body: string, amount: string) =>
    guarded(async () => {
      await api.remitStatutory(body, amount);
      setData(await api.payrollOverview(period));
    });

  if (loading && !data) return <PayrollSkeleton />;

  if (error && !data) {
    return (
      <div className="glass rounded-xl2 border border-status-critical p-8 text-center">
        <p className="text-lg font-semibold text-ink-primary">{error}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-5 rounded-lg bg-accent-soft px-6 py-2.5 text-sm font-semibold text-ink-primary ring-1 ring-inset ring-accent"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {error ? (
        <p
          className="rounded-lg border border-status-critical bg-status-critical/10 px-4 py-3 text-sm font-medium text-ink-primary"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <PayrollSummary data={data} />

      {run ? (
        <RunPanel
          run={run}
          busy={busy}
          onEdit={editPayslip}
          onApprove={approve}
          onPay={pay}
        />
      ) : (
        <EmptyRuns onCreate={createRun} busy={busy} />
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <RunList
          runs={data.runs}
          activeId={run?.id ?? null}
          onSelect={selectRun}
          onCreate={createRun}
          busy={busy}
        />
        <StatutoryPanel
          outstanding={data.outstanding_statutory}
          onRemit={remit}
          busy={busy}
        />
        <TeamPanel employees={data.employees} />
      </div>

      <p className="text-xs leading-relaxed text-ink-muted">
        Contribution rates: {data.rules_label}. EPF, SOCSO and EIS are published as
        banded schedules; this system applies the headline rates against the wage
        ceilings and rounds EPF up to the next ringgit, which tracks the schedules
        closely but is not identical band for band. Check the figures against the
        official schedule before filing a statutory return.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Summary tiles
// --------------------------------------------------------------------------- //
function PayrollSummary({ data }: { data: PayrollOverview }) {
  const wages = toNumber(data.period_wage_cost);
  const contributions = toNumber(data.period_employer_contributions);
  const owed = Object.values(data.outstanding_statutory).reduce(
    (sum, value) => sum + toNumber(value),
    0,
  );

  return (
    <div className="grid gap-6 lg:grid-cols-4">
      <SummaryTile
        label="Wage cost this period"
        value={money(wages)}
        caption="Gross pay charged to the profit statement"
      />
      <SummaryTile
        label="Employer contributions"
        value={money(contributions)}
        caption="EPF and SOCSO the business pays on top"
      />
      <SummaryTile
        label="Total cost of staff"
        value={money(wages + contributions)}
        caption={
          wages > 0
            ? `${((contributions / wages) * 100).toFixed(1)}% on top of gross`
            : "No wages recorded yet"
        }
      />
      <SummaryTile
        label="Owed to KWSP, PERKESO, LHDN"
        value={money(owed)}
        caption={owed > 0 ? "Not yet remitted" : "Nothing outstanding"}
      />
    </div>
  );
}

function SummaryTile({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-xl2 border border-surface-border p-5"
    >
      <p className="text-xs uppercase tracking-wider text-ink-muted">{label}</p>
      <p className="tabular mt-2 text-2xl font-bold text-ink-primary">{value}</p>
      <p className="mt-1 text-xs text-ink-secondary">{caption}</p>
    </motion.div>
  );
}

// --------------------------------------------------------------------------- //
// The run itself
// --------------------------------------------------------------------------- //
function RunPanel({
  run,
  busy,
  onEdit,
  onApprove,
  onPay,
}: {
  run: PayrollRun;
  busy: boolean;
  onEdit: (payslipId: number, patch: PayslipEdit) => Promise<void>;
  onApprove: () => Promise<void>;
  onPay: () => Promise<void>;
}) {
  const status = STATUS_STYLE[run.status];
  const editable = run.status === "DRAFT";
  const color = ratingColor(status.rating);

  return (
    <section className="glass rounded-xl2 border border-surface-border p-6" aria-labelledby="run-heading">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h2 id="run-heading" className="text-lg font-semibold text-ink-primary">
              {run.reference}
            </h2>
            <span
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold"
              style={{ backgroundColor: `${color}22`, color }}
            >
              <span aria-hidden="true">{ratingGlyph(status.rating)}</span>
              {status.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            {shortDate(run.period_start)} — {shortDate(run.period_end)} · paid{" "}
            {shortDate(run.pay_date)} · {run.headcount} staff
          </p>
          <p className="mt-1 text-xs text-ink-muted">{status.hint}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {run.status === "DRAFT" ? (
            <button
              type="button"
              onClick={() => void onApprove()}
              disabled={busy}
              className="rounded-lg bg-accent-soft px-4 py-2 text-sm font-semibold text-ink-primary ring-1 ring-inset ring-accent disabled:opacity-50"
            >
              {busy ? "Working…" : "Approve and post"}
            </button>
          ) : null}
          {run.status === "APPROVED" ? (
            <button
              type="button"
              onClick={() => void onPay()}
              disabled={busy}
              className="rounded-lg bg-accent-soft px-4 py-2 text-sm font-semibold text-ink-primary ring-1 ring-inset ring-accent disabled:opacity-50"
            >
              {busy ? "Working…" : `Pay ${money(run.totals.net_pay)}`}
            </button>
          ) : null}
        </div>
      </div>

      {run.ad_hoc_wage_warnings.length > 0 ? (
        <ul className="mt-5 space-y-2">
          {run.ad_hoc_wage_warnings.map((warning) => (
            <li
              key={warning}
              className="flex items-start gap-2 rounded-lg border border-status-warning/40 bg-status-warning/10 px-4 py-3 text-sm text-ink-secondary"
            >
              <span
                className="mt-0.5 shrink-0 font-bold"
                style={{ color: ratingColor("warning") }}
                aria-hidden="true"
              >
                {ratingGlyph("warning")}
              </span>
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <PayslipTable run={run} editable={editable} busy={busy} onEdit={onEdit} />

      <RunTotals run={run} />
    </section>
  );
}

function PayslipTable({
  run,
  editable,
  busy,
  onEdit,
}: {
  run: PayrollRun;
  editable: boolean;
  busy: boolean;
  onEdit: (payslipId: number, patch: PayslipEdit) => Promise<void>;
}) {
  return (
    <div className="mt-5 overflow-x-auto">
      <table className="w-full min-w-[1240px] text-sm">
        <thead>
          <tr className="border-b border-surface-border text-xs uppercase tracking-wider text-ink-muted">
            <th scope="col" className="py-2 pr-3 text-left font-medium">Employee</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Days</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">OT hrs</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Basic</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Overtime</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Allowance</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Bonus</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Gross</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">EPF</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">SOCSO</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">EIS</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Other</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Net pay</th>
            <th scope="col" className="py-2 pl-2 text-right font-medium">Cost to us</th>
          </tr>
        </thead>
        <tbody>
          {run.payslips.map((slip) => (
            <PayslipTableRow
              key={slip.id}
              slip={slip}
              editable={editable}
              busy={busy}
              onEdit={onEdit}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PayslipTableRow({
  slip,
  editable,
  busy,
  onEdit,
}: {
  slip: PayslipRow;
  editable: boolean;
  busy: boolean;
  onEdit: (payslipId: number, patch: PayslipEdit) => Promise<void>;
}) {
  const daily = slip.pay_basis === "DAILY";

  return (
    <tr className="border-b border-surface-border/60 last:border-0">
      <th scope="row" className="min-w-[190px] py-2 pr-3 text-left font-normal">
        <span className="block whitespace-nowrap text-ink-primary">
          {slip.employee_name}
        </span>
        <span className="block whitespace-nowrap text-xs text-ink-muted">
          {slip.position} · {slip.pay_basis.toLowerCase()}
        </span>
      </th>
      {daily ? (
        <NumberCell
          value={slip.days_worked}
          editable={editable}
          busy={busy}
          decimals={0}
          onCommit={(value) => onEdit(slip.id, { days_worked: value })}
        />
      ) : (
        <td className="px-2 py-2 text-right text-ink-muted" aria-label="Not applicable">
          —
        </td>
      )}
      <NumberCell
        value={slip.overtime_hours}
        editable={editable}
        busy={busy}
        decimals={0}
        onCommit={(value) => onEdit(slip.id, { overtime_hours: value })}
      />
      <MoneyCell value={slip.basic_pay} />
      <MoneyCell value={slip.overtime_pay} />
      <NumberCell
        value={slip.allowances}
        editable={editable}
        busy={busy}
        decimals={2}
        onCommit={(value) => onEdit(slip.id, { allowances: value })}
      />
      <NumberCell
        value={slip.bonus}
        editable={editable}
        busy={busy}
        decimals={2}
        onCommit={(value) => onEdit(slip.id, { bonus: value })}
      />
      <MoneyCell value={slip.gross_pay} strong />
      <MoneyCell value={slip.epf_employee} muted />
      <MoneyCell value={slip.socso_employee} muted />
      <MoneyCell value={slip.eis_employee} muted />
      <NumberCell
        value={slip.other_deductions}
        editable={editable}
        busy={busy}
        decimals={2}
        onCommit={(value) => onEdit(slip.id, { other_deductions: value })}
      />
      <MoneyCell value={slip.net_pay} strong />
      <MoneyCell value={slip.employer_cost} />
    </tr>
  );
}

function MoneyCell({
  value,
  strong = false,
  muted = false,
}: {
  value: string;
  strong?: boolean;
  muted?: boolean;
}) {
  return (
    <td
      className={`tabular px-2 py-2 text-right ${
        strong ? "font-semibold text-ink-primary" : muted ? "text-ink-muted" : "text-ink-secondary"
      }`}
    >
      {money(value)}
    </td>
  );
}

/** An input in a draft run, plain text once the run is posted. */
function NumberCell({
  value,
  editable,
  busy,
  decimals,
  onCommit,
}: {
  value: string;
  editable: boolean;
  busy: boolean;
  decimals: number;
  onCommit: (value: string) => Promise<void>;
}) {
  const display = useMemo(
    () => toNumber(value).toFixed(decimals),
    [value, decimals],
  );
  const [draft, setDraft] = useState(display);

  useEffect(() => setDraft(display), [display]);

  if (!editable) {
    return (
      <td className="tabular px-2 py-2 text-right text-ink-secondary">
        {decimals === 0 ? display : money(value)}
      </td>
    );
  }

  return (
    <td className="px-2 py-2 text-right">
      <input
        type="number"
        min="0"
        step={decimals === 0 ? "1" : "0.01"}
        value={draft}
        disabled={busy}
        onChange={(event) => setDraft(event.target.value)}
        // Commit on blur rather than on every keystroke: each save recomputes
        // the whole run server-side, and doing that per character would be
        // both slow and jumpy to type into.
        onBlur={() => {
          if (draft !== display && draft !== "") void onCommit(draft);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        aria-label="Editable payroll value"
        className="tabular w-20 rounded-md border border-surface-border bg-surface-sunken px-2 py-1 text-right text-ink-primary disabled:opacity-50"
      />
    </td>
  );
}

function RunTotals({ run }: { run: PayrollRun }) {
  const t = run.totals;
  const rows: { label: string; value: string; note?: string; strong?: boolean }[] = [
    { label: "Gross pay", value: t.gross_pay, note: "Charged to Salaries & Wages" },
    {
      label: "Employee deductions",
      value: t.employee_deductions,
      note: "Held for KWSP, PERKESO and LHDN",
    },
    { label: "Net pay", value: t.net_pay, note: "What the staff receive", strong: true },
    {
      label: "Employer contributions",
      value: t.employer_contributions,
      note: "An extra cost on top of gross",
    },
    {
      label: "Total cost to the restaurant",
      value: t.employer_cost,
      note: "Gross plus employer contributions",
      strong: true,
    },
  ];

  return (
    <dl className="mt-6 grid gap-4 border-t border-surface-border pt-5 sm:grid-cols-3 lg:grid-cols-5">
      {rows.map((row) => (
        <div key={row.label}>
          <dt className="text-xs uppercase tracking-wider text-ink-muted">{row.label}</dt>
          <dd
            className={`tabular mt-1 text-lg ${
              row.strong ? "font-bold text-ink-primary" : "font-semibold text-ink-secondary"
            }`}
          >
            {money(row.value)}
          </dd>
          {row.note ? (
            <dd className="mt-0.5 text-xs text-ink-muted">{row.note}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

// --------------------------------------------------------------------------- //
// Side panels
// --------------------------------------------------------------------------- //
function RunList({
  runs,
  activeId,
  onSelect,
  onCreate,
  busy,
}: {
  runs: PayrollOverview["runs"];
  activeId: number | null;
  onSelect: (id: number) => Promise<void>;
  onCreate: () => Promise<void>;
  busy: boolean;
}) {
  return (
    <section className="glass rounded-xl2 border border-surface-border p-5" aria-labelledby="runs-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="runs-heading" className="text-sm font-semibold text-ink-primary">
          Payroll runs
        </h2>
        <button
          type="button"
          onClick={() => void onCreate()}
          disabled={busy}
          className="rounded-md px-2.5 py-1 text-xs font-semibold text-accent hover:bg-accent-soft disabled:opacity-50"
        >
          + New run
        </button>
      </div>

      <ul className="mt-3 space-y-1.5">
        {runs.map((item) => {
          const active = item.id === activeId;
          const color = ratingColor(STATUS_STYLE[item.status].rating);
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => void onSelect(item.id)}
                disabled={busy}
                aria-current={active ? "true" : undefined}
                className={`w-full rounded-lg px-3 py-2 text-left transition-colors disabled:opacity-50 ${
                  active ? "bg-accent-soft ring-1 ring-inset ring-accent" : "hover:bg-surface-sunken"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-ink-primary">
                    {shortDate(item.period_start)} — {shortDate(item.period_end)}
                  </span>
                  <span
                    className="shrink-0 text-[10px] font-bold uppercase"
                    style={{ color }}
                  >
                    {STATUS_STYLE[item.status].label}
                  </span>
                </span>
                <span className="tabular mt-0.5 block text-xs text-ink-muted">
                  {item.headcount} staff · {money(item.employer_cost)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function StatutoryPanel({
  outstanding,
  onRemit,
  busy,
}: {
  outstanding: Record<string, string>;
  onRemit: (body: string, amount: string) => Promise<void>;
  busy: boolean;
}) {
  const entries = Object.entries(outstanding).filter(([, value]) => toNumber(value) > 0);

  return (
    <section className="glass rounded-xl2 border border-surface-border p-5" aria-labelledby="statutory-heading">
      <h2 id="statutory-heading" className="text-sm font-semibold text-ink-primary">
        Statutory owed
      </h2>
      {entries.length === 0 ? (
        <p className="mt-3 text-xs text-ink-muted">
          Nothing outstanding. Everything withheld has been remitted.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map(([body, amount]) => (
            <li key={body} className="flex items-center justify-between gap-3">
              <span className="text-xs text-ink-secondary">{BODY_LABEL[body] ?? body}</span>
              <span className="flex items-center gap-2">
                <span className="tabular text-sm font-semibold text-ink-primary">
                  {money(amount)}
                </span>
                <button
                  type="button"
                  onClick={() => void onRemit(body, amount)}
                  disabled={busy}
                  className="rounded-md px-2 py-1 text-[11px] font-semibold text-accent hover:bg-accent-soft disabled:opacity-50"
                >
                  Remit
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TeamPanel({ employees }: { employees: PayrollOverview["employees"] }) {
  return (
    <section className="glass rounded-xl2 border border-surface-border p-5" aria-labelledby="team-heading">
      <h2 id="team-heading" className="text-sm font-semibold text-ink-primary">
        The team
      </h2>
      <ul className="mt-3 space-y-2.5">
        {employees.map((employee) => (
          <li key={employee.id}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xs text-ink-primary">{employee.name}</span>
              <span className="tabular shrink-0 text-xs text-ink-secondary">
                {money(employee.base_rate)}
                <span className="text-ink-muted">
                  {employee.pay_basis === "MONTHLY"
                    ? "/mth"
                    : employee.pay_basis === "DAILY"
                      ? "/day"
                      : "/hr"}
                </span>
              </span>
            </div>
            <p className="text-[11px] text-ink-muted">
              {employee.position}
              {employee.contributes_statutory ? " · EPF & SOCSO" : " · no contributions"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EmptyRuns({ onCreate, busy }: { onCreate: () => Promise<void>; busy: boolean }) {
  return (
    <section className="glass rounded-xl2 border border-dashed border-surface-border p-10 text-center">
      <p className="text-lg font-semibold text-ink-primary">No payroll runs yet</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-secondary">
        A run opens as a draft with a payslip for every active member of staff.
        Nothing reaches the ledger until you approve it.
      </p>
      <button
        type="button"
        onClick={() => void onCreate()}
        disabled={busy}
        className="mt-6 rounded-lg bg-accent-soft px-6 py-2.5 text-sm font-semibold text-ink-primary ring-1 ring-inset ring-accent disabled:opacity-50"
      >
        {busy ? "Working…" : "Start this month's payroll"}
      </button>
    </section>
  );
}

function PayrollSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading payroll">
      <div className="grid gap-6 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-xl2 border border-surface-border bg-surface-raised/40"
          />
        ))}
      </div>
      <div className="h-96 animate-pulse rounded-xl2 border border-surface-border bg-surface-raised/40" />
    </div>
  );
}
