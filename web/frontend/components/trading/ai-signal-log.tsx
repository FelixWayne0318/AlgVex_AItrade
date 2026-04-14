'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface AnalysisData {
  signal: string;
  confidence: string;
  reasoning: string;
  key_points?: string[];
  bull_score?: number;
  bear_score?: number;
  risk_assessment?: string;
}

interface SignalLog {
  id: string;
  timestamp: string;
  symbol: string;
  bull_analysis: AnalysisData;
  bear_analysis: AnalysisData;
  judge_decision: AnalysisData;
  final_signal: string;
  confidence: string;
  market_data?: {
    price?: number;
    rsi?: number;
    macd?: number;
    volume_24h?: string;
  };
  entry_timing?: {
    timing_verdict?: string;
    timing_quality?: string;
    counter_trend_risk?: string;
    reason?: string;
  };
}

interface AISignalLogProps {
  signals: SignalLog[];
  maxItems?: number;
}

function SignalBadge({ signal, size = 'md' }: { signal: string; size?: 'sm' | 'md' }) {
  const colors = {
    BUY: 'bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))] border-[hsl(var(--profit))]/30',
    SELL: 'bg-[hsl(var(--loss))]/20 text-[hsl(var(--loss))] border-[hsl(var(--loss))]/30',
    HOLD: 'bg-[hsl(var(--warning))]/20 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/30',
    LONG: 'bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))] border-[hsl(var(--profit))]/30',
    SHORT: 'bg-[hsl(var(--loss))]/20 text-[hsl(var(--loss))] border-[hsl(var(--loss))]/30',
  };

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-1 text-sm',
  };

  return (
    <span className={`font-semibold rounded border ${colors[signal as keyof typeof colors] || 'bg-muted text-muted-foreground'} ${sizeClasses[size]}`}>
      {signal}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const colors = {
    HIGH: 'text-[hsl(var(--profit))]',
    MEDIUM: 'text-[hsl(var(--warning))]',
    LOW: 'text-muted-foreground',
  };

  return (
    <span className={`text-xs font-medium ${colors[confidence as keyof typeof colors] || 'text-muted-foreground'}`}>
      {confidence}
    </span>
  );
}

