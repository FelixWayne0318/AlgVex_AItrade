"use client";

import { motion } from "framer-motion";
import {
  Brain, Clock, Shield, Target, TrendingUp, TrendingDown, Minus,
  CheckCircle, XCircle, AlertTriangle, Database, Timer, BarChart3,
  Gauge, Zap,
} from "lucide-react";

interface PhaseTimeline {
  debate?: number;
  judge?: number;
  entry_timing?: number;
  risk?: number;
  total?: number;
  debate_rounds?: number;
  api_calls?: number;
}

interface RRValidation {
  rr_ratio?: number;
  min_rr?: number;
  is_valid?: boolean;
  is_counter_trend?: boolean;
}

interface DataSources {
  technical?: boolean;
  sentiment?: boolean;
  order_flow?: boolean;
  derivatives?: boolean;
  [key: string]: boolean | undefined;
}

interface Confluence {
  trend_1d?: string;
  momentum_4h?: string;
  levels_30m?: string;
  derivatives?: string;
  aligned_layers?: number;
}

interface EntryTimingAssessment {
  timing_verdict?: string;
  timing_quality?: string;
  counter_trend_risk?: string;
  alignment?: string;
  reason?: string;
}

// v28.0: Dimensional scores from compute_scores_from_features()
interface DimensionalScores {
  trend?: number;
  momentum?: number;
  order_flow?: number;
  vol_ext_risk?: number;
  risk_env?: number;
  net?: string;
  [key: string]: number | string | undefined;
}

// v29.0+: AI Quality Auditor metrics
interface AuditorMetrics {
  data_coverage_rate?: number;
  citation_score?: number;
  mtf_compliance?: number;
  production_quality?: number;
  overall_score?: number;
  [key: string]: number | string | undefined;
}

// v32.1: Risk Manager output
interface RiskManager {
  risk_appetite?: string;
  size_pct?: number;
  reasoning?: string;
}

// v27.0: Reason tags
interface ReasonTags {
  bull_evidence?: string[];
  bear_evidence?: string[];
  judge_reasons?: string[];
  [key: string]: string[] | undefined;
}

interface AIAnalysis {
  signal?: string;
  confidence?: string;
  confidence_score?: number;
  confluence?: Confluence;
  bull_analysis?: string;
  bear_analysis?: string;
  judge_reasoning?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  risk_appetite?: string;
  phase_timeline?: PhaseTimeline;
  rr_validation?: RRValidation;
  data_sources?: DataSources;
  winning_side?: string;
  timestamp?: string;
  entry_timing?: EntryTimingAssessment;
  timing_confidence_adjusted?: string;
  // v28.0: Dimensional scores
  dimensional_scores?: DimensionalScores;
  // v29.0+: Auditor metrics
  auditor_metrics?: AuditorMetrics;
  // v32.1: Risk Manager
  risk_manager?: RiskManager;
  // v27.0: Reason tags
  reason_tags?: ReasonTags;
}

interface AIDecisionDetailProps {
  analysis?: AIAnalysis | null;
}

