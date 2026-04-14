import useSWR from 'swr';

interface ConfidenceBucket {
  n: number;
  wins: number;
  win_rate: number | null;
}

interface CounterTrendStats {
  n: number;
  wins?: number;
  win_rate: number | null;
  avg_rr: number | null;
}

interface EntryTimingBucket {
  n: number;
  wins: number;
  win_rate: number | null;
}

interface ConfidenceEV {
  ev: number | null;
  avg_win_rr: number | null;
  avg_loss_rr: number | null;
}

export interface QualityAnalysisSummary {
  total_trades: number;
  overall_win_rate: number;
  confidence_calibration: {
    HIGH: ConfidenceBucket;
    MEDIUM: ConfidenceBucket;
    LOW: ConfidenceBucket;
    UNKNOWN?: ConfidenceBucket;
  };
  calibration_flags: string[];
  confidence_ev: {
    HIGH?: ConfidenceEV;
    MEDIUM?: ConfidenceEV;
    LOW?: ConfidenceEV;
  };
  counter_trend: {
    trend_following: CounterTrendStats;
    counter_trend: CounterTrendStats;
  };
  grade_distribution: Record<string, number>;
  entry_timing: {
    ENTER: EntryTimingBucket;
    REJECT: EntryTimingBucket;
    total_with_verdict: number;
  };
  status: string;
  generated_at: string;
}

/**
 * Hook to fetch Layer 3 quality analysis summary
 */
export function useQualityAnalysisSummary() {
  const { data, error, mutate } = useSWR<QualityAnalysisSummary>(
    '/api/public/quality-analysis/summary',
    { refreshInterval: 120000 }
  );

  return {
    analysis: data,
    isLoading: !error && !data,
    isError: error,
    mutate,
  };
}

/**
 * Hook to fetch full Layer 3 analysis (all 10 analyses)
 */
export function useFullQualityAnalysis() {
  const { data, error, mutate } = useSWR(
    '/api/public/quality-analysis/full',
    { refreshInterval: 120000 }
  );

  return {
    report: data,
    isLoading: !error && !data,
    isError: error,
    mutate,
  };
}
