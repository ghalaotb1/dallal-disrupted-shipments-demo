"use client";

import { useEffect, useState } from "react";
import { Eye, FlaskConical, Play } from "lucide-react";
import { cn } from "@/lib/cn";
import { modelApi } from "@/lib/live/client";
import { Card, CardHeader } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import type { LiveReplay2, LiveReplayOutcome } from "@/types/live";

const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`;

/** Demo A: a REAL held-out delivery task goes through the live agent; the model result is labelled; the real outcome is revealed afterwards. */
export function ReplayDemo() {
  const [avail, setAvail] = useState<{ available: boolean; reason: string | null } | null>(null);
  const [run, setRun] = useState<LiveReplay2 | null>(null);
  const [outcome, setOutcome] = useState<LiveReplayOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void modelApi.replayStatus().then(setAvail).catch(() => setAvail({ available: false, reason: "backend unreachable" }));
  }, []);

  async function go() {
    setBusy(true);
    setErr(null);
    setOutcome(null);
    try {
      setRun(await modelApi.replayRun(Math.floor(Math.random() * 100000)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  if (avail && !avail.available) {
    return (
      <Card>
        <CardHeader icon={<FlaskConical />} title="Real-data agent replay" subtitle="Needs the LaDe tables on this machine" />
        <p className="px-4 pb-4 text-xs text-ink-3">{avail.reason}</p>
      </Card>
    );
  }
  const r = run?.risk;
  const model = r?.source === "model";
  return (
    <Card>
      <CardHeader
        icon={<FlaskConical />}
        title="Real-data agent replay"
        subtitle="A real held-out delivery task (LaDe, Shanghai) goes through the live agent. Not SPL data."
        actions={
          <Button size="xs" variant="primary" disabled={busy} onClick={() => void go()}>
            <Play /> {run ? "Replay another real task" : "Replay a real task"}
          </Button>
        }
      />
      <div className="space-y-3 px-4 pb-4">
        {err ? <p className="text-xs text-crit-700">{err}</p> : null}
        {!run ? <p className="text-xs text-ink-3">The agent sees the task 10 minutes after the courier accepted it. Workload and delivery history are read point-in-time (only what was already known). The real outcome stays hidden until you reveal it.</p> : null}
        {run ? (
          <>
            <p className="text-2xs text-ink-4">
              {run.source} · accepted {run.accepted_at}, agent sees it at {run.as_of} ({run.timestamps_note})
            </p>
            <ol className="space-y-1">
              {run.steps.map((s, i) => (
                <li key={i} className="rounded-md border border-line-soft bg-subtle px-2.5 py-1.5 text-xs">
                  <span className="font-mono text-ink">{s.tool}</span> <span className="text-ink-3">- {s.summary}</span>
                  {s.tool === "predict_risk" ? (
                    <span className={cn("ml-2 rounded px-1.5 py-px text-[10.5px] font-semibold uppercase", model ? "bg-ok-50 text-ok-700" : "bg-warn-50 text-warn-700")}>{model ? "model" : "heuristic - model abstained"}</span>
                  ) : null}
                  {s.tool === "predict_risk" ? (
                    <ul className="mt-1 list-disc pl-4 text-2xs text-ink-3">
                      {s.facts.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ol>
            {model && r?.probability != null ? (
              <p className="text-13 text-ink-2">
                Trained model: P(task takes longer than {run.slow_threshold_min.toFixed(0)} min) = <b>{pct(r.probability, 2)}</b> (band <b>{r.band}</b>) vs {pct(r.meta?.base_rate_source ?? 0)} base rate in the source data.
              </p>
            ) : (
              <p className="text-xs text-warn-700">
                No trained model scored this task: {r?.meta?.why_heuristic ?? "abstained"}. The labelled heuristic had nothing to go on, so no risk claim is made.
              </p>
            )}
            <p className="text-13 text-ink">
              <b>Agent decision:</b> {run.decision.headline}
            </p>
            <div className="flex items-center gap-2">
              <Button size="xs" variant="secondary" onClick={() => void modelApi.replayOutcome(run.case_id).then(setOutcome)}>
                <Eye /> Reveal what actually happened
              </Button>
              {outcome ? (
                <span className="text-xs text-ink-2">
                  The task took <b>{outcome.duration_min.toFixed(0)} min</b> - {outcome.slow ? "SLOW (above the threshold)" : "not slow"}. {model && r?.band ? `The model said "${r.band}".` : ""} One case proves nothing; the held-out metrics do.
                </span>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    </Card>
  );
}
