"use client";

import { useRouter } from "next/router";
import Head from "next/head";
import dynamic from "next/dynamic";
import useSWR from "swr";

import { Header } from "@/components/layout/header";
import { Footer } from "@/components/layout/footer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatsCard } from "@/components/stats-card";
import { useTranslation, type Locale } from "@/lib/i18n";
import { useQualityAnalysisSummary, useFullQualityAnalysis } from "@/hooks/useQualityAnalysis";
import { AdminTradeAnalysis } from "@/components/trade-evaluation/AdminTradeAnalysis";
import { BarChart3 } from "lucide-react";

// Dynamic imports for animated components (SSR disabled)
const PerformanceAttribution = dynamic(
  () => import("@/components/admin/performance-attribution").then((mod) => mod.PerformanceAttribution),
  { ssr: false, loading: () => <div className="h-32 bg-muted/30 rounded-lg animate-pulse" /> }
);

function ConfidenceCalibrationTable({
  data,
  evData,
  t,
}: {
  data: Record<string, { n: number; wins: number; win_rate: number | null }>;
  evData: Record<string, { ev: number | null; avg_win_rr: number | null; avg_loss_rr: number | null }>;
  t: (key: string) => string;
}) {
  const levels = ["HIGH", "MEDIUM", "LOW"];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50">
            <th className="text-left py-2 px-3 text-muted-foreground">{t("quality.confidenceLevel")}</th>
            <th className="text-right py-2 px-3 text-muted-foreground">{t("quality.trades")}</th>
            <th className="text-right py-2 px-3 text-muted-foreground">{t("quality.winRate")}</th>
            <th className="text-right py-2 px-3 text-muted-foreground">{t("quality.ev")}</th>
          </tr>
        </thead>
        <tbody>
          {levels.map((level) => {
            const d = data[level];
            if (!d || d.n === 0) return null;
            const wr = d.win_rate !== null ? `${(d.win_rate * 100).toFixed(1)}%` : "N/A";
            const ev = evData[level]?.ev;
            const evStr = ev !== null && ev !== undefined ? (ev >= 0 ? `+${ev.toFixed(4)}` : ev.toFixed(4)) : "N/A";
            const evColor = ev !== null && ev !== undefined ? (ev >= 0 ? "text-green-400" : "text-red-400") : "";
            return (
              <tr key={level} className="border-b border-border/30">
                <td className="py-2 px-3 font-medium">{level}</td>
                <td className="text-right py-2 px-3">{d.wins}/{d.n}</td>
                <td className="text-right py-2 px-3">{wr}</td>
                <td className={`text-right py-2 px-3 ${evColor}`}>{evStr}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GradeDistributionBar({ grades }: { grades: Record<string, number> }) {
  const order = ["A+", "A", "B", "C", "D", "F"];
  const colors: Record<string, string> = {
    "A+": "bg-green-500",
    A: "bg-green-400",
    B: "bg-blue-400",
    C: "bg-yellow-400",
    D: "bg-orange-400",
    F: "bg-red-400",
  };
  const total = Object.values(grades).reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex rounded-lg overflow-hidden h-8">
        {order.map((grade) => {
          const count = grades[grade] || 0;
          if (count === 0) return null;
          const pct = (count / total) * 100;
          return (
            <div
              key={grade}
              className={`${colors[grade]} flex items-center justify-center text-xs font-bold text-white`}
              style={{ width: `${pct}%` }}
              title={`${grade}: ${count}`}
            >
              {pct >= 10 ? `${grade}:${count}` : ""}
            </div>
          );
        })}
      </div>
      <div className="flex gap-3 text-xs text-muted-foreground flex-wrap">
        {order.map((grade) => {
          const count = grades[grade] || 0;
          if (count === 0) return null;
          return (
            <span key={grade}>
              <span className={`inline-block w-2 h-2 rounded-full ${colors[grade]} mr-1`} />
              {grade}: {count}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export default function QualityPage() {
  const router = useRouter();
  const locale = (router.locale || "en") as Locale;
  const { t } = useTranslation(locale);
  const { analysis, isLoading } = useQualityAnalysisSummary();
  const { report: fullReport } = useFullQualityAnalysis();

  // Fetch attribution data for PerformanceAttribution component
  const { data: attributionData } = useSWR(
    "/api/public/trade-evaluation/attribution",
    { refreshInterval: 120000 }
  );

  // Fetch HOLD counterfactuals
  const { data: holdCounterfactuals } = useSWR(
    "/api/public/quality-analysis/hold-counterfactuals",
    { refreshInterval: 120000 }
  );

  // Fetch quality quintiles
  const { data: quintiles } = useSWR(
    "/api/public/quality-analysis/quintiles",
    { refreshInterval: 120000 }
  );

  const noData = !analysis || analysis.status === "no_data" || analysis.total_trades === 0;

  return (
    <>
      <Head>
        <title>{t("quality.title")} - AlgVex</title>
        <meta name="description" content="AI quality analysis and outcome feedback" />
      </Head>

      <div className="min-h-screen gradient-bg">
        <Header locale={locale} t={t} />

        <main className="pt-24 pb-16 px-4">
          <div className="container mx-auto">
            <div className="mb-8">
              <h1 className="text-4xl font-bold mb-2">{t("quality.title")}</h1>
              <p className="text-muted-foreground">{t("quality.subtitle")}</p>
            </div>

            {isLoading ? (
              <div className="text-center py-16 text-muted-foreground">{t("common.loading")}</div>
            ) : noData ? (
              <Card className="border-border/50">
                <CardContent className="py-16 text-center text-muted-foreground">
                  {t("quality.noData")}
                </CardContent>
              </Card>
            ) : (
              <>
                {/* Stats Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                  <StatsCard
                    title={t("quality.totalTrades")}
                    value={analysis.total_trades}
                    type="neutral"
                    icon="activity"
                  />
                  <StatsCard
                    title={t("quality.overallWinRate")}
                    value={`${(analysis.overall_win_rate * 100).toFixed(1)}%`}
                    type={analysis.overall_win_rate >= 0.5 ? "profit" : "loss"}
                    icon="target"
                  />
                  <StatsCard
                    title={t("quality.trendFollowing")}
                    value={
                      analysis.counter_trend?.trend_following?.win_rate !== null
                        ? `${((analysis.counter_trend.trend_following.win_rate || 0) * 100).toFixed(0)}%`
                        : "N/A"
                    }
                    subtitle={`${analysis.counter_trend?.trend_following?.n || 0} ${t("quality.trades")}`}
                    type="neutral"
                    icon="trending"
                  />
                  <StatsCard
                    title={t("quality.counterTrendLabel")}
                    value={
                      analysis.counter_trend?.counter_trend?.win_rate !== null
                        ? `${((analysis.counter_trend.counter_trend.win_rate || 0) * 100).toFixed(0)}%`
                        : "N/A"
                    }
                    subtitle={`${analysis.counter_trend?.counter_trend?.n || 0} ${t("quality.trades")}`}
                    type="neutral"
                    icon="alert"
                  />
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                  {/* Confidence Calibration */}
                  <Card className="border-border/50">
                    <CardHeader>
                      <CardTitle>{t("quality.confidenceCalibration")}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ConfidenceCalibrationTable
                        data={analysis.confidence_calibration}
                        evData={analysis.confidence_ev || {}}
                        t={t}
                      />
                      {analysis.calibration_flags && analysis.calibration_flags.length > 0 ? (
                        <div className="mt-4 space-y-1">
                          {analysis.calibration_flags.map((flag, i) => (
                            <div key={i} className="text-sm text-yellow-400 flex items-start gap-2">
                              <span>&#9888;&#65039;</span>
                              <span>{flag}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-4 text-sm text-green-400">
                          &#10003; {t("quality.noFlags")}
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Entry Timing Effectiveness */}
                  <Card className="border-border/50">
                    <CardHeader>
                      <CardTitle>{t("quality.entryTiming")}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {["ENTER", "REJECT"].map((verdict) => {
                          const d = analysis.entry_timing?.[verdict as "ENTER" | "REJECT"];
                          if (!d || d.n === 0) return null;
                          const wr = d.win_rate !== null ? d.win_rate * 100 : 0;
                          const label = verdict === "ENTER" ? t("quality.enter") : t("quality.reject");
                          return (
                            <div key={verdict}>
                              <div className="flex justify-between text-sm mb-1">
                                <span>{label}</span>
                                <span>
                                  {d.wins}/{d.n} ({wr.toFixed(1)}%)
                                </span>
                              </div>
                              <div className="w-full bg-muted rounded-full h-3">
                                <div
                                  className={`h-3 rounded-full ${verdict === "ENTER" ? "bg-green-500" : "bg-red-400"}`}
                                  style={{ width: `${Math.max(wr, 2)}%` }}
                                />
                              </div>
                            </div>
                          );
                        })}
                        {(!analysis.entry_timing?.ENTER?.n && !analysis.entry_timing?.REJECT?.n) && (
                          <div className="text-sm text-muted-foreground">{t("quality.noData")}</div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Grade Distribution */}
                <Card className="border-border/50 mb-8">
                  <CardHeader>
                    <CardTitle>{t("quality.gradeDistribution")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <GradeDistributionBar grades={analysis.grade_distribution || {}} />
                  </CardContent>
                </Card>

                {/* Trade Quality Analysis (from AdminTradeAnalysis) */}
                <div className="mb-8">
                  <AdminTradeAnalysis />
                </div>

                {/* Performance Attribution */}
                <Card className="border-border/50 mb-8">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <BarChart3 className="h-5 w-5" />
                      Performance Attribution
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <PerformanceAttribution data={attributionData} />
                  </CardContent>
                </Card>

                {/* Quality Quintiles */}
                {quintiles && Array.isArray(quintiles) && quintiles.length > 0 && (
                  <Card className="border-border/50 mb-8">
                    <CardHeader>
                      <CardTitle>Quality Score Quintiles</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-border/50">
                              <th className="text-left py-2 px-3 text-muted-foreground">Quintile</th>
                              <th className="text-right py-2 px-3 text-muted-foreground">Trades</th>
                              <th className="text-right py-2 px-3 text-muted-foreground">Win Rate</th>
                              <th className="text-right py-2 px-3 text-muted-foreground">Avg PnL</th>
                              <th className="text-right py-2 px-3 text-muted-foreground">Score Range</th>
                            </tr>
                          </thead>
                          <tbody>
                            {quintiles.map((q: any, i: number) => (
                              <tr key={i} className="border-b border-border/30">
                                <td className="py-2 px-3 font-medium">Q{i + 1}</td>
                                <td className="text-right py-2 px-3">{q.count || q.n || 0}</td>
                                <td className="text-right py-2 px-3">
                                  <span className={(q.win_rate || 0) >= 50 ? "text-green-400" : "text-red-400"}>
                                    {(q.win_rate || 0).toFixed(1)}%
                                  </span>
                                </td>
                                <td className={`text-right py-2 px-3 font-mono ${(q.avg_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {(q.avg_pnl || 0) >= 0 ? "+" : ""}{(q.avg_pnl || 0).toFixed(2)}%
                                </td>
                                <td className="text-right py-2 px-3 text-muted-foreground font-mono">
                                  {q.score_min !== undefined ? `${q.score_min}-${q.score_max}` : "--"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* HOLD Counterfactuals */}
                {holdCounterfactuals && Array.isArray(holdCounterfactuals) && holdCounterfactuals.length > 0 && (
                  <Card className="border-border/50 mb-8">
                    <CardHeader>
                      <CardTitle>HOLD Counterfactuals</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-3 max-h-[400px] overflow-auto">
                        {holdCounterfactuals.slice(0, 50).map((cf: any, i: number) => {
                          const ts = cf.timestamp ? new Date(cf.timestamp) : null;
                          const timeStr = ts && !isNaN(ts.getTime())
                            ? ts.toLocaleDateString("en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
                            : "--";
                          const verdictColor =
                            cf.verdict === "correct" ? "text-green-500" :
                            cf.verdict === "wrong" ? "text-red-500" : "text-muted-foreground";
                          return (
                            <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/30 text-sm">
                              <span className="font-mono text-xs text-muted-foreground w-28 flex-shrink-0">{timeStr}</span>
                              <span className="font-medium w-16 flex-shrink-0">{cf.proposed_signal || "--"}</span>
                              <span className="text-xs text-muted-foreground flex-shrink-0">{cf.hold_source || "--"}</span>
                              <span className={`text-xs font-mono flex-shrink-0 ${(cf.price_change_pct || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                                {(cf.price_change_pct || 0) >= 0 ? "+" : ""}{(cf.price_change_pct || 0).toFixed(2)}%
                              </span>
                              <span className={`text-xs font-medium flex-shrink-0 ${verdictColor}`}>
                                {cf.verdict || "--"}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                      <div className="text-xs text-muted-foreground text-center mt-3">
                        {holdCounterfactuals.length} total counterfactual records
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Full Quality Report (raw analyses) */}
                {fullReport && fullReport.analyses && (
                  <Card className="border-border/50 mb-8">
                    <CardHeader>
                      <CardTitle>Full Quality Analysis Report</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {Object.entries(fullReport.analyses).map(([key, value]: [string, any]) => (
                          <details key={key} className="group">
                            <summary className="cursor-pointer text-sm font-medium py-2 px-3 rounded-lg bg-muted/30 border border-border/30 hover:bg-muted/50 transition-colors">
                              {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                            </summary>
                            <div className="mt-2 p-3 rounded-lg bg-muted/20 border border-border/20">
                              <pre className="text-xs text-muted-foreground whitespace-pre-wrap overflow-auto max-h-[300px]">
                                {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
                              </pre>
                            </div>
                          </details>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Last Updated */}
                {analysis.generated_at && (
                  <p className="text-sm text-muted-foreground text-center">
                    {t("common.lastUpdated")}: {new Date(analysis.generated_at).toLocaleString()}
                  </p>
                )}
              </>
            )}
          </div>
        </main>

        <Footer t={t} />
      </div>
    </>
  );
}
