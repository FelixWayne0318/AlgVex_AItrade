export type Locale = "en" | "zh";

export const translations: Record<Locale, Record<string, string>> = {
  en: {
    // Navigation
    "nav.home": "Home",
    "nav.dashboard": "Dashboard",
    "nav.chart": "Chart",
    "nav.performance": "Performance",
    "nav.copy": "Copy Trading",
    "nav.quality": "AI Quality",
    "nav.about": "About",

    // Hero section
    "hero.title": "AI-Powered",
    "hero.title2": "Crypto Trading",
    "hero.subtitle": "Advanced algorithmic trading powered by DeepSeek AI and multi-agent decision system",
    "hero.cta": "Start Copy Trading",
    "hero.stats": "View Performance",

    // Stats
    "stats.totalReturn": "Total Return",
    "stats.winRate": "Win Rate",
    "stats.maxDrawdown": "Max Drawdown",
    "stats.totalTrades": "Total Trades",
    "stats.activeStatus": "Trading Status",
    "stats.running": "Running",
    "stats.stopped": "Stopped",

    // Performance
    "perf.title": "Performance Analytics",
    "perf.subtitle": "Real-time trading performance from Binance Futures",
    "perf.pnlCurve": "Cumulative P&L",
    "perf.period": "Period",
    "perf.days30": "30 Days",
    "perf.days90": "90 Days",
    "perf.days180": "180 Days",
    "perf.days365": "1 Year",

    // Copy Trading
    "copy.title": "Copy Trading",
    "copy.subtitle": "Follow my trades on these exchanges",
    "copy.howTo": "How to Copy Trade",
    "copy.step1": "Click the exchange link below",
    "copy.step2": "Log in to your exchange account",
    "copy.step3": "Follow the copy trading instructions",
    "copy.disclaimer": "Trading involves risk. Past performance is not indicative of future results.",

    // About
    "about.title": "About AlgVex",
    "about.strategy": "AI Strategy",
    "about.strategyDesc": "Multi-agent system with Bull/Bear debate mechanism for comprehensive market analysis",
    "about.risk": "Risk Management",
    "about.riskDesc": "Automated stop-loss, take-profit, and trailing stop to protect your capital",
    "about.tech": "Technology",
    "about.techDesc": "Built on NautilusTrader framework with DeepSeek AI integration",

    // Footer
    "footer.disclaimer": "Disclaimer: Trading cryptocurrencies involves significant risk. Past performance does not guarantee future results. Trade responsibly.",
    "footer.rights": "All rights reserved",

    // AI Quality
    "quality.title": "AI Quality Analytics",
    "quality.subtitle": "Layer 3 outcome feedback — does AI quality predict trade outcomes?",
    "quality.totalTrades": "Total Trades",
    "quality.overallWinRate": "Overall Win Rate",
    "quality.confidenceCalibration": "Confidence Calibration",
    "quality.confidenceLevel": "Confidence Level",
    "quality.trades": "Trades",
    "quality.winRate": "Win Rate",
    "quality.ev": "Expected Value",
    "quality.calibrationFlags": "Calibration Alerts",
    "quality.noFlags": "Confidence levels properly calibrated",
    "quality.entryTiming": "Entry Timing Effectiveness",
    "quality.enter": "Approved (ENTER)",
    "quality.reject": "Rejected (REJECT)",
    "quality.counterTrend": "Trend vs Counter-Trend",
    "quality.trendFollowing": "Trend-Following",
    "quality.counterTrendLabel": "Counter-Trend",
    "quality.avgRR": "Avg R/R",
    "quality.gradeDistribution": "Grade Distribution",
    "quality.holdCounterfactual": "HOLD Counterfactual Analysis",
    "quality.holdTotal": "Total HOLDs Evaluated",
    "quality.holdAccuracy": "HOLD Accuracy",
    "quality.noData": "Not enough trade data yet",

    // Common
    "common.loading": "Loading...",
    "common.error": "Error loading data",
    "common.lastUpdated": "Last updated",
  },
  zh: {
    // Navigation
    "nav.home": "首页",
    "nav.dashboard": "监控",
    "nav.chart": "图表",
    "nav.performance": "业绩",
    "nav.copy": "跟单",
    "nav.quality": "AI 质量",
    "nav.about": "关于",

    // Hero section
    "hero.title": "AI 驱动",
    "hero.title2": "加密货币交易",
    "hero.subtitle": "基于 DeepSeek AI 和多代理决策系统的先进算法交易",
    "hero.cta": "开始跟单",
    "hero.stats": "查看业绩",

    // Stats
    "stats.totalReturn": "总收益率",
    "stats.winRate": "胜率",
    "stats.maxDrawdown": "最大回撤",
    "stats.totalTrades": "总交易次数",
    "stats.activeStatus": "交易状态",
    "stats.running": "运行中",
    "stats.stopped": "已停止",

    // Performance
    "perf.title": "业绩分析",
    "perf.subtitle": "来自币安合约的实时交易业绩",
    "perf.pnlCurve": "累计盈亏",
    "perf.period": "周期",
    "perf.days30": "30 天",
    "perf.days90": "90 天",
    "perf.days180": "180 天",
    "perf.days365": "1 年",

    // Copy Trading
    "copy.title": "跟单交易",
    "copy.subtitle": "在以下交易所跟随我的交易",
    "copy.howTo": "如何跟单",
    "copy.step1": "点击下方交易所链接",
    "copy.step2": "登录您的交易所账户",
    "copy.step3": "按照跟单说明操作",
    "copy.disclaimer": "交易有风险，过往业绩不代表未来表现。",

    // About
    "about.title": "关于 AlgVex",
    "about.strategy": "AI 策略",
    "about.strategyDesc": "采用多头/空头辩论机制的多代理系统进行全面市场分析",
    "about.risk": "风险管理",
    "about.riskDesc": "自动止损、止盈和移动止损，保护您的资金",
    "about.tech": "技术架构",
    "about.techDesc": "基于 NautilusTrader 框架，集成 DeepSeek AI",

    // Footer
    "footer.disclaimer": "免责声明：加密货币交易涉及重大风险。过往业绩不保证未来收益。请谨慎交易。",
    "footer.rights": "版权所有",

    // AI Quality
    "quality.title": "AI 质量分析",
    "quality.subtitle": "Layer 3 结果反馈 — AI 分析质量是否能预测交易结果？",
    "quality.totalTrades": "总交易数",
    "quality.overallWinRate": "总胜率",
    "quality.confidenceCalibration": "信心校准",
    "quality.confidenceLevel": "信心等级",
    "quality.trades": "交易数",
    "quality.winRate": "胜率",
    "quality.ev": "期望值",
    "quality.calibrationFlags": "校准告警",
    "quality.noFlags": "信心等级校准正常",
    "quality.entryTiming": "入场时机效果",
    "quality.enter": "通过 (ENTER)",
    "quality.reject": "拦截 (REJECT)",
    "quality.counterTrend": "顺势 vs 逆势",
    "quality.trendFollowing": "顺势交易",
    "quality.counterTrendLabel": "逆势交易",
    "quality.avgRR": "平均 R/R",
    "quality.gradeDistribution": "评级分布",
    "quality.holdCounterfactual": "HOLD 反事实分析",
    "quality.holdTotal": "已评估 HOLD 决策",
    "quality.holdAccuracy": "HOLD 准确率",
    "quality.noData": "交易数据不足",

    // Common
    "common.loading": "加载中...",
    "common.error": "数据加载错误",
    "common.lastUpdated": "最后更新",
  },
};

export function useTranslation(locale: Locale) {
  const t = (key: string): string => {
    return translations[locale][key] || key;
  };
  return { t, locale };
}
