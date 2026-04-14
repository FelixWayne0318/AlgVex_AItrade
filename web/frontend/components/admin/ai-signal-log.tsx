"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, TrendingUp, TrendingDown, Minus, Clock } from "lucide-react";
import { formatTime } from "@/lib/utils";

interface AISignal {
  id: string;
  time: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  reason?: string;
  symbol?: string;
}

interface AISignalLogProps {
  signals?: AISignal[];
}

export function AISignalLog({ signals }: AISignalLogProps) {
  const [expandedReasons, setExpandedReasons] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState(false);
  const displaySignals = signals?.length ? signals : [];

  const getSignalConfig = (signal: string) => {
    switch (signal) {
      case "BUY":
        return {
          icon: TrendingUp,
          color: "text-green-500",
          bg: "bg-green-500/10",
          border: "border-green-500/30",
        };
      case "SELL":
        return {
          icon: TrendingDown,
          color: "text-red-500",
          bg: "bg-red-500/10",
          border: "border-red-500/30",
        };
      default:
        return {
          icon: Minus,
          color: "text-yellow-500",
          bg: "bg-yellow-500/10",
          border: "border-yellow-500/30",
        };
    }
  };

  const getConfidenceColor = (confidence: string) => {
    switch (confidence) {
      case "HIGH":
        return "text-green-500 bg-green-500/10";
      case "MEDIUM":
        return "text-yellow-500 bg-yellow-500/10";
      default:
        return "text-muted-foreground bg-muted";
    }
  };

  return (
    <div className={`space-y-3 ${expanded ? '' : 'max-h-80'} overflow-y-auto pr-2`}>
      <AnimatePresence mode="popLayout">
        {displaySignals.map((signal, index) => {
          const config = getSignalConfig(signal.signal);
          const Icon = config.icon;

          return (
            <motion.div
              key={signal.id}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              transition={{ duration: 0.2, delay: index * 0.05 }}
              className={`p-3 rounded-lg ${config.bg} border ${config.border}`}
            >
              <div className="flex items-start gap-3">
                {/* Icon */}
                <div className={`p-2 rounded-lg bg-background/50`}>
                  <Brain className={`h-4 w-4 ${config.color}`} />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-1.5">
                      <Icon className={`h-4 w-4 ${config.color}`} />
                      <span className={`font-medium ${config.color}`}>{signal.signal}</span>
                    </div>
                    {signal.symbol && (
                      <span className="text-xs text-muted-foreground">{signal.symbol}</span>
                    )}
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded ${getConfidenceColor(
                        signal.confidence
                      )}`}
                    >
                      {signal.confidence}
                    </span>
                  </div>
                  {signal.reason && (
                    <p
                      className={`text-xs text-muted-foreground mt-1 cursor-pointer hover:text-foreground/70 transition-colors ${expandedReasons.has(signal.id) ? '' : 'line-clamp-2'}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedReasons(prev => {
                          const next = new Set(prev);
                          next.has(signal.id) ? next.delete(signal.id) : next.add(signal.id);
                          return next;
                        });
                      }}
                    >
                      {signal.reason}
                    </p>
                  )}
                </div>

                {/* Time */}
                <div className="flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap">
                  <Clock className="h-3 w-3" />
                  {formatTime(signal.time)}
                </div>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>

      {!displaySignals.length && (
        <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <Brain className="h-8 w-8 mb-3 opacity-40" />
          <p className="text-sm font-medium">No AI signals yet</p>
          <p className="text-xs mt-1">Signals will appear after the bot completes an analysis cycle</p>
        </div>
      )}
      {displaySignals.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full py-2 text-xs text-primary hover:text-primary/80 hover:underline transition-colors"
        >
          {expanded ? 'Collapse' : `Expand all ${displaySignals.length} signals`}
        </button>
      )}
    </div>
  );
}