export function AIDecisionDetail({ analysis }: AIDecisionDetailProps) {
  if (!analysis || analysis.signal === "NO_DATA") {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <Brain className="h-8 w-8 mb-3 opacity-40" />
        <p className="text-sm font-medium">No AI analysis available</p>
        <p className="text-xs mt-1">Waiting for the next analysis cycle</p>
      </div>
    );
  }

  const pt = analysis.phase_timeline || {};
  const rr = analysis.rr_validation || {};
  const ds = analysis.data_sources || {};
  const cf = analysis.confluence || {};
  const et = analysis.entry_timing || {};
  const scores = analysis.dimensional_scores || {};
  const auditor = analysis.auditor_metrics || {};
  const rm = analysis.risk_manager || {};
  const tags = analysis.reason_tags || {};

  return (
    <div className="space-y-4">
      {/* Signal Header */}
      <SignalHeader analysis={analysis} />

      {/* v28.0: Dimensional Scores */}
      {Object.keys(scores).length > 0 && scores.net && (
        <DimensionalScoresPanel scores={scores} />
      )}

      {/* Phase Timeline */}
      {pt.total != null && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="p-3 rounded-lg bg-muted/30 border border-border/50"
        >
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Timer className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <span className="text-xs font-medium text-muted-foreground">PHASE TIMELINE</span>
            <span className="ml-auto text-[10px] sm:text-xs text-muted-foreground">
              {pt.api_calls || 0} calls | {pt.debate_rounds || 0} rounds
            </span>
          </div>
          <div className="flex gap-0.5 sm:gap-1 h-5 rounded overflow-hidden">
            {pt.debate != null && pt.total > 0 && (
              <div
                className="bg-blue-500/60 flex items-center justify-center text-[9px] sm:text-[10px] text-white font-mono overflow-hidden"
                style={{ width: `${(pt.debate / pt.total) * 100}%`, minWidth: "28px" }}
                title={`Debate: ${pt.debate}s`}
              >
                <span className="hidden sm:inline">Debate </span>{pt.debate}s
              </div>
            )}
            {pt.judge != null && pt.total > 0 && (
              <div
                className="bg-purple-500/60 flex items-center justify-center text-[9px] sm:text-[10px] text-white font-mono overflow-hidden"
                style={{ width: `${(pt.judge / pt.total) * 100}%`, minWidth: "28px" }}
                title={`Judge: ${pt.judge}s`}
              >
                <span className="hidden sm:inline">Judge </span>{pt.judge}s
              </div>
            )}
            {pt.entry_timing != null && pt.total > 0 && (
              <div
                className="bg-cyan-500/60 flex items-center justify-center text-[9px] sm:text-[10px] text-white font-mono overflow-hidden"
                style={{ width: `${(pt.entry_timing / pt.total) * 100}%`, minWidth: "28px" }}
                title={`Entry Timing: ${pt.entry_timing}s`}
              >
                <span className="hidden sm:inline">ET </span>{pt.entry_timing}s
              </div>
            )}
            {pt.risk != null && pt.total > 0 && (
              <div
                className="bg-orange-500/60 flex items-center justify-center text-[9px] sm:text-[10px] text-white font-mono overflow-hidden"
                style={{ width: `${(pt.risk / pt.total) * 100}%`, minWidth: "28px" }}
                title={`Risk: ${pt.risk}s`}
              >
                <span className="hidden sm:inline">Risk </span>{pt.risk}s
              </div>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 text-right">
            Total: {pt.total}s
          </p>
        </motion.div>
      )}

      {/* R/R Validation */}
      {rr.rr_ratio != null && (
        <div className={`p-3 rounded-lg border ${
          rr.is_valid ? "bg-green-500/5 border-green-500/30" : "bg-red-500/5 border-red-500/30"
        }`}>
          <div className="flex items-center justify-between flex-wrap gap-1">
            <div className="flex items-center gap-2">
              {rr.is_valid ? (
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
              )}
              <span className="text-xs sm:text-sm font-medium">
                R/R {rr.rr_ratio}:1
                <span className="text-muted-foreground font-normal ml-1">
                  (min {rr.min_rr}:1)
                </span>
              </span>
            </div>
            {rr.is_counter_trend && (
              <span className="text-[10px] sm:text-xs px-1.5 sm:px-2 py-0.5 rounded bg-orange-500/10 text-orange-500 border border-orange-500/30">
                Counter-Trend
              </span>
            )}
          </div>
          {/* Price levels */}
          {analysis.entry_price && (
            <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
              <div>
                <span className="text-muted-foreground">Entry</span>
                <p className="font-mono">${Number(analysis.entry_price).toLocaleString()}</p>
              </div>
              <div>
                <span className="text-muted-foreground">SL</span>
                <p className="font-mono text-red-400">
                  {analysis.stop_loss ? `$${Number(analysis.stop_loss).toLocaleString()}` : "N/A"}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">TP</span>
                <p className="font-mono text-green-400">
                  {analysis.take_profit ? `$${Number(analysis.take_profit).toLocaleString()}` : "N/A"}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Confluence Matrix */}
      {cf.aligned_layers != null && (
        <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
          <div className="flex items-center gap-2 mb-2">
            <Target className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">
              CONFLUENCE ({cf.aligned_layers}/4 aligned)
            </span>
          </div>
          <div className="space-y-1">
            {(["trend_1d", "momentum_4h", "levels_30m", "derivatives"] as const).map((key) => {
              const val = cf[key] || "N/A";
              const isBullish = val.toUpperCase().includes("BULLISH");
              const isBearish = val.toUpperCase().includes("BEARISH");
              return (
                <div key={key} className="flex items-center gap-1.5 sm:gap-2 text-xs">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    isBullish ? "bg-green-500" : isBearish ? "bg-red-500" : "bg-yellow-500"
                  }`} />
                  <span className="text-muted-foreground w-20 sm:w-24 flex-shrink-0 text-[10px] sm:text-xs">{key}</span>
                  <span className="font-mono text-foreground/80 truncate text-[10px] sm:text-xs">{val}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Data Source Status */}
      {Object.keys(ds).length > 0 && (
        <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
          <div className="flex items-center gap-2 mb-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">DATA SOURCES</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(ds).map(([name, ok]) => (
              <span
                key={name}
                className={`text-xs px-2 py-0.5 rounded flex items-center gap-1 ${
                  ok ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                }`}
              >
                {ok ? <CheckCircle className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                {name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Entry Timing Assessment (v23.0) */}
      {et.timing_verdict && (
        <div className={`p-3 rounded-lg border ${
          et.timing_verdict === "ENTER" ? "bg-green-500/5 border-green-500/30" : "bg-red-500/5 border-red-500/30"
        }`}>
          <div className="flex items-center justify-between flex-wrap gap-1">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <span className="text-xs font-medium text-muted-foreground">ENTRY TIMING</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={`text-xs font-bold ${
                et.timing_verdict === "ENTER" ? "text-green-500" : "text-red-500"
              }`}>
                {et.timing_verdict === "ENTER" ? "通过 ENTER" : et.timing_verdict === "REJECT" ? "拦截 REJECT" : et.timing_verdict}
              </span>
              {et.timing_quality && (
                <span className={`text-[10px] sm:text-xs px-1.5 py-0.5 rounded ${
                  et.timing_quality === "OPTIMAL" ? "bg-green-500/10 text-green-500" :
                  et.timing_quality === "GOOD" ? "bg-blue-500/10 text-blue-400" :
                  et.timing_quality === "FAIR" ? "bg-yellow-500/10 text-yellow-500" :
                  "bg-red-500/10 text-red-500"
                }`}>
                  {et.timing_quality}
                </span>
              )}
            </div>
          </div>
          {(et.counter_trend_risk || et.alignment || et.reason) && (
            <div className="mt-2 space-y-1 text-xs text-muted-foreground">
              {et.counter_trend_risk && et.counter_trend_risk !== "NONE" && (
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3 w-3 text-orange-500 flex-shrink-0" />
                  <span>Counter-trend: {et.counter_trend_risk}</span>
                </div>
              )}
              {et.alignment && (
                <p className="font-mono text-[10px] sm:text-xs truncate">{et.alignment}</p>
              )}
              {et.reason && (
                <p className="text-[10px] sm:text-xs">{et.reason}</p>
              )}
            </div>
          )}
          {analysis.timing_confidence_adjusted && (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Adjusted confidence: {analysis.timing_confidence_adjusted}
            </p>
          )}
        </div>
      )}

      {/* v32.1: Risk Manager Details */}
      {rm.risk_appetite && (
        <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
          <div className="flex items-center gap-2 mb-2">
            <Shield className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">RISK MANAGER</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs px-2 py-0.5 rounded ${
              rm.risk_appetite === "AGGRESSIVE" ? "bg-red-500/10 text-red-500" :
              rm.risk_appetite === "CONSERVATIVE" ? "bg-blue-500/10 text-blue-400" :
              "bg-yellow-500/10 text-yellow-500"
            }`}>
              {rm.risk_appetite}
            </span>
            {rm.size_pct != null && (
              <span className="text-xs text-muted-foreground font-mono">
                Size: {rm.size_pct}%
              </span>
            )}
          </div>
          {rm.reasoning && (
            <p className="text-[10px] sm:text-xs text-muted-foreground mt-2 line-clamp-3">
              {rm.reasoning}
            </p>
          )}
        </div>
      )}

      {/* v29.0+: Auditor Quality Score */}
      {auditor.overall_score != null && (
        <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
          <div className="flex items-center gap-2 mb-2">
            <Gauge className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">AI QUALITY AUDIT</span>
            <span className={`ml-auto text-xs font-bold ${
              (auditor.overall_score as number) >= 80 ? "text-green-500" :
              (auditor.overall_score as number) >= 60 ? "text-yellow-500" :
              "text-red-500"
            }`}>
              {auditor.overall_score}/100
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {auditor.data_coverage_rate != null && (
              <ScoreMini label="Data Coverage" value={auditor.data_coverage_rate as number} />
            )}
            {auditor.citation_score != null && (
              <ScoreMini label="Citations" value={auditor.citation_score as number} />
            )}
            {auditor.mtf_compliance != null && (
              <ScoreMini label="MTF Compliance" value={auditor.mtf_compliance as number} />
            )}
            {auditor.production_quality != null && (
              <ScoreMini label="Production Quality" value={auditor.production_quality as number} />
            )}
          </div>
        </div>
      )}

      {/* v27.0: Reason Tags */}
      {(tags.bull_evidence?.length || tags.bear_evidence?.length || tags.judge_reasons?.length) && (
        <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">REASON TAGS</span>
          </div>
          <div className="space-y-1.5">
            {tags.bull_evidence && tags.bull_evidence.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-green-500 mr-1">BULL:</span>
                {tags.bull_evidence.map((tag, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {tags.bear_evidence && tags.bear_evidence.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-red-500 mr-1">BEAR:</span>
                {tags.bear_evidence.map((tag, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-500">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {tags.judge_reasons && tags.judge_reasons.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-purple-500 mr-1">JUDGE:</span>
                {tags.judge_reasons.map((tag, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-500">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Winning Side + Risk Appetite */}
      <div className="flex items-center gap-2 sm:gap-3 text-xs flex-wrap">
        {analysis.winning_side && (
          <span className={`px-1.5 sm:px-2 py-0.5 sm:py-1 rounded ${
            analysis.winning_side === "BULL" ? "bg-green-500/10 text-green-500" :
            analysis.winning_side === "BEAR" ? "bg-red-500/10 text-red-500" :
            "bg-yellow-500/10 text-yellow-500"
          }`}>
            {analysis.winning_side}
          </span>
        )}
        {analysis.risk_appetite && !rm.risk_appetite && (
          <span className={`px-1.5 sm:px-2 py-0.5 sm:py-1 rounded ${
            analysis.risk_appetite === "AGGRESSIVE" ? "bg-red-500/10 text-red-500" :
            analysis.risk_appetite === "CONSERVATIVE" ? "bg-blue-500/10 text-blue-400" :
            "bg-muted text-muted-foreground"
          }`}>
            {analysis.risk_appetite}
          </span>
        )}
        {analysis.timestamp && (
          <span className="ml-auto flex items-center gap-1 text-muted-foreground">
            <Clock className="h-3 w-3" />
            {new Date(analysis.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>
    </div>
  );
}

// v28.0: Dimensional Scores Panel
function DimensionalScoresPanel({ scores }: { scores: DimensionalScores }) {
  const dimensions = [
    { key: "trend", label: "Trend", color: "bg-blue-500" },
    { key: "momentum", label: "Momentum", color: "bg-purple-500" },
    { key: "order_flow", label: "Order Flow", color: "bg-cyan-500" },
    { key: "vol_ext_risk", label: "Vol/Ext Risk", color: "bg-orange-500" },
    { key: "risk_env", label: "Risk Env", color: "bg-red-500" },
  ];

  const netLabel = scores.net || "NEUTRAL";
  const netColor =
    netLabel === "BULLISH" ? "text-green-500" :
    netLabel === "BEARISH" ? "text-red-500" :
    "text-yellow-500";

  return (
    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
      <div className="flex items-center gap-2 mb-2">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">DIMENSIONAL SCORES</span>
        <span className={`ml-auto text-xs font-bold ${netColor}`}>
          {netLabel}
        </span>
      </div>
      <div className="space-y-1.5">
        {dimensions.map(({ key, label, color }) => {
          const val = scores[key];
          if (val == null || typeof val !== "number") return null;
          // Score is -1 to +1, normalize to 0-100 for display
          const pct = Math.round(((val + 1) / 2) * 100);
          const displayVal = val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2);
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[10px] sm:text-xs text-muted-foreground w-20 sm:w-24 flex-shrink-0">{label}</span>
              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full ${color}/60`}
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>
              <span className={`text-[10px] font-mono w-10 text-right ${
                val > 0 ? "text-green-500" : val < 0 ? "text-red-500" : "text-muted-foreground"
              }`}>
                {displayVal}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Auditor score mini display
function ScoreMini({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between text-[10px] sm:text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono ${
        value >= 80 ? "text-green-500" : value >= 60 ? "text-yellow-500" : "text-red-500"
      }`}>
        {typeof value === "number" ? Math.round(value) : value}%
      </span>
    </div>
  );
}

function SignalHeader({ analysis }: { analysis: AIAnalysis }) {
  const signal = analysis.signal || "HOLD";
  const isLong = signal === "LONG";
  const isShort = signal === "SHORT";

  const signalLabel = isLong ? "开多 LONG" : isShort ? "开空 SHORT" :
    signal === "HOLD" ? "观望 HOLD" : signal === "CLOSE" ? "平仓 CLOSE" : signal;
  const color = isLong ? "text-green-500" : isShort ? "text-red-500" : "text-yellow-500";
  const bg = isLong ? "bg-green-500/10" : isShort ? "bg-red-500/10" : "bg-yellow-500/10";
  const Icon = isLong ? TrendingUp : isShort ? TrendingDown : Minus;

  return (
    <div className={`flex items-center justify-between p-3 rounded-lg ${bg}`}>
      <div className="flex items-center gap-3">
        <Icon className={`h-6 w-6 ${color}`} />
        <div>
          <span className={`text-lg font-bold ${color}`}>{signalLabel}</span>
          <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
            analysis.confidence === "HIGH" ? "text-green-500 bg-green-500/10" :
            analysis.confidence === "MEDIUM" ? "text-yellow-500 bg-yellow-500/10" :
            "text-muted-foreground bg-muted"
          }`}>
            {analysis.confidence}
          </span>
        </div>
      </div>
      {analysis.confidence_score != null && (
        <div className="text-right">
          <p className="text-2xl font-bold font-mono">{analysis.confidence_score}</p>
          <p className="text-xs text-muted-foreground">score</p>
        </div>
      )}
    </div>
  );
}
