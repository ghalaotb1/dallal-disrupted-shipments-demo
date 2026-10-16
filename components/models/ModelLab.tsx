"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Play, Shuffle } from "lucide-react";
import { cn } from "@/lib/cn";
import { modelApi } from "@/lib/live/client";
import { useLive } from "@/store/live";
import { Card, CardHeader, EmptyState, SectionLabel } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Capabilities } from "@/components/live/Capabilities";
import { LiveTag } from "@/components/live/LiveTags";
import type { LiveModelCard, LiveModelSummary, LiveReplay, LiveScore } from "@/types/live";

const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`;

interface SeqReport {
  contenders: Record<string, { valid: { pr_auc: number; roc_auc: number }; test: { pr_auc: number; roc_auc: number } }>;
  decision: { reading: string; adopt_sequence_model: boolean };
}

function Reliability({ rows }: { rows: { mean_predicted: number; observed: number }[] }) {
  const max = Math.max(0.001, ...rows.flatMap((r) => [r.mean_predicted, r.observed])) * 1.1;
  const x = (v: number) => 8 + (v / max) * 144;
  const y = (v: number) => 152 - (v / max) * 144;
  return (
    <svg viewBox="0 0 160 160" className="h-40 w-40 shrink-0" role="img" aria-label="Reliability diagram: predicted vs observed rate by decile on the held-out test window">
      <rect x="8" y="8" width="144" height="144" className="fill-subtle stroke-line" />
      <line x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} className="stroke-ink-5" strokeDasharray="3 3" />
      {rows.map((r, i) => (
        <circle key={i} cx={x(r.mean_predicted)} cy={y(r.observed)} r="3" className="fill-brand-600" />
      ))}
      <text x="80" y="159" textAnchor="middle" className="fill-ink-4 text-[7px]">predicted</text>
      <text x="4" y="80" textAnchor="middle" transform="rotate(-90 4 80)" className="fill-ink-4 text-[7px]">observed</text>
    </svg>
  );
}

function ModelPanel({ m }: { m: LiveModelSummary }) {
  const [card, setCard] = useState<LiveModelCard | null>(null);
  const [replay, setReplay] = useState<LiveReplay | null>(null);
  const [replayErr, setReplayErr] = useState<string | null>(null);
  const [feats, setFeats] = useState<Record<string, string>>({});
  const [score, setScore] = useState<(LiveScore & { err?: string }) | null>(null);
  const [outcome, setOutcome] = useState<number | null>(null);

  useEffect(() => {
    void modelApi.card(m.model_id).then(setCard).catch(() => undefined);
  }, [m.model_id]);

  const run = useCallback(
    async (values: Record<string, string>) => {
      const num: Record<string, number> = {};
      for (const [k, v] of Object.entries(values)) num[k] = Number(v);
      try {
        setScore(await modelApi.score(m.model_id, num));
      } catch (e) {
        setScore({ model_id: m.model_id, abstained: true, base_rate_source: 0, err: e instanceof Error ? e.message : "request failed" });
      }
    },
    [m.model_id],
  );

  async function loadReplay() {
    setReplayErr(null);
    try {
      const r = replay ?? (await modelApi.replay(m.model_id, 12, 0));
      setReplay(r);
      const row = r.rows[Math.floor(Math.random() * r.rows.length)];
      const f = Object.fromEntries(Object.entries(row.features).map(([k, v]) => [k, String(Math.round(v * 1000) / 1000)]));
      setFeats(f);
      setOutcome(row.outcome);
      await run(f);
    } catch (e) {
      setReplayErr(e instanceof Error ? e.message : "replay unavailable");
    }
  }

  const t = m.test;
  const bandCls = score?.band === "high" ? "text-crit-700" : score?.band === "elevated" ? "text-warn-700" : "text-ok-700";
  return (
    <Card>
      <CardHeader
        icon={<FlaskConical />}
        title={<span className="font-mono">{m.model_id}</span>}
        subtitle={`${m.source} · ${m.licence}`}
        actions={
          <>
            <LiveTag label="REAL DATA" tip="Trained on a real public dataset; not SPL data" />
          </>
        }
      />
      <div className="grid gap-4 px-4 pb-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <p className="text-13 text-ink-2">
            <b>Predicts:</b> {m.target}.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {[
              ["Test ROC-AUC", `${t.roc_auc.toFixed(3)} (${m.test_auc_95ci[0].toFixed(2)}–${m.test_auc_95ci[1].toFixed(2)})`],
              ["Test PR-AUC", `${t.pr_auc.toFixed(3)} (base rate ${pct(t.prevalence)})`],
              ["Lift @ top 10%", `${t["lift@top10%"].toFixed(1)}×`],
              ["Brier", `${t.brier.toFixed(4)} vs ${t.brier_prevalence_baseline.toFixed(4)} base-rate`],
              ["Calibration error (ECE)", t.ece.toFixed(4)],
              ["Rows train / valid / test", `${m.split.train.toLocaleString()} / ${m.split.valid.toLocaleString()} / ${m.split.test.toLocaleString()}`],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-ink-4">{k}</dt>
                <dd className="font-medium text-ink tabular">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="text-2xs text-ink-3">
            {m.algorithm} · {m.calibration}. Chronological split with embargo; model and calibrator chosen on the validation window only; test touched once.
          </p>
          {card ? (
            <>
              <div className="flex items-start gap-3">
                <Reliability rows={card.metrics.test_calibration.reliability_deciles} />
                <div className="text-xs text-ink-3">
                  <p>
                    Test window: mean predicted {pct(card.metrics.test_calibration.mean_predicted, 2)} vs observed {pct(card.metrics.test_calibration.observed, 2)}. ECE {card.metrics.test_calibration.ece_uncalibrated_raw.toFixed(4)} before → {card.metrics.test_calibration.ece_calibrated.toFixed(4)} after calibration.
                  </p>
                  <p className="mt-1">Bands: elevated ≥ {pct(card.band_thresholds.elevated)}, high ≥ {pct(card.band_thresholds.high)} (validation 85th / 95th percentile).</p>
                </div>
              </div>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-3">
                {card.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>

        <div className="rounded-lg border border-line bg-subtle p-3">
          <SectionLabel>Score a case</SectionLabel>
          <p className="mt-1 text-2xs text-ink-3">Every feature is required; nothing is imputed. Values far outside the training range make the model abstain.</p>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {m.features.map((f) => (
              <label key={f} className="text-2xs text-ink-4">
                {f}
                <input
                  value={feats[f] ?? ""}
                  onChange={(e) => setFeats((s) => ({ ...s, [f]: e.target.value }))}
                  inputMode="decimal"
                  className="mt-0.5 h-7 w-full rounded-md border border-line bg-surface px-2 font-mono text-xs text-ink outline-none focus:border-brand-400"
                />
              </label>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button size="xs" variant="primary" onClick={() => void run(feats)}>
              <Play /> Score
            </Button>
            <Button size="xs" variant="secondary" onClick={() => void loadReplay()}>
              <Shuffle /> Replay a real held-out case
            </Button>
          </div>
          {replayErr ? <p className="mt-1.5 text-2xs text-warn-700">{replayErr}</p> : null}
          {score ? (
            <div className="mt-2 rounded-md border border-line bg-surface px-2.5 py-2 text-xs">
              {score.err ? (
                <p className="text-crit-700">{score.err}</p>
              ) : score.abstained ? (
                <p className="text-warn-700">
                  Abstained: {score.reason}
                  {score.features_outside_range?.length ? ` (${score.features_outside_range.join(", ")})` : ""}.
                </p>
              ) : (
                <>
                  <p>
                    P(target) = <b className={cn("text-sm", bandCls)}>{pct(score.probability ?? 0, 2)}</b> · band <b className={bandCls}>{score.band}</b> · {score.lift_over_base_rate}× the source base rate ({pct(score.base_rate_source)})
                  </p>
                  <p className="mt-0.5 text-ink-3">{score.note}</p>
                </>
              )}
              {outcome !== null ? (
                <p className="mt-1 text-ink-2">
                  What actually happened in the source data: <b>{outcome ? "target event occurred" : "target event did not occur"}</b>. One case proves nothing; see the test metrics.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

export function ModelLab() {
  const connected = useLive((s) => s.status === "connected");
  const [models, setModels] = useState<LiveModelSummary[] | null>(null);
  const [seq, setSeq] = useState<SeqReport | null>(null);

  useEffect(() => {
    if (!connected) return;
    void modelApi.list().then(setModels).catch(() => setModels([]));
    void modelApi.experiment<SeqReport>("sequence_experiment").then(setSeq).catch(() => undefined);
  }, [connected]);

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-3 p-3 lg:p-4">
      <section className="rounded-xl border border-line bg-surface px-5 py-4 shadow-card">
        <h1 className="text-[22px] leading-8 font-semibold tracking-[-0.02em] text-ink">Model Lab</h1>
        <p className="mt-1 max-w-3xl text-13 text-ink-2">
          Risk models trained and calibrated on real public delivery datasets. Each model has one target and one source; they are never merged. These are <b>not trained on SPL data</b>, so probabilities describe the source population and are used by Dallal as ranking evidence only,
          and only when a case supplies a complete in-range feature row.
        </p>
      </section>
      {!connected ? (
        <EmptyState icon={<FlaskConical />} title="Backend not connected" body="Model Lab serves artifacts from the Dallal backend. Start it (or set ?backend=…) to score cases live." />
      ) : models === null ? (
        <p className="p-4 text-13 text-ink-3">Loading models…</p>
      ) : (
        <>
          <Capabilities />
          {models.map((m) => (
            <ModelPanel key={m.model_id} m={m} />
          ))}
          {seq ? (
            <Card>
              <CardHeader title="Sequence model vs tabular (LaDe slow-task risk)" subtitle="Same rows, same labels, same information; adoption rule fixed in advance (≥5% relative PR-AUC on validation and test)." />
              <div className="overflow-x-auto px-4 pb-4">
                <table className="w-full text-left text-xs">
                  <thead className="text-ink-4">
                    <tr>
                      <th className="py-1 pr-3 font-medium">Contender</th>
                      <th className="px-3 font-medium">Valid PR-AUC</th>
                      <th className="px-3 font-medium">Test PR-AUC</th>
                      <th className="px-3 font-medium">Test ROC-AUC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(seq.contenders).map(([k, v]) => (
                      <tr key={k} className="border-t border-line-soft">
                        <td className="py-1 pr-3 font-mono">{k}</td>
                        <td className="px-3 tabular">{v.valid.pr_auc.toFixed(3)}</td>
                        <td className="px-3 tabular">{v.test.pr_auc.toFixed(3)}</td>
                        <td className="px-3 tabular">{v.test.roc_auc.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-ink-2">{seq.decision.reading}</p>
              </div>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}
