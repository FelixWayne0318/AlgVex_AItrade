"use client";

import { useState } from "react";
import Head from "next/head";
import Link from "next/link";
import useSWR from "swr";
import { useRouter } from "next/router";
import { TradingViewWidget } from "@/components/charts/tradingview-widget";
import { Header } from "@/components/layout/header";
import { useTranslation, type Locale } from "@/lib/i18n";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  Clock,
  DollarSign,
  Brain,
  Target,
  Shield,
  Zap,
  MessageSquare,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GradePieChart } from "@/components/trade-evaluation/GradePieChart";

const formatNumber = (num: number, decimals = 2) => {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
};

const formatTime = (isoString: string) => {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);

  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return date.toLocaleDateString();
};

/** Expandable analysis section — click header to toggle between 3-line preview and full text. */
function ExpandableSection({
  icon: Icon,
  label,
  text,
  colorClass,
  bgClass,
  borderClass,
}: {
  icon: React.ElementType;
  label: string;
  text: string;
  colorClass: string;
  bgClass: string;
  borderClass: string;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`p-2 rounded-lg ${bgClass} border ${borderClass}`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center justify-between w-full gap-2 mb-1 cursor-pointer"
      >
        <span className="flex items-center gap-2">
          <Icon className={`h-3 w-3 ${colorClass}`} />
          <span className={`text-xs font-medium ${colorClass}`}>{label}</span>
        </span>
        <ChevronDown
          className={`h-3 w-3 text-muted-foreground transition-transform duration-200 ${
            expanded ? "rotate-180" : ""
          }`}
        />
      </button>
      <p
        className={`text-xs text-muted-foreground whitespace-pre-wrap ${
          expanded ? "" : "line-clamp-3"
        }`}
      >
        {text}
      </p>
    </div>
  );
}

function BullBearAnalysis({ aiAnalysis }: { aiAnalysis: any }) {
  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          Bull vs Bear Analysis
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ExpandableSection
          icon={TrendingUp}
          label="Bull Case"
          text={aiAnalysis?.bull_analysis || "Loading analysis..."}
          colorClass="text-[hsl(var(--profit))]"
          bgClass="bg-[hsl(var(--profit))]/5"
          borderClass="border-[hsl(var(--profit))]/20"
        />
        <ExpandableSection
          icon={TrendingDown}
          label="Bear Case"
          text={aiAnalysis?.bear_analysis || "Loading analysis..."}
          colorClass="text-[hsl(var(--loss))]"
          bgClass="bg-[hsl(var(--loss))]/5"
          borderClass="border-[hsl(var(--loss))]/20"
        />
        <ExpandableSection
          icon={Shield}
          label="Judge Decision"
          text={aiAnalysis?.judge_reasoning || "Awaiting analysis..."}
          colorClass="text-primary"
          bgClass="bg-primary/5"
          borderClass="border-primary/20"
        />
      </CardContent>
    </Card>
  );
}

