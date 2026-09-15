import { BookOpen, CheckCircle2, ShieldOff, Sliders } from "lucide-react";
import type { Metadata } from "next";

import { SeverityBadge } from "@/components/ui/Badge";
import { Card, CardHeader, ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getActivePolicy, getRuleCatalogue, getRuleFrequency } from "@/lib/api";
import { formatCount, humaniseRuleCode } from "@/lib/format";

export const metadata: Metadata = { title: "Validation rules" };
export const dynamic = "force-dynamic";

/**
 * The rule catalogue: what the engine checks, and against what tolerance.
 *
 * This page exists so the console can explain itself. A reviewer told a record
 * failed `AREA_SUM_MISMATCH` deserves to be able to read what that rule checks
 * and what threshold it was judged against, without anyone opening a YAML file
 * on the server. In a system whose output carries legal weight, "why did it say
 * that?" has to be answerable from the interface.
 *
 * The list is read from the live rule registry (`adhikar.validation.registry`),
 * not a hand-maintained copy — so a rule added to the engine appears here the
 * moment it is registered. A documentation page that can silently fall behind
 * the code is not documentation.
 */
export default async function RulesPage() {
  const [catalogue, policy, frequency] = await Promise.all([
    getRuleCatalogue(),
    getActivePolicy(),
    getRuleFrequency(60),
  ]);

  if (catalogue.error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Validation rules" />
        <ErrorPanel message={catalogue.error.message} unreachable={catalogue.error.unreachable} />
      </div>
    );
  }

  const counts = new Map((frequency.data ?? []).map((row) => [row.rule_code, row.count]));

  const groups = catalogue.data.reduce<Record<string, typeof catalogue.data>>((acc, rule) => {
    (acc[rule.group] ??= []).push(rule);
    return acc;
  }, {});

  const enabledCount = catalogue.data.filter((rule) => rule.enabled).length;
  const firedCount = catalogue.data.filter((rule) => (counts.get(rule.code) ?? 0) > 0).length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Validation rules"
        description={
          <>
            {catalogue.data.length} checks in the registry, {enabledCount} enabled under the{" "}
            <strong className="font-semibold text-ink-primary">{policy.data?.name ?? "default"}</strong>{" "}
            policy. Tolerances are configuration — a state that surveys to ±1% instead of ±0.5% edits{" "}
            <code className="font-mono text-xs">policies/validation_policy.yaml</code>, not the code.
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard
          icon={BookOpen}
          label="Registered checks"
          value={formatCount(catalogue.data.length)}
          hint="Read live from the engine's own registry"
        />
        <SummaryCard
          icon={CheckCircle2}
          label="Enabled by policy"
          value={formatCount(enabledCount)}
          hint="A disabled rule is recorded as skipped, never silently dropped"
        />
        <SummaryCard
          icon={Sliders}
          label="Firing in this corpus"
          value={formatCount(firedCount)}
          hint="Rules that have found at least one problem in the ingested records"
        />
      </section>

      {Object.entries(groups).map(([group, rules]) => (
        <Card key={group}>
          <CardHeader
            title={group}
            subtitle={`${rules.length} check${rules.length === 1 ? "" : "s"}`}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-line bg-surface-sunken text-[11px] uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Rule</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">What it checks</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Policy</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Findings here</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rules.map((rule) => {
                  const fired = counts.get(rule.code) ?? 0;
                  return (
                    <tr key={rule.code} className="transition-colors hover:bg-surface-sunken/60">
                      <td className="px-4 py-3 align-top">
                        <span className="block text-[13px] font-semibold text-ink-primary">
                          {humaniseRuleCode(rule.code)}
                        </span>
                        <code className="mt-0.5 block break-anywhere text-[10px] text-ink-muted">
                          {rule.code}
                        </code>
                      </td>
                      <td className="max-w-md px-4 py-3 align-top text-[13px] leading-relaxed text-ink-secondary">
                        {rule.description || (
                          <span className="italic text-ink-muted">
                            Declared in the schema; no rule function registered against it yet.
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top">
                        {rule.enabled ? (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-status-good-ink">
                            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Enabled
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                            <ShieldOff className="h-3.5 w-3.5" aria-hidden /> Disabled
                          </span>
                        )}
                        {rule.severity_override && (
                          <span className="mt-1.5 block">
                            <SeverityBadge severity={rule.severity_override} />
                            <span className="ml-1.5 text-[10px] text-ink-muted">policy override</span>
                          </span>
                        )}
                        {!rule.registered && (
                          <span className="mt-1 block text-[10px] text-ink-muted">not yet implemented</span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top">
                        {fired > 0 ? (
                          <span className="font-mono text-sm font-semibold tabular-nums text-ink-primary">
                            {fired}
                          </span>
                        ) : (
                          <span className="text-xs text-ink-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof BookOpen;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface-card px-4 py-3.5 shadow-card">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-series-1/10">
          <Icon className="h-4 w-4 text-series-1" strokeWidth={2} aria-hidden />
        </span>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</p>
          <p className="text-xl font-bold leading-tight text-ink-primary">{value}</p>
        </div>
      </div>
      <p className="mt-2 text-xs leading-snug text-ink-muted">{hint}</p>
    </div>
  );
}
