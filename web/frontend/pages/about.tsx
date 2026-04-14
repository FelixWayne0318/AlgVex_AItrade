"use client";

import { useRouter } from "next/router";
import Head from "next/head";
import { Bot, Shield, Zap, LineChart, Brain, Server } from "lucide-react";

import { Header } from "@/components/layout/header";
import { Footer } from "@/components/layout/footer";
import { Card, CardContent } from "@/components/ui/card";
import { useTranslation, type Locale } from "@/lib/i18n";

const features = [
  {
    icon: Brain,
    titleKey: "about.strategy",
    descKey: "about.strategyDesc",
  },
  {
    icon: Shield,
    titleKey: "about.risk",
    descKey: "about.riskDesc",
  },
  {
    icon: Zap,
    titleKey: "about.tech",
    descKey: "about.techDesc",
  },
];

const techStack = [
  {
    name: "NautilusTrader",
    description: "High-performance algorithmic trading platform (Cython indicators)",
    version: "1.224.0",
  },
  {
    name: "DeepSeek AI",
    description: "V3.2 Thinking mode — deep chain-of-thought reasoning for market analysis",
    version: "deepseek-chat (Thinking v32.0)",
  },
  {
    name: "Multi-Agent System",
    description: "5+1 agent pipeline: Bull/Bear debate → Judge → Entry Timing → Risk Manager + Reflection",
    version: "Feature-Driven v27.0+",
  },
  {
    name: "124 Typed Features",
    description: "Structured feature extraction from 13 data sources with dimensional scoring",
    version: "v28.0 Scores",
  },
  {
    name: "AI Quality Auditor",
    description: "6-dimensional verification: data coverage, citations, MTF compliance, production quality",
    version: "v29.0+",
  },
  {
    name: "Binance Futures",
    description: "Primary exchange for BTCUSDT perpetual futures with native trailing stops",
    version: "Futures API",
  },
  {
    name: "Python",
    description: "Core language for strategy and data processing",
    version: "3.12+",
  },
  {
    name: "Next.js + FastAPI",
    description: "Web dashboard frontend and backend",
    version: "14 / 0.115",
  },
];

export default function AboutPage() {
  const router = useRouter();
  const locale = (router.locale || "en") as Locale;
  const { t } = useTranslation(locale);

  return (
    <>
      <Head>
        <title>About - AlgVex</title>
        <meta
          name="description"
          content="Learn about AlgVex AI-powered trading system"
        />
      </Head>

      <div className="min-h-screen gradient-bg">
        <Header locale={locale} t={t} />

        {/* pt-24 accounts for floating rounded header with extra spacing */}
        <main className="pt-24 pb-16 px-4">
          <div className="container mx-auto max-w-4xl">
            {/* Page Header */}
            <div className="text-center mb-16">
              <h1 className="text-4xl font-bold mb-4">{t("about.title")}</h1>
              <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
                An AI-powered algorithmic trading system built for consistent,
                data-driven decision making in cryptocurrency markets.
              </p>
            </div>

            {/* Core Features */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
              {features.map((feature) => {
                const Icon = feature.icon;
                return (
                  <Card
                    key={feature.titleKey}
                    className="border-border/50 text-center"
                  >
                    <CardContent className="p-8">
                      <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-primary/10 flex items-center justify-center">
                        <Icon className="h-8 w-8 text-primary" />
                      </div>
                      <h3 className="text-xl font-semibold mb-3">
                        {t(feature.titleKey)}
                      </h3>
                      <p className="text-muted-foreground">
                        {t(feature.descKey)}
                      </p>
                    </CardContent>
                  </Card>
                );
              })}
            </div>

            {/* How It Works */}
            <Card className="border-border/50 mb-16">
              <CardContent className="p-8">
                <h2 className="text-2xl font-bold mb-6 text-center">
                  How It Works
                </h2>
                <div className="space-y-6">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0 font-semibold">
                      1
                    </div>
                    <div>
                      <h4 className="font-semibold mb-1">13-Source Data Aggregation</h4>
                      <p className="text-muted-foreground">
                        Every 20 minutes: technical indicators (RSI, MACD, ATR, ADX, OBV)
                        across 3 timeframes (1D/4H/30M), order flow (CVD, taker ratios),
                        derivatives (OI, liquidations, funding rate), orderbook depth,
                        and sentiment data — 124 typed features extracted automatically.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0 font-semibold">
                      2
                    </div>
                    <div>
                      <h4 className="font-semibold mb-1">5+1 Agent AI Pipeline</h4>
                      <p className="text-muted-foreground">
                        DeepSeek V3.2 with Thinking mode powers a structured debate:
                        Bull and Bear analysts argue 2 rounds, a Judge decides direction,
                        Entry Timing Agent validates the entry window, and Risk Manager
                        sizes the position. Post-close reflections feed back as lessons.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0 font-semibold">
                      3
                    </div>
                    <div>
                      <h4 className="font-semibold mb-1">Mechanical R/R Guarantee</h4>
                      <p className="text-muted-foreground">
                        SL/TP are mechanically constructed by ATR to guarantee R/R ≥ 2.0:1.
                        Counter-trend trades require R/R ≥ 1.95:1. Entry via LIMIT orders
                        at validated prices — R/R never drops below verification.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0 font-semibold">
                      4
                    </div>
                    <div>
                      <h4 className="font-semibold mb-1">Multi-Layer Safety</h4>
                      <p className="text-muted-foreground">
                        Per-layer independent SL/TP with Binance native trailing stops.
                        Emergency SL fallback with automatic retry. Liquidation buffer
                        monitoring. FR exhaustion detection breaks directional loops.
                        Trade memory with recency-weighted learning across all agents.
                      </p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Tech Stack */}
            <Card className="border-border/50">
              <CardContent className="p-8">
                <h2 className="text-2xl font-bold mb-6 text-center">
                  Technology Stack
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {techStack.map((tech) => (
                    <div
                      key={tech.name}
                      className="p-4 rounded-lg bg-muted/30 border border-border/50"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold">{tech.name}</h4>
                        <span className="text-xs text-primary bg-primary/10 px-2 py-1 rounded">
                          {tech.version}
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {tech.description}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </main>

        <Footer t={t} />
      </div>
    </>
  );
}