export default function ChartPage() {
  const router = useRouter();
  const locale = (router.locale || "en") as Locale;
  const { t } = useTranslation(locale);

  const [interval, setInterval] = useState("15");
  const [symbol, setSymbol] = useState("BINANCE:BTCUSDT.P");

  // Fetch real-time data
  const { data: ticker } = useSWR("/api/trading/ticker/BTCUSDT", {
    refreshInterval: 5000,
  });

  const { data: markPrice } = useSWR("/api/trading/mark-price/BTCUSDT", {
    refreshInterval: 5000,
  });

  const { data: longShortRatio } = useSWR(
    "/api/trading/long-short-ratio/BTCUSDT",
    { refreshInterval: 60000 }
  );

  // AI-specific data
  const { data: aiAnalysis } = useSWR("/api/public/ai-analysis", {
    refreshInterval: 30000,
  });

  const { data: signalHistory } = useSWR("/api/public/signal-history?limit=5", {
    refreshInterval: 30000,
  });

  const intervals = [
    { value: "1", label: "1m" },
    { value: "5", label: "5m" },
    { value: "15", label: "15m" },
    { value: "60", label: "1H" },
    { value: "240", label: "4H" },
    { value: "D", label: "1D" },
  ];

  const symbols = [
    { value: "BINANCE:BTCUSDT.P", label: "BTC/USDT" },
    { value: "BINANCE:ETHUSDT.P", label: "ETH/USDT" },
    { value: "BINANCE:SOLUSDT.P", label: "SOL/USDT" },
  ];

  const priceChange = ticker?.price_change_percent || 0;
  const isPositive = priceChange >= 0;

  // Signal colors
  const getSignalColor = (signal: string) => {
    if (signal === "BUY" || signal === "LONG") return "text-[hsl(var(--profit))]";
    if (signal === "SELL" || signal === "SHORT") return "text-[hsl(var(--loss))]";
    return "text-yellow-500";
  };

  const getSignalBg = (signal: string) => {
    if (signal === "BUY" || signal === "LONG") return "bg-[hsl(var(--profit))]/10 border-[hsl(var(--profit))]/30";
    if (signal === "SELL" || signal === "SHORT") return "bg-[hsl(var(--loss))]/10 border-[hsl(var(--loss))]/30";
    return "bg-yellow-500/10 border-yellow-500/30";
  };

  const getConfidenceColor = (confidence: string) => {
    if (confidence === "HIGH") return "text-[hsl(var(--profit))]";
    if (confidence === "LOW") return "text-[hsl(var(--loss))]";
    return "text-yellow-500";
  };

  return (
    <>
      <Head>
        <title>AI Trading Chart - AlgVex</title>
        <meta name="description" content="AI-powered cryptocurrency trading analysis" />
      </Head>

      <div className="min-h-screen gradient-bg">
        <Header locale={locale} t={t} />

        {/* pt-24 accounts for floating rounded header with extra spacing */}
        <main className="container mx-auto px-4 pt-24 pb-6">
          {/* Sub-header with symbol selector */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <span className="font-semibold text-lg">AI Trading View</span>
            </div>

            {/* Symbol selector */}
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="px-3 py-2 rounded-lg bg-muted border border-border text-sm"
            >
              {symbols.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          {/* Price Stats - Simplified */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <Card className="border-border/50">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <DollarSign className="h-4 w-4 text-primary" />
                  <span className="text-xs text-muted-foreground">Price</span>
                </div>
                <p className="text-xl font-bold font-mono">
                  ${ticker ? formatNumber(ticker.price) : "---"}
                </p>
              </CardContent>
            </Card>

            <Card className="border-border/50">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  {isPositive ? (
                    <TrendingUp className="h-4 w-4 text-[hsl(var(--profit))]" />
                  ) : (
                    <TrendingDown className="h-4 w-4 text-[hsl(var(--loss))]" />
                  )}
                  <span className="text-xs text-muted-foreground">24h Change</span>
                </div>
                <p className={`text-xl font-bold font-mono ${isPositive ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}>
                  {isPositive ? "+" : ""}{formatNumber(priceChange)}%
                </p>
              </CardContent>
            </Card>

            <Card className="border-border/50">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  <span className="text-xs text-muted-foreground">24h Volume</span>
                </div>
                <p className="text-xl font-bold font-mono">
                  {ticker ? `$${formatNumber(ticker.quote_volume_24h / 1e9, 1)}B` : "---"}
                </p>
              </CardContent>
            </Card>

            <Card className="border-border/50">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Activity className="h-4 w-4 text-yellow-500" />
                  <span className="text-xs text-muted-foreground">Funding</span>
                </div>
                <p className={`text-xl font-bold font-mono ${markPrice?.funding_rate >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}>
                  {markPrice ? `${(markPrice.funding_rate * 100).toFixed(4)}%` : "---"}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Interval Selector */}
          <div className="flex gap-2 mb-4">
            {intervals.map((i) => (
              <Button
                key={i.value}
                variant={interval === i.value ? "default" : "outline"}
                size="sm"
                onClick={() => setInterval(i.value)}
                className={interval !== i.value ? "border-border/50" : ""}
              >
                {i.label}
              </Button>
            ))}
          </div>

          {/* Main Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* Chart */}
            <div className="lg:col-span-3">
              <Card className="border-border/50 overflow-hidden">
                <CardContent className="p-0">
                  <div style={{ height: 600 }}>
                    <TradingViewWidget
                      symbol={symbol}
                      interval={interval}
                      theme="dark"
                      height={600}
                      autosize={false}
                      showToolbar={true}
                      showDetails={true}
                    />
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* AI Analysis Sidebar */}
            <div className="space-y-4">
              {/* AI Signal Panel */}
              <Card className={`border ${getSignalBg(aiAnalysis?.signal || "HOLD")}`}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Brain className="h-4 w-4 text-primary" />
                    AI Signal
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className={`text-2xl font-bold ${getSignalColor(aiAnalysis?.signal || "HOLD")}`}>
                      {aiAnalysis?.signal || "HOLD"}
                    </span>
                    <span className={`text-sm font-medium px-2 py-1 rounded ${getConfidenceColor(aiAnalysis?.confidence || "MEDIUM")} bg-current/10`}>
                      {aiAnalysis?.confidence || "MEDIUM"}
                    </span>
                  </div>

                  {/* Confidence Bar */}
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">Confidence</span>
                      <span className="font-mono">{aiAnalysis?.confidence_score || 50}%</span>
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full ${aiAnalysis?.confidence_score >= 70 ? 'bg-[hsl(var(--profit))]' : aiAnalysis?.confidence_score >= 40 ? 'bg-yellow-500' : 'bg-[hsl(var(--loss))]'}`}
                        style={{ width: `${aiAnalysis?.confidence_score || 50}%` }}
                      />
                    </div>
                  </div>

                  {/* Entry/SL/TP if available */}
                  {aiAnalysis?.entry_price && (
                    <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border/50">
                      <div className="text-center">
                        <p className="text-[10px] text-muted-foreground">Entry</p>
                        <p className="text-xs font-mono">${formatNumber(aiAnalysis.entry_price)}</p>
                      </div>
                      <div className="text-center">
                        <p className="text-[10px] text-muted-foreground">SL</p>
                        <p className="text-xs font-mono text-[hsl(var(--loss))]">
                          ${aiAnalysis.stop_loss ? formatNumber(aiAnalysis.stop_loss) : "--"}
                        </p>
                      </div>
                      <div className="text-center">
                        <p className="text-[10px] text-muted-foreground">TP</p>
                        <p className="text-xs font-mono text-[hsl(var(--profit))]">
                          ${aiAnalysis.take_profit ? formatNumber(aiAnalysis.take_profit) : "--"}
                        </p>
                      </div>
                    </div>
                  )}

                  <p className="text-xs text-muted-foreground">
                    Updated {aiAnalysis?.timestamp ? formatTime(aiAnalysis.timestamp) : "--"}
                  </p>
                </CardContent>
              </Card>

              {/* Bull vs Bear Debate */}
              <BullBearAnalysis aiAnalysis={aiAnalysis} />

              {/* Confidence Breakdown */}
              <Card className="border-border/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Target className="h-4 w-4 text-primary" />
                    Analysis Scores
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">Technical</span>
                      <span className="font-mono">{aiAnalysis?.technical_score || 50}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500"
                        style={{ width: `${aiAnalysis?.technical_score || 50}%` }}
                      />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">Sentiment</span>
                      <span className="font-mono">{aiAnalysis?.sentiment_score || 50}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-500"
                        style={{ width: `${aiAnalysis?.sentiment_score || 50}%` }}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Trade Quality */}
              <GradePieChart limit={5} days={30} />

              {/* Recent Signals History */}
              <Card className="border-border/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Clock className="h-4 w-4 text-primary" />
                    Recent Signals
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {signalHistory?.signals?.slice(0, 5).map((signal: any, idx: number) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2 rounded-lg bg-muted/30"
                      >
                        <div className="flex items-center gap-2">
                          <Zap className={`h-3 w-3 ${getSignalColor(signal.signal)}`} />
                          <span className={`text-xs font-medium ${getSignalColor(signal.signal)}`}>
                            {signal.signal}
                          </span>
                          <span className={`text-[10px] ${getConfidenceColor(signal.confidence)}`}>
                            {signal.confidence}
                          </span>
                        </div>
                        <div className="text-right">
                          {signal.result !== null && signal.result !== undefined && (
                            <span className={`text-xs font-mono ${signal.result >= 0 ? 'text-[hsl(var(--profit))]' : 'text-[hsl(var(--loss))]'}`}>
                              {signal.result >= 0 ? '+' : ''}{signal.result}%
                            </span>
                          )}
                          <p className="text-[10px] text-muted-foreground">
                            {formatTime(signal.timestamp)}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Mark Price Info - Kept */}
              <Card className="border-border/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Derivatives Info</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Mark Price</span>
                    <span className="font-mono">
                      ${markPrice ? formatNumber(markPrice.mark_price) : "---"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Index Price</span>
                    <span className="font-mono">
                      ${markPrice ? formatNumber(markPrice.index_price) : "---"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Next Funding</span>
                    <span className="font-mono text-xs">
                      {markPrice?.next_funding_time
                        ? new Date(markPrice.next_funding_time).toLocaleTimeString()
                        : "---"}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </main>

        {/* Footer */}
        <footer className="border-t border-border/50 mt-12">
          <div className="container mx-auto px-4 py-6">
            <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
              <p>AI-powered analysis • Real-time data from Binance Futures</p>
              <div className="flex items-center gap-4">
                <Link href="/" className="hover:text-foreground transition-colors">
                  Home
                </Link>
                <Link href="/performance" className="hover:text-foreground transition-colors">
                  Performance
                </Link>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}