function AnalysisCard({
  title,
  analysis,
  icon,
  color,
}: {
  title: string;
  analysis: AnalysisData;
  icon: React.ReactNode;
  color: 'profit' | 'loss' | 'primary';
}) {
  const [expanded, setExpanded] = useState(false);
  const [reasoningExpanded, setReasoningExpanded] = useState(false);

  const borderColors = {
    profit: 'border-[hsl(var(--profit))]/30',
    loss: 'border-[hsl(var(--loss))]/30',
    primary: 'border-primary/30',
  };

  return (
    <div className={`rounded-lg border ${borderColors[color]} bg-card/30 p-3`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-medium text-sm">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          <SignalBadge signal={analysis.signal} size="sm" />
          <ConfidenceBadge confidence={analysis.confidence} />
        </div>
      </div>

      <p
        className={`text-xs text-muted-foreground cursor-pointer hover:text-foreground/70 transition-colors ${reasoningExpanded || expanded ? '' : 'line-clamp-2'}`}
        onClick={() => setReasoningExpanded(!reasoningExpanded)}
      >
        {analysis.reasoning}
      </p>

      {analysis.key_points && analysis.key_points.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-primary mt-2 hover:underline"
          >
            {expanded ? 'Hide details' : `View ${analysis.key_points.length} key points`}
          </button>

          <AnimatePresence>
            {expanded && (
              <motion.ul
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="mt-2 space-y-1 overflow-hidden"
              >
                {analysis.key_points.map((point, i) => (
                  <li key={i} className="text-xs text-muted-foreground flex items-start gap-1">
                    <span className="text-primary">•</span>
                    {point}
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </>
      )}

      {/* Judge specific fields */}
      {analysis.bull_score !== undefined && (
        <div className="mt-2 pt-2 border-t border-border/50 flex items-center gap-4 text-xs">
          <span className="text-[hsl(var(--profit))]">Bull: {analysis.bull_score}</span>
          <span className="text-[hsl(var(--loss))]">Bear: {analysis.bear_score}</span>
        </div>
      )}
    </div>
  );
}

export function AISignalLog({ signals, maxItems = 5 }: AISignalLogProps) {
  const [expandedId, setExpandedId] = useState<string | null>(signals[0]?.id || null);
  const [showAll, setShowAll] = useState(false);

  const displaySignals = showAll ? signals : signals.slice(0, maxItems);

  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <svg className="w-12 h-12 mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <p className="text-sm">No AI signals recorded</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {displaySignals.map((signal, index) => (
        <motion.div
          key={signal.id}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.05 }}
          className={`rounded-xl border transition-all ${
            expandedId === signal.id
              ? 'bg-card border-primary/30'
              : 'bg-card/50 border-border/50 hover:border-border'
          }`}
        >
          {/* Header */}
          <div
            className="p-3 sm:p-4 cursor-pointer"
            onClick={() => setExpandedId(expandedId === signal.id ? null : signal.id)}
          >
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
                <SignalBadge signal={signal.final_signal} />
                <span className="font-medium">{signal.symbol}</span>
                <ConfidenceBadge confidence={signal.confidence} />
                {signal.entry_timing?.timing_verdict && (
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    signal.entry_timing.timing_verdict === "ENTER"
                      ? "bg-[hsl(var(--profit))]/10 text-[hsl(var(--profit))]"
                      : "bg-[hsl(var(--loss))]/10 text-[hsl(var(--loss))]"
                  }`}>
                    {signal.entry_timing.timing_verdict}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2 sm:gap-3 text-xs text-muted-foreground">
                <span className="truncate">
                  {new Date(signal.timestamp).toLocaleString()}
                </span>
                <svg
                  className={`w-4 h-4 flex-shrink-0 transition-transform ${
                    expandedId === signal.id ? 'rotate-180' : ''
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </div>

            {/* Market data summary */}
            {signal.market_data && expandedId !== signal.id && (
              <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
                {signal.market_data.price && (
                  <span>Price: ${signal.market_data.price.toLocaleString()}</span>
                )}
                {signal.market_data.rsi && <span>RSI: {signal.market_data.rsi.toFixed(1)}</span>}
              </div>
            )}
          </div>

          {/* Expanded content */}
          <AnimatePresence>
            {expandedId === signal.id && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="px-4 pb-4 space-y-3">
                  {/* Market data */}
                  {signal.market_data && (
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 rounded-lg bg-muted/30">
                      {signal.market_data.price && (
                        <div>
                          <span className="text-xs text-muted-foreground">Price</span>
                          <p className="font-mono text-sm">${signal.market_data.price.toLocaleString()}</p>
                        </div>
                      )}
                      {signal.market_data.rsi && (
                        <div>
                          <span className="text-xs text-muted-foreground">RSI</span>
                          <p className="font-mono text-sm">{signal.market_data.rsi.toFixed(1)}</p>
                        </div>
                      )}
                      {signal.market_data.macd && (
                        <div>
                          <span className="text-xs text-muted-foreground">MACD</span>
                          <p className="font-mono text-sm">{signal.market_data.macd.toFixed(1)}</p>
                        </div>
                      )}
                      {signal.market_data.volume_24h && (
                        <div>
                          <span className="text-xs text-muted-foreground">Volume 24h</span>
                          <p className="font-mono text-sm">{signal.market_data.volume_24h}</p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Analysis cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <AnalysisCard
                      title="Bull Analyst"
                      analysis={signal.bull_analysis}
                      color="profit"
                      icon={
                        <svg className="w-4 h-4 text-[hsl(var(--profit))]" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" clipRule="evenodd" />
                        </svg>
                      }
                    />
                    <AnalysisCard
                      title="Bear Analyst"
                      analysis={signal.bear_analysis}
                      color="loss"
                      icon={
                        <svg className="w-4 h-4 text-[hsl(var(--loss))]" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M12 13a1 1 0 100 2h5a1 1 0 001-1V9a1 1 0 10-2 0v2.586l-4.293-4.293a1 1 0 00-1.414 0L8 9.586 3.707 5.293a1 1 0 00-1.414 1.414l5 5a1 1 0 001.414 0L11 9.414 14.586 13H12z" clipRule="evenodd" />
                        </svg>
                      }
                    />
                    <AnalysisCard
                      title="Judge Decision"
                      analysis={signal.judge_decision}
                      color="primary"
                      icon={
                        <svg className="w-4 h-4 text-primary" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z" />
                        </svg>
                      }
                    />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      ))}
      {!showAll && signals.length > maxItems && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full py-2 text-xs text-primary hover:text-primary/80 hover:underline transition-colors"
        >
          Show all {signals.length} signals
        </button>
      )}
      {showAll && signals.length > maxItems && (
        <button
          onClick={() => setShowAll(false)}
          className="w-full py-2 text-xs text-muted-foreground hover:text-foreground/70 hover:underline transition-colors"
        >
          Show less
        </button>
      )}
    </div>
  );
}
