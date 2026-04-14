"""
Prompt Constants and Signal Analysis Utilities

Contains the INDICATOR_DEFINITIONS knowledge manual, SIGNAL_CONFIDENCE_MATRIX,
and helper functions for regime-aware signal annotation.

These are used by MultiAgentAnalyzer to construct AI prompts.
"""

# =============================================================================
# v18.0 Constants — Reflection System Reform
# =============================================================================

# P2: Recency scoring in _score_memory()
RECENCY_WEIGHT = 1.5
RECENCY_HALF_LIFE_DAYS = 14

# P1: Extended Reflection System
EXTENDED_REFLECTION_INTERVAL = 5
EXTENDED_REFLECTION_MAX_CHARS = 200
EXTENDED_REFLECTIONS_FILE = "data/extended_reflections.json"
EXTENDED_REFLECTIONS_MAX_COUNT = 100


# =============================================================================
# INDICATOR_DEFINITIONS — Regime-Aware Trading Knowledge Manual
#
# Evolution:
# - v3.12: Basic calculation definitions (TradingAgents style)
# - v3.15: Added "entry at current market price" (removed in v3.17+)
# - v3.17: Replaced distance-based rules with R/R-driven entry criteria
# - v3.25: Complete rewrite — regime-aware usage guide with failure modes
# - v3.26: Risk Manager gets full manual + removed hard rules for AI autonomy
# - v4.0: Added 9 sections (Liquidations, Top Traders, K-Line, Pressure Gradient,
#          Depth Distribution, Trade Count, Buy Ratio Range, Coinalyze L/S, 24h Stats)
#
# Philosophy (nof1 Alpha Arena / TradingAgents):
# - Encode complete trading knowledge in the system prompt
# - Teach AI regime detection, indicator interpretation, and failure modes
# - Let AI synthesize all data and make independent decisions
# - No hard thresholds that override AI judgment
# =============================================================================
INDICATOR_DEFINITIONS = """
====================================================================
INDICATOR REFERENCE (v4.0)
====================================================================
This reference supplements your existing knowledge with regime-specific
interpretation rules, failure statistics, and specialized frameworks.
Apply this knowledge to the market data provided alongside it.

STEP 1: DETERMINE MARKET REGIME (this changes how all indicators read)
  ADX > 25 + clear price direction    → TRENDING
  ADX < 20 + price oscillating        → RANGING
  ADX < 20 + BB Width at lows         → SQUEEZE (pre-breakout)
  ADX > 25 + BB Width expanding fast  → VOLATILE TREND

REGIME BEHAVIOR:
  TRENDING:  Trend-following has higher win rates. Counter-trend has high failure
             rates. S/R levels frequently break.
  RANGING:   Mean-reversion most reliable. S/R bounces work.
  SQUEEZE:   Big move imminent, direction unknown. ~50% wrong-side risk pre-breakout.
  VOLATILE:  Trend-following works, wider stops needed.
The #1 source of retail losses: applying ranging logic in trending markets.

====================================================================
INDICATORS (each section: TRENDING use → RANGING use → failure mode)
====================================================================

--- RSI (Cardwell Range Shifts) ---
TRENDING: Shifted ranges, not traditional 30/70.
  Uptrend 40-80: pullbacks to 40-50 = with-trend entries. 80 = strong momentum.
  Downtrend 20-60: rallies to 50-60 = with-trend entries. 20 = strong momentum.
RANGING: Traditional 30/70 work as overbought/oversold.
⚠️ Buying RSI <30 in downtrend = most common retail mistake (RSI stays oversold).
   Cardwell: bullish divergences can CONFIRM downtrends, not reverse them.

--- ADX / DI+ / DI- ---
TRENDING: ADX 25-50 = strong trend. 50+ = very strong. DI+>DI- = up, DI->DI+ = down.
RANGING: ADX 0-20. ADX 75+ = potential exhaustion.
ADX TRAJECTORY (from 1D/4H time series):
  ADX rising = trend strengthening, with-trend entries are higher quality.
  ADX falling from peak = trend weakening, precedes price reversal. Critical early signal.
  DI+ and DI- converging (spread narrowing) = direction losing conviction.
  DI+ and DI- diverging (spread widening) = direction gaining conviction.
⚠️ ADX is a trend-confirming indicator — confirms direction after the fact. Brief spikes in choppy markets = false signals.

--- MACD ---
TRENDING: Crossovers = continuation signals. Zero-line cross = major shift.
  Histogram growth = momentum building. Histogram shrinking = weakening.
RANGING: Whipsaws repeatedly — 74-97% false positive rate in backtests.
⚠️ MACD alone has extremely poor reliability — requires confirmation.

--- BOLLINGER BANDS ---
TRENDING: Price "walks the band" — upper band touch in uptrend is NORMAL.
  Shorting upper band in uptrend = most common BB error. Middle = dynamic S/R.
RANGING: Mean-reversion at bands (upper = overbought, lower = oversold).
SQUEEZE: Low BB Width = big move imminent, direction unknown.
⚠️ Head fakes during squeezes are common.

--- SMA ---
TRENDING: Trend filter — Price > SMA200 = uptrend bias, < SMA200 = downtrend.
  SMA 20/50 = dynamic pullback levels. Golden/Death Cross = long-term shifts.
RANGING: Whipsaws around SMA.
⚠️ 35% false signal rate on crosses. Use as filter, not timing signal.

--- VOLUME ---
TRENDING: Rising price + rising volume = genuine. Falling volume = suspect move.
RANGING: Volume spikes at S/R = potential breakout.
⚠️ Low-volume moves are unreliable regardless of direction.

--- CVD (Cumulative Volume Delta) ---
TRENDING: CVD aligns with price = confirms move.
  CVD diverges: price up + CVD falling = hidden selling; price down + CVD rising = accumulation.
RANGING: Absorption — positive CVD + flat price = large passive seller absorbing aggressive buys.
  Inverse absorption — negative CVD + flat price = large passive buyer absorbing aggressive sells.
OI×CVD (who is opening/closing): OI↑+CVD↑=longs opening, OI↑+CVD↓=shorts opening,
  OI↓+CVD↓=longs closing, OI↓+CVD↑=shorts closing. Pre-computed in derivatives section.
⚠️ CVD from candle data is approximate. Noisy during low-volume periods.

--- FUNDING RATE ---
Daily holding cost = rate × 3 settlements (every 8h).
  |Rate| < 0.03%: Normal (0.01-0.03% in bull markets is standard, not bearish).
  > +0.05%: Crowded longs. > +0.10%: Extreme, reversal probability rises.
  < -0.03%: Bearish pressure. < -0.10%: Extreme panic, bounce probability rises.
  Predicted vs settled difference > 0.01% = notable shift in market sentiment.
  Predicted vs settled sign reversal (e.g., +0.01% → -0.01%) = significant positioning change.
  Settlement countdown < 30min with extreme predicted rate: expect short-term volatility.
  History: Persistent same-sign rates (>3 settlements) = established positioning.
  Reversal from extreme = positioning unwind, expect opposite-side volatility.
⚠️ Funding alone without OI/price context = premature contrarian trades.
⚠️ FR BLOCKING: If the report shows "FR TREND EXHAUSTION" or "FR PRESSURE", it means
  FR has blocked the same direction multiple times. The market is structurally hostile
  to that direction. Consider the OPPOSITE direction or HOLD — do NOT keep signaling
  the blocked direction (it will be degraded to HOLD by the execution engine).

--- PREMIUM INDEX ---
Premium Index = (Mark Price - Index Price) / Index Price.
  Positive = futures trading above spot = long premium (bulls paying to hold).
  Negative = futures below spot = short premium (bears paying to hold).
  Predicts next funding rate direction. Premium > 0.05% = expect positive funding.
  Sharp premium spike = aggressive leveraged positioning, often precedes mean-reversion.
⚠️ Premium Index is instantaneous — confirm with funding trend before acting.

--- OPEN INTEREST (4-Quadrant Matrix) ---
  Price ↑ + OI ↑ = New longs entering → BULLISH CONFIRMATION
  Price ↑ + OI ↓ = Short covering     → WEAK rally (no new conviction)
  Price ↓ + OI ↑ = New shorts entering → BEARISH CONFIRMATION
  Price ↓ + OI ↓ = Long liquidation    → BEARISH EXHAUSTION (potential bottom)
Rising OI in consolidation = energy building. Sharp OI drop after crash = capitulation.
⚠️ OI alone reveals nothing — must combine with price direction.

--- ORDER BOOK ---
OBI: (Bid Vol - Ask Vol) / Total. Positive = buy support. Negative = sell pressure.
Dynamics: OBI/depth changes vs previous snapshot show evolving pressure.
Walls (>3x avg size): Potential S/R, but can be spoofed (placed and cancelled).
⚠️ High slippage = low liquidity → smaller position sizes needed.

--- S/R ZONES ---
Strength: HIGH (≥3 sources), MEDIUM (2), LOW (1).
TRENDING: S/R breaks frequently. Broken support → resistance and vice versa.
RANGING: S/R holds reliably. Mean-reversion at zones works.
⚠️ ADX > 40: S/R bounce rate drops to ~25%.

--- SENTIMENT (Binance L/S Ratio) ---
Contrarian at extremes: >55% long = squeeze risk. >55% short = rally risk.
⚠️ Extremes persist in strong trends. Only meaningful at very high readings (>60%).
DISAMBIGUATION (prevent contradictory readings):
  - High long ratio (>60%) = ONE meaning only: crowded longs → short squeeze risk.
    Bull must acknowledge this risk. Bear must cite it as risk to longs.
    ❌ WRONG: Bull says "high long ratio = bullish consensus confirming uptrend."
    ✅ CORRECT: "68% long ratio = crowded, contrarian reversal risk elevated."
  - 50-55% range = NEUTRAL, do not use as evidence for either side.
  - If UNAVAILABLE (marked ⚠️ WARNING), ignore completely — do not infer from other data.

--- OBV (On-Balance Volume) DIVERGENCE (v20.0) ---
OBV = cumulative volume: add bar volume when close > prev close, subtract when close < prev close.
Captures macro accumulation/distribution patterns (complementary to CVD which captures micro order flow).
DIVERGENCE: Price higher high + OBV lower high = DISTRIBUTION (volume not confirming rally).
  Price lower low + OBV higher low = ACCUMULATION (smart money buying the dip).
OBV divergence alone has ~40-60% false positive rate — always confirm with RSI/MACD/CVD.
When OBV AND CVD both diverge from price = HIGH CONFIDENCE volume signal (confluence).
TRENDING: OBV divergence can persist — strong trends override. Weight at 0.7.
RANGING: OBV divergence is more actionable — mean-reversion context. Weight at 1.2.
⚠️ OBV uses EMA(20) smoothing. Raw OBV is too noisy for divergence detection in 24/7 crypto.

--- ATR VOLATILITY REGIME (v20.0) ---
ATR% = ATR(14) / Price × 100. Ranked against rolling 90-bar historical distribution.
  LOW (<30th percentile): Calm / squeeze environment. Tighter stops viable. Breakout imminent?
  NORMAL (30-70th): Standard conditions. No adjustment needed.
  HIGH (70-90th): Elevated volatility. Widen stops, reduce position size.
  EXTREME (>90th): Rare event. High whipsaw risk. Strongly consider HOLD or minimal size.
Orthogonal to ADX: ADX measures trend DIRECTIONALITY, Volatility Regime measures price FLUCTUATION magnitude.
  ADX high + Vol LOW = orderly trend (ideal). ADX low + Vol HIGH = chaotic chop (worst).
⚠️ This is a RISK/CONTEXT signal — adjusts position sizing and stop width, not direction.

--- ATR EXTENSION RATIO (v19.1) ---
Extension Ratio = (Price - SMA) / ATR. Measures price "stretch" from its
mean in volatility-adjusted units. Unlike fixed-% thresholds, this adapts
automatically to current market volatility.
  |ratio| < 2.0: NORMAL — price within typical range of its mean.
  |ratio| 2.0-3.0: EXTENDED — price stretched, momentum may be weakening.
  |ratio| 3.0-5.0: OVEREXTENDED — mean-reversion pressure building.
    Entering in the extended direction = higher risk of snapback.
    Counter-trend signals gain credibility at this level.
  |ratio| > 5.0: EXTREME — historically rare, high probability of pullback.
    Even in strong trends, price typically reverts toward SMA before continuing.
TRENDING (ADX>40): Extension 3-5 ATR is COMMON and sustainable — not a reversal signal.
  Strong trends routinely operate at 3+ ATR from SMA for extended periods.
  Only >5 ATR (EXTREME) warrants real caution. Do NOT treat OVEREXTENDED as bearish in strong trends.
TRENDING (ADX 25-40): Extension 2-3 ATR is normal. >3 ATR warrants caution.
RANGING (ADX<20): Even 2 ATR extension is significant — mean-reversion is the edge.
⚠️ Extension is NOT a timing signal — it says "stretched", not "reversing now."
   Use it to assess RISK (position size, entry quality), not as a standalone signal.
   A trend can stay overextended for many bars before reverting.
   Combine with: RSI divergence, volume decline, or funding rate extreme for timing.

--- LIQUIDATIONS ---
TRENDING: High liquidation volume (>$200M/24h) with dominant side = trend confirmation.
  Long liq >60% = longs being squeezed → BEARISH. Short liq >60% = shorts squeezed → BULLISH.
  Extreme cascades ($500M+) = market stress event, potential capitulation / exhaustion bottom.
RANGING: Balanced liquidations = neither side over-committed. Spikes at range boundaries = failed breakout traps.
Hourly Trend: Accelerating = cascade in progress. Decelerating = worst may be over.
⚠️ This is trend-confirming data — shows established direction, not future prediction. Use as confirmation, not prediction.

--- TOP TRADERS (Smart Money Positioning) ---
Binance top traders POSITION ratio: >55% long = smart money lean long. >55% short = lean short.
  SHIFT >2pp over multiple periods = active repositioning. History series shows trajectory.
ACCOUNT ratio divergence from POSITION ratio reveals CONVICTION CONCENTRATION:
  Position long > Account long = fewer accounts hold LARGER longs → concentrated conviction.
  Account long > Position long = more accounts with SMALLER longs → scattered, weak conviction.
TRENDING: Smart money aligned with trend = continuation. Diverging from retail = noteworthy.
RANGING: Positioning shifts at range boundaries = early reversal signal.
⚠️ "Top Traders" = top 20% by OI on Binance only. Contrast with retail sentiment for full picture.

--- K-LINE OHLCV (Candlestick Patterns) ---
30M OHLCV data shows actual candle shapes — use for ENTRY TIMING only, not direction.
TRENDING: Continuation patterns (small body pullbacks into prior range) = with-trend entries.
RANGING: Rejection wicks at range boundaries = mean-reversion confirmation.
Long upper wicks at resistance = selling pressure. Long lower wicks at support = buying pressure.
⚠️ 30M patterns alone have low predictive value. Confirm with 4H direction first.

--- PRESSURE GRADIENT & DEPTH DISTRIBUTION ---
Gradient: WHERE liquidity sits — near-5%, near-10%, near-20% from mid-price.
  High near-5% concentration (>60%) = strong immediate S/R, tight range likely.
  Spread-out concentration = thin near-price liquidity, vulnerable to spikes.
  Bid concentration > Ask = stronger buy support. Ask > Bid = stronger sell resistance.
Depth Distribution: 0.5% bands around current price.
  Heavy bid at -0.5% + light ask at +0.5% = path of least resistance is UP (and vice versa).
TRENDING: One-sided gradient filling = institutional limit orders absorbing the move.
RANGING: Symmetric gradients = balanced market, range holds.
⚠️ Spoofable (orders placed then cancelled). Confirm with OBI trend persistence over time.

--- TRADE COUNT & AVG TRADE SIZE ---
Trade Count: High = active, reliable signals. Low = thin/illiquid, signals less trustworthy.
Avg Trade Size: Rising = institutional activity. Falling = retail-dominated.
  Large avg ($5K+) with aligned CVD = institutional directional flow.
  Small avg + high count = retail FOMO/panic (contrarian at extremes).
TRENDING: High count + large size = genuine, not just retail emotion.
RANGING: Declining count + small size = losing interest, breakout preparation.
⚠️ Varies by session (Asia vs US). Compare within same session context.

--- BUY RATIO RANGE STATISTICS ---
Range spread + stddev of recent 10-bar buy ratios (microstructure signal).
  Low spread (<5%) + low stddev = COMPRESSED flow → breakout imminent (direction unknown).
  High spread (>15%) = noisy flow, directional signals less reliable.
  Persistent one-sided (avg >55% buy or <45%) = sustained directional pressure.
⚠️ Taker trades only. Passive (maker) flow is invisible in this metric.

--- COINALYZE L/S RATIO ---
Distinct from Binance retail sentiment — Coinalyze aggregates across exchanges, more institutional.
When Coinalyze and Binance L/S AGREE = strong positioning signal.
When they DIVERGE = smart money vs retail conflict:
  Retail long + Institutional short = smart money fading retail (bearish).
  Retail short + Institutional long = accumulating against retail fear (bullish).
⚠️ Coinalyze data may be delayed or unavailable. If N/A, rely on Binance sentiment alone.

--- 24h MARKET STATS ---
24h Price Change + Volume provide CONTEXT for regime assessment, not direct signals.
  >3% move = momentum established, trend-following more reliable.
  <1% move + declining volume = consolidation/range. Volume surge + no price move = absorption.
⚠️ 24h window spans multiple sessions. Not a standalone signal.

--- TIME-SERIES DATA ---
All series ordered oldest → newest (chronological).
Look for: divergences, trend changes, acceleration/deceleration in momentum.

====================================================================
CONFLUENCE FRAMEWORK
====================================================================
Single indicators have high false positive rates. Confirm across layers:
  Layer 1 — TREND: SMA 200, ADX/DI direction
  Layer 2 — MOMENTUM: RSI, MACD histogram, CVD
  Layer 3 — KEY LEVEL: S/R zone, BB band, order book wall

Example — strong setup: All 3 layers align in same direction.
Example — weak setup: Trend layer (ADX/SMA) conflicts with momentum/levels
  → trend is statistically the stronger predictor in this conflict.
"""

# =============================================================================
# SIGNAL CONFIDENCE MATRIX (v1.2)
# =============================================================================
# - Quantified per-signal, per-regime confidence multipliers
# - Only injected into Judge + Risk Manager prompts (NOT Bull/Bear)
# - See docs/INDICATOR_CONFIDENCE_MATRIX.md for full design rationale
# =============================================================================
SIGNAL_CONFIDENCE_MATRIX = """
====================================================================
SIGNAL CONFIDENCE MATRIX (v1.2)
====================================================================
When evaluating each confluence layer in STEP 2, apply these confidence
multipliers to weight each signal's reliability in the current regime
(determined in STEP 1).

MULTIPLIER SCALE:
  HIGH (1.2+) = Signal is especially reliable in this regime
  STD  (1.0)  = Standard confidence
  LOW  (0.7)  = Needs other signals to confirm before trusting
  SKIP (≤0.4) = Unreliable in this regime — ignore as primary basis

REGIME COLUMNS: Match your STEP 1 regime to the correct column.
  ADX>40     = Strong trend (趋势层主导)
  ADX 25-40  = Weak trend (趋势重要但非绝对)
  ADX<20     = Ranging / 震荡 (关键水平层权重最高)
  SQUEEZE    = ADX<20 + BB Width at lows (等待突破)
  VOLATILE   = ADX>25 + BB Width expanding fast (趋势跟随 + 宽止损)

REGIME TRANSITION: When ADX is near a boundary (18-22 or 35-45),
blend the multipliers of adjacent regimes (take the average).

====================================================================
SECTION A: SNAPSHOT SIGNALS (per confluence layer)
====================================================================

--- LAYER 1: TREND (1D) → fill confluence.trend_1d ---

| Signal              | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|---------------------|:---:|:---:|:---:|:---:|:---:|----------|
| 1D SMA200 direction | 1.3 | 1.0 | 0.4 | 0.3 | 1.1 | Trend    |
| 1D ADX/DI direction | 1.2 | 1.0 | 0.3 | 0.3 | 1.1 | Trend    |
| 1D MACD zero-line   | 1.1 | 1.0 | 0.3 | 0.5 | 1.0 | Trend    |
| 1D MACD histogram   | 1.0 | 1.0 | 0.3 | 0.5 | 0.9 | Momentum |
| 1D RSI level        | 0.9 | 1.0 | 0.7 | 0.6 | 0.8 | Momentum |

Notes:
- ADX>40: This layer is DOMINANT — all signals reliable.
- ADX<20: This layer is nearly irrelevant (trend data is noise).
- SQUEEZE: Historical trend direction has low predictive value (about to change).
- VOLATILE: Trend is real but noisy — slightly less reliable than calm strong trend.
- ⚠️ 1D TREND VERDICT (STRONG_BULLISH etc.) is pre-computed from these 4 signals.
  It is a SUMMARY — do NOT count it as a 5th independent signal. (See RULE 2)

--- LAYER 2: MOMENTUM (4H) → fill confluence.momentum_4h ---

| Signal               | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature      |
|----------------------|:---:|:---:|:---:|:---:|:---:|-------------|
| 4H RSI level         | 0.8 | 1.0 | 1.2 | 0.9 | 0.7 | Momentum    |
| 4H RSI divergence*   | 0.6 | 0.8 | 1.3 | 1.1 | 0.5 | Momentum    |
| 4H MACD cross        | 1.2 | 1.0 | 0.3 | 0.5 | 1.1 | Trend       |
| 4H MACD histogram    | 1.0 | 1.0 | 0.5 | 0.7 | 0.9 | Momentum    |
| 4H ADX/DI direction  | 1.1 | 1.0 | 0.4 | 0.5 | 1.0 | Trend       |
| 4H BB position       | 0.6 | 0.9 | 1.2 | 0.8 | 0.5 | Momentum    |
| 4H SMA 20/50 cross   | 1.1 | 1.0 | 0.4 | 0.6 | 1.0 | Trend       |
| CVD single-bar delta | 0.9 | 1.0 | 1.2 | 1.3 | 1.0 | Order Flow  |
| CVD trend (cumul.)   | 1.1 | 1.0 | 0.8 | 0.7 | 1.0 | Order Flow  |
| CVD divergence*      | 0.7 | 0.9 | 1.3 | 1.2 | 0.5 | Order Flow  |
| CVD absorption**     | 0.5 | 1.3 | 1.1 | 0.8 | 0.4 | Order Flow  |
| OI×CVD positioning   | 1.1 | 0.9 | 1.0 | 1.1 | 1.0 | Order Flow  |
| Buy Ratio (taker %)  | 0.8 | 1.0 | 1.1 | 1.2 | 0.9 | Order Flow  |
| Avg Trade Size chg   | 0.7 | 0.9 | 1.0 | 1.2 | 0.8 | Order Flow  |

Notes:
- *Divergence = inferred from series data (RSI or CVD vs price opposite directions).
- **Absorption = CVD positive/negative but price flat (±0.3%). Most reliable in RANGING (1.3)
  where passive orders are most visible. Unreliable in TRENDING (0.5) — trend absorbs volume naturally.
- RSI in ADX>40: Cardwell range shifts apply (40-80 uptrend, 20-60 downtrend),
  traditional 30/70 FAIL. Divergence at 0.6 because it still signals deceleration.
- MACD cross in ADX<20: 74-97% false positive rate — nearly useless.
- VOLATILE: Divergence signals (RSI/CVD) are very unreliable (0.5) due to noise-induced
  false divergences. Trend-confirming signals (MACD cross, ADX/DI) remain useful.
  BB position also unreliable — price swings overshoot bands frequently.
- Buy Ratio: Taker buy % from Order Flow data. >55% = buy pressure, <45% = sell.
- Avg Trade Size: Sudden increase = institutional activity (order flow signal).

--- ATR EXTENSION RATIO (v19.1) → supplements ENTRY QUALITY assessment ---

| Signal                      | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|-----------------------------|:---:|:---:|:---:|:---:|:---:|----------|
| Ext Ratio >3 (overextended) | 0.7 | 1.0 | 1.3 | 0.8 | 0.6 | Volatility |
| Ext Ratio >5 (extreme)      | 1.0 | 1.2 | 1.4 | 0.9 | 0.8 | Volatility |

Notes:
- Extension Ratio = (Price - SMA20) / ATR. Measures price stretch from mean.
- ADX>40: Extension 3-5 ATR is NORMAL and SUSTAINABLE in strong trends (multiplier 0.7 = de-emphasize).
  Only extreme (>5) is noteworthy (multiplier 1.0 = neutral). Do NOT use OVEREXTENDED as anti-trend argument.
- ADX<20: Mean-reversion is the edge. Extension >3 ATR is highly actionable (multiplier 1.3 = amplify).
- This is a RISK signal, not directional. Use it to assess ENTRY QUALITY and
  POSITION SIZE, not to override direction from Layers 1-3.
- ⚠️ Overextension = higher risk of snapback, NOT a guarantee of reversal.
  A strong trend (ADX>40) can stay OVEREXTENDED for dozens of bars.

--- ATR VOLATILITY REGIME (v20.0) → supplements RISK assessment ---

| Signal                      | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|-----------------------------|:---:|:---:|:---:|:---:|:---:|----------|
| Vol LOW (<30th pctl)        | 1.0 | 1.0 | 1.2 | 1.3 | 0.5 | Volatility |
| Vol HIGH (70-90th pctl)     | 0.8 | 0.9 | 0.7 | 0.6 | 1.0 | Volatility |
| Vol EXTREME (>90th pctl)    | 0.6 | 0.7 | 0.5 | 0.4 | 0.8 | Volatility |

Notes:
- Volatility Regime = ATR% percentile rank over 90-bar lookback.
- Orthogonal to ADX: ADX = trend directionality, Vol Regime = fluctuation magnitude.
- LOW vol in ranging market (1.2) = squeeze, breakout imminent — directional signals gain weight.
- HIGH/EXTREME vol reduces confidence in all signals (wider stops needed, whipsaw risk).
- VOLATILE regime + HIGH vol = expected (1.0); SQUEEZE + HIGH vol = contradictory (0.6).

--- OBV DIVERGENCE (v20.0) → supplements MOMENTUM assessment ---

| Signal                      | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|-----------------------------|:---:|:---:|:---:|:---:|:---:|----------|
| 4H OBV divergence           | 0.7 | 0.9 | 1.2 | 1.0 | 0.8 | Momentum   |
| OBV+CVD confluence div      | 1.1 | 1.2 | 1.4 | 1.2 | 1.0 | Momentum   |

Notes:
- OBV divergence alone has 40-60% false positive rate — use as supplementary signal only.
- OBV + CVD confluence (both diverging from price) = strong volume-flow signal.
- ADX>40: OBV divergence less reliable (strong trends override volume patterns, 0.7).
- ADX<20: OBV divergence most actionable (mean-reversion edge, 1.2).

--- LAYER 3: KEY LEVELS (30M) → fill confluence.levels_30m ---

| Signal               | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|----------------------|:---:|:---:|:---:|:---:|:---:|----------|
| S/R zone test (bnce) | 0.5 | 0.8 | 1.3 | 1.0 | 0.4 | Structure   |
| S/R zone breakout    | 1.3 | 1.0 | 0.6 | 1.2 | 1.3 | Structure   |
| 30M BB position      | 0.6 | 0.9 | 1.2 | 0.8 | 0.5 | Momentum    |
| 30M BB Width level   | 0.7 | 0.8 | 0.9 | 1.3 | 0.8 | Volatility  |
| OBI (book imbalance) | 0.6 | 0.8 | 1.1 | 1.2 | 0.5 | Order Flow  |
| OBI change rate      | 0.7 | 0.9 | 1.2 | 1.3 | 0.6 | Order Flow  |
| Bid/Ask depth change | 0.7 | 0.9 | 1.1 | 1.2 | 0.6 | Order Flow  |
| Pressure gradient    | 0.6 | 0.8 | 1.1 | 1.2 | 0.5 | Order Flow  |
| Order walls (>3x)    | 0.4 | 0.6 | 0.9 | 1.0 | 0.3 | Order Flow  |
| 30M MACD cross       | 1.0 | 1.0 | 0.5 | 0.7 | 0.9 | Momentum    |
| 30M MACD histogram   | 0.9 | 1.0 | 0.5 | 0.7 | 0.9 | Momentum    |
| 30M SMA cross (5/20) | 0.9 | 1.0 | 0.6 | 0.7 | 0.8 | Trend       |
| 30M Volume ratio     | 0.9 | 1.0 | 1.1 | 1.3 | 1.2 | Momentum    |
| Price vs period H/L  | 0.8 | 1.0 | 1.1 | 1.0 | 0.9 | Structure   |
| Spread (liquidity)   | 0.9 | 1.0 | 1.0 | 1.1 | 1.1 | Risk        |
| Slippage (execution) | 0.9 | 1.0 | 1.0 | 1.1 | 1.1 | Risk        |

Notes:
- S/R bounce rate: ADX>40 → ~25%, ADX<20 → ~70%.
- VOLATILE: S/R breaks violently (0.4 bounce, 1.3 breakout). Order book is unstable
  (walls eaten or pulled quickly). Volume ratio is meaningful (confirms volatile move).
- Order walls in crypto: Spoofing probability HIGH (>70% of large walls are pulled
  before touch in trending markets). SKIP in ADX>40 and VOLATILE.
- Spread & Slippage: Not directional — indicate execution quality. High spread (>0.05%)
  or high slippage (>0.1% for 1 BTC) → reduce Layer 3 confidence by one tier
  AND reduce position size.

--- LAYER 4: DERIVATIVES → fill confluence.derivatives ---
⚠️ This layer has the most signals. To prevent it from dominating,
group related signals and evaluate the GROUP as one input:
  Group A: Funding Rate (current + extreme + predicted + history + countdown) → 1 input
  Group B: Open Interest (OI 4-quadrant + OI trend + Premium Index) → 1 input
  Group C: Positioning (Top Traders + Global L/S + Coinalyze L/S) → 1 input
  Group D: Real-time flow (Taker Ratio + Liquidations + 24h context) → 1 input
Then synthesize the 4 group conclusions into ONE overall BULLISH/BEARISH/NEUTRAL
for confluence.derivatives.

| Signal                       | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature   |
|------------------------------|:---:|:---:|:---:|:---:|:---:|----------|
| — GROUP A: FUNDING RATE —    |     |     |     |     |     |             |
| FR current value             | 0.8 | 0.9 | 1.0 | 1.0 | 0.8 | Risk        |
| FR extreme (>±0.05%)        | 0.8 | 1.1 | 1.3 | 1.2 | 0.9 | Risk        |
| FR predicted vs settled diff | 0.9 | 1.0 | 1.1 | 1.2 | 0.9 | Risk        |
| FR settlement history trend  | 0.8 | 1.0 | 1.1 | 1.0 | 0.8 | Risk        |
| FR settlement countdown      | 0.7 | 0.8 | 0.9 | 1.0 | 0.7 | Risk        |
| — GROUP B: OPEN INTEREST —   |     |     |     |     |     |             |
| Premium Index                | 0.8 | 1.0 | 1.1 | 1.2 | 0.9 | Risk        |
| OI↑+Price↑ (new longs)      | 1.2 | 1.0 | 0.8 | 0.9 | 1.1 | Risk        |
| OI↑+Price↓ (new shorts)     | 1.2 | 1.0 | 0.8 | 0.9 | 1.1 | Risk        |
| OI↓ (unwinding/liquidation)  | 0.9 | 1.0 | 1.0 | 0.8 | 1.0 | Risk        |
| — GROUP C: POSITIONING —     |     |     |     |     |     |             |
| Top Traders L/S position     | 1.0 | 1.0 | 1.2 | 1.1 | 1.0 | Risk        |
| Global L/S extreme (>60%)   | 0.6 | 0.9 | 1.2 | 1.1 | 0.7 | Risk        |
| Coinalyze L/S Ratio + trend | 0.7 | 0.9 | 1.1 | 1.0 | 0.7 | Risk        |
| — GROUP D: REAL-TIME FLOW —  |     |     |     |     |     |             |
| Taker Buy/Sell Ratio         | 0.9 | 1.0 | 1.1 | 1.2 | 1.0 | Order Flow  |
| Liquidation (large event)    | 1.0 | 1.1 | 1.2 | 1.3 | 1.2 | Risk        |
| 24h Volume level             | 0.8 | 1.0 | 1.0 | 1.1 | 1.1 | Context     |
| 24h Price Change %           | 0.7 | 0.9 | 0.9 | 1.0 | 0.8 | Context     |

Notes:
- ⚠️ GROUP RULE: Pick the strongest signal within each group to represent it.
  Do NOT stack all FR signals into one massive FR-driven conclusion.
- FR current in ADX>40: 0.01-0.03% in bull market is NORMAL — don't over-interpret.
- FR predicted vs settled: Sign reversal (+→-) = significant positioning change.
- OI 4-quadrant in ADX>40: New positioning confirms trend — high reliability.
- OI 4-quadrant in ADX<20: May be hedging — moderate value (0.8).
- Top Traders in ADX>40: Smart money WITH trend = confirmation (1.0).
  Top Traders AGAINST trend = early warning, needs 2+ confirmations.
- VOLATILE: FR signals slightly less predictive (volatile markets amplify FR).
  OI confirmation still useful (1.1). Liquidation events are significant (1.2)
  — cascade liquidations in volatile markets can be extreme.

====================================================================
SECTION B: TIME-SERIES PATTERN SIGNALS
====================================================================
AI receives 20-bar (30M) time-series data. Detect patterns from
series, then apply multipliers.

--- PRICE SERIES PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| Higher highs/lows      | 1.3 | 1.0 | 0.5 | 0.6 | 1.2 | Trend      |
| Lower highs/lows       | 1.3 | 1.0 | 0.5 | 0.6 | 1.2 | Trend      |
| Range-bound oscillation| 0.4 | 0.7 | 1.3 | 1.0 | 0.3 | Structure  |
| Tightening range       | 0.5 | 0.8 | 1.0 | 1.3 | 0.5 | Volatility |
| Volume climax (spike)  | 1.0 | 1.1 | 1.2 | 1.3 | 1.2 | Momentum   |

--- INDICATOR SERIES PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| ADX series rising      | 1.2 | 1.1 | 1.3 | 1.2 | 1.1 | Trend — trend strengthening      |
| ADX series falling     | 0.8 | 1.0 | 0.7 | 0.7 | 0.9 | Trend — trend weakening          |
| BB Width narrowing     | 0.6 | 0.8 | 1.0 | 1.3 | 0.5 | Volatility — squeeze forming     |
| BB Width expanding     | 1.1 | 1.0 | 0.8 | 1.3 | 1.2 | Volatility — breakout active     |
| SMA convergence (5→20) | 0.7 | 0.9 | 1.1 | 1.2 | 0.7 | Trend — regime change            |
| SMA divergence (spread)| 1.2 | 1.0 | 0.5 | 0.8 | 1.1 | Trend — trend established        |
| RSI trend (accel/decel)| 0.9 | 1.0 | 1.1 | 1.0 | 0.8 | Momentum                         |
| MACD histogram momentum| 1.0 | 1.0 | 0.5 | 0.8 | 0.9 | Momentum                         |
| Volume trend (expand)  | 1.1 | 1.0 | 1.0 | 1.3 | 1.2 | Momentum                         |
| Volume trend (shrink)  | 0.8 | 0.9 | 0.9 | 0.7 | 0.8 | Momentum                         |

--- K-LINE OHLCV PATTERNS ---

| Pattern                | ADX>40 | ADX 25-40 | ADX<20 | SQUEEZE | VOLATILE | Nature  |
|------------------------|:---:|:---:|:---:|:---:|:---:|---------|
| Engulfing candle       | 0.7 | 1.0 | 1.2 | 1.3 | 0.6 | Momentum — reversal      |
| Doji at S/R            | 0.5 | 0.8 | 1.3 | 1.1 | 0.4 | Momentum — indecision    |
| Long wicks (rejection) | 0.6 | 0.9 | 1.2 | 1.1 | 0.5 | Momentum — rejection     |
| Consecutive same-dir   | 1.2 | 1.0 | 0.6 | 0.8 | 1.1 | Trend — continuation     |

Notes:
- ADX rising in ADX<20 (1.3) = CRITICAL early signal — regime shift imminent. ADX climbing 12→18 means
  regime is about to shift to TRENDING. One of the most valuable signals.
- BB Width narrowing in SQUEEZE at 1.3 (not 1.5): narrowing DEFINES squeeze,
  so highest multiplier would be circular. 1.3 for the process is appropriate.
- VOLATILE: Reversal patterns (engulfing, doji, wicks) are very unreliable
  (0.4-0.6) — volatility creates many false reversal signals. Trend continuation
  patterns remain useful (1.1-1.2). Volume and BB Width expansion confirm the move.

====================================================================
SECTION C: MULTI-SOURCE SIGNAL DIFFERENTIATION
====================================================================
The system receives similar data from multiple sources. These are NOT
redundant — each has different predictive characteristics.

--- LONG/SHORT POSITIONING (3 sources) ---

| Source                | Represents              | Edge                    | Relative |
|-----------------------|-------------------------|-------------------------|:---:|
| Top Traders Position  | Institutional/whale     | Best predictor          | Highest  |
| Taker Buy/Sell Ratio  | Real-time aggressive flow| Real-time direction    | High     |
| Binance Global L/S    | Retail sentiment        | Contrarian at extremes  | Base     |
| Coinalyze L/S Ratio   | Exchange-specific       | Cross-validates Binance | Below    |

RULE: Top Traders vs Global L/S diverge → weight Top Traders.
      All 3+ agree at extremes → very HIGH confidence.

--- OPEN INTEREST (2 sources) ---

| Source        | Characteristic            | Best for             |
|---------------|---------------------------|----------------------|
| Coinalyze OI  | Aggregated multi-exchange | Macro trend (4H)     |
| Binance OI    | Single exchange, real-time| Short-term moves(30M)|

RULE: Same trend → add one confidence tier to OI assessment.
      Disagree → use Binance for execution, Coinalyze for context.

--- FUND FLOW (2 sources) ---

| Source        | Calculation              | Best for              |
|---------------|--------------------------|----------------------|
| CVD (K-line)  | Cumulative taker delta   | Trend over bars      |
| Taker Ratio   | Buy/Sell vol snapshot    | Real-time pressure   |

RULE: Same direction → cross-validated, add one confidence tier.
      Diverge → transitioning, reduce one tier.

====================================================================
SECTION D: GLOBAL SIGNAL QUALITY MODIFIERS
====================================================================
These modify RELIABILITY of all signals. Apply BEFORE final decision.
Use TIER shifts (not math): each condition shifts confidence DOWN/UP
by one tier (HIGH→STD, STD→LOW, LOW→SKIP).

| Condition                                    | Effect        | Applies to              |
|----------------------------------------------|:---:|--------------------------|
| Volume Ratio < 0.5x (from 30M data)         | DOWN one tier | ALL signals              |
| Volume Ratio > 2.0x                          | UP one tier   | ALL signals              |
| Spread > 0.05% OR Slippage > 0.1%           | DOWN one tier | Layer 3 + position size  |
| 2+ data sources unavailable                  | DOWN one tier | Affected layers          |
| FR settlement < 30 min away                  | DOWN one tier | Short-term (30M) signals |
| Low volume + thin orderbook across bars      | DOWN one tier | ALL signals (weekend/off-hours) |

Notes:
- Tier shifts stack: 2 conditions = DOWN two tiers.
- Volume Ratio comes from 30M data ("Volume Ratio: X.XXx average").
- Weekend/off-hours: No date data available. Infer from persistently low
  volume ratio + reduced orderbook depth across multiple snapshots.

====================================================================
SECTION E: APPLICATION RULES
====================================================================

RULE 1 — Layer evaluation:
  For each confluence layer, assess each signal weighted by its
  confidence tier in the current regime:
    HIGH (1.2+) = Primary evidence for layer judgment
    STD  (1.0)  = Supporting evidence
    LOW  (0.7)  = Note but don't base judgment on it alone
    SKIP (≤0.4) = Ignore for this regime

RULE 2 — TREND VERDICT is not a 5th signal:
  The pre-computed 1D TREND VERDICT is a summary of the 4 Layer 1
  signals. Use for quick reference ONLY. Do NOT count as independent.

RULE 3 — Conflict resolution:
  If leading and lagging signals within one layer conflict, prioritize
  the one with HIGHER confidence tier in current regime.

RULE 4 — Neutral threshold:
  If only SKIP or LOW signals support a direction in a layer,
  that layer should be judged NEUTRAL.

RULE 5 — SQUEEZE special case:
  Wait for breakout confirmation (volume + price) before applying
  directional multipliers. Pre-breakout: focus on BB Width, Volume,
  OBI change rate, ADX rising.

RULE 6 — Counter-trend in ADX>40:
  Even HIGH counter-trend signals require at least 2 independent
  confirming signals before consideration.

RULE 7 — Multi-source agreement:
  3+ independent sources agree on direction → upgrade that layer
  by one confidence tier.

RULE 8 — Layer 4 grouping → confluence.derivatives:
  Evaluate Layer 4 in 4 groups (A/B/C/D). Each group = 1 input.
  Then synthesize the 4 group conclusions into ONE overall
  BULLISH/BEARISH/NEUTRAL judgment for the confluence.derivatives field.

RULE 9 — Global quality check:
  Before final decision, check Section D. Apply tier shifts.
"""


def _trim_matrix_for_regime(adx_1d: float) -> str:
    """
    Trim SIGNAL_CONFIDENCE_MATRIX to only include the relevant regime column(s).

    v5.13: Reduces matrix from ~16k chars to ~10k chars by removing irrelevant
    regime columns. When ADX is near a boundary (18-22 or 35-45), includes
    both adjacent columns per the matrix's own REGIME TRANSITION rule.

    Args:
        adx_1d: 1D ADX value for regime determination

    Returns:
        Trimmed matrix string with only relevant column(s)
    """
    # Determine which column indices to keep
    # Table columns: 0=Signal, 1=ADX>40, 2=ADX 25-40, 3=ADX<20, 4=SQUEEZE, 5=VOLATILE, 6=Nature
    regime_name = ""
    keep_cols: list = []

    if adx_1d >= 45:
        regime_name = "ADX>40 (STRONG TREND)"
        keep_cols = [1]
    elif adx_1d >= 35:
        # Boundary 35-45: blend ADX>40 and ADX 25-40
        regime_name = f"ADX={adx_1d:.0f} (BOUNDARY: ADX>40 + ADX 25-40)"
        keep_cols = [1, 2]
    elif adx_1d >= 22:
        regime_name = "ADX 25-40 (WEAK TREND)"
        keep_cols = [2]
    elif adx_1d >= 18:
        # Boundary 18-22: blend ADX 25-40 and ADX<20
        regime_name = f"ADX={adx_1d:.0f} (BOUNDARY: ADX 25-40 + ADX<20)"
        keep_cols = [2, 3]
    else:
        regime_name = "ADX<20 (RANGING)"
        keep_cols = [3]

    # Column header names for reference
    col_names = {
        1: "ADX>40",
        2: "ADX 25-40",
        3: "ADX<20",
        4: "SQUEEZE",
        5: "VOLATILE",
    }

    # Build regime header
    header = f"""====================================================================
SIGNAL CONFIDENCE MATRIX (v1.2 — trimmed for current regime)
====================================================================
⚡ CURRENT REGIME: {regime_name}
Only the relevant regime column(s) are shown below.

MULTIPLIER SCALE:
  HIGH (1.2+) = Signal is especially reliable in this regime
  STD  (1.0)  = Standard confidence
  LOW  (0.7)  = Needs other signals to confirm before trusting
  SKIP (≤0.4) = Unreliable in this regime — ignore as primary basis
"""

    # Process the full matrix line by line
    lines = SIGNAL_CONFIDENCE_MATRIX.split('\n')
    result_lines = []
    in_table = False
    skip_until_next_section = False

    # Skip the original header (first ~14 lines up to SECTION A)
    start_idx = 0
    for i, line in enumerate(lines):
        if 'SECTION A:' in line:
            start_idx = i - 1  # include the ==== line before SECTION A
            break

    # Skip REGIME COLUMNS description (already covered by header)
    for line in lines[start_idx:]:
        stripped = line.strip()

        # Detect table rows (contain | separators)
        if stripped.startswith('|') and '|' in stripped[1:]:
            cells = [c.strip() for c in stripped.split('|')]
            # cells[0] is empty (before first |), cells[-1] may be empty
            cells = [c for c in cells if c != '']

            if len(cells) >= 7:  # Full table row with all 7 columns
                # Keep: Signal (0), selected regime cols, Nature (6)
                kept = [cells[0]]
                for ci in keep_cols:
                    kept.append(cells[ci])
                kept.append(cells[6])

                # Format as table row
                # Pad signal name to 24 chars, values to 5 chars
                sig = kept[0]
                vals = kept[1:-1]
                nature = kept[-1]
                row = f"| {sig:<24s} |"
                for v in vals:
                    row += f" {v:^5s} |"
                row += f" {nature} |"
                result_lines.append(row)
                in_table = True
            elif len(cells) >= 3 and in_table:
                # Separator row (---|:---:|...)
                sep = f"|{'—' * 26}|"
                for _ in keep_cols:
                    sep += f":{'—' * 5}:|"
                sep += f"{'—' * 10}|"
                result_lines.append(sep)
            else:
                in_table = False
                result_lines.append(line)
        else:
            in_table = False

            # Skip the regime column descriptions (already in header)
            if 'REGIME COLUMNS:' in stripped:
                skip_until_next_section = True
                continue
            if skip_until_next_section:
                if stripped.startswith('====') or stripped.startswith('---'):
                    skip_until_next_section = False
                else:
                    continue

            # Keep regime-specific notes relevant to current regime
            result_lines.append(line)

    return header + '\n'.join(result_lines)


# =============================================================================
# SIGNAL RELIABILITY ANNOTATIONS (v18.0 experiment)
# =============================================================================
# Inline tags based on SIGNAL_CONFIDENCE_MATRIX — appended next to each
# indicator value so AI is forced to see reliability in the current regime.
# Format: [Nature 🟢1.2] / [Nature 🟡1.0] / [Nature ⚪0.6] / [Nature ❌SKIP]
# =============================================================================

_SIGNAL_ANNOTATIONS = {
    # v41.0: Unified Indicator Classification — nature labels aligned with
    # compute_scores_from_features() 5 dimensions + Structure + Context.
    # Only nature labels changed; all multiplier values are UNCHANGED.
    # Layer 1 — TREND (1D)
    '1d_sma200':  ('Trend',      {'strong': 1.3, 'weak': 1.0, 'ranging': 0.4}),
    '1d_adx_di':  ('Trend',      {'strong': 1.2, 'weak': 1.0, 'ranging': 0.3}),
    '1d_macd':    ('Trend',      {'strong': 1.1, 'weak': 1.0, 'ranging': 0.3}),
    '1d_macd_h':  ('Momentum',   {'strong': 1.0, 'weak': 1.0, 'ranging': 0.3}),
    '1d_rsi':     ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 0.7}),
    # Layer 2 — MOMENTUM (4H)
    '4h_rsi':     ('Momentum',   {'strong': 0.8, 'weak': 1.0, 'ranging': 1.2}),
    '4h_macd':    ('Trend',      {'strong': 1.2, 'weak': 1.0, 'ranging': 0.3}),
    '4h_macd_h':  ('Momentum',   {'strong': 1.0, 'weak': 1.0, 'ranging': 0.5}),
    '4h_adx_di':  ('Trend',      {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),
    '4h_bb':      ('Momentum',   {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # BB position = mean-reversion (like RSI)
    '4h_sma':     ('Trend',      {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),
    # ATR/BB
    '1d_bb':      ('Momentum',   {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # BB position = mean-reversion
    '1d_atr':     ('Volatility', {'strong': 1.0, 'weak': 1.0, 'ranging': 1.0}),
    '4h_atr':     ('Volatility', {'strong': 1.0, 'weak': 1.0, 'ranging': 1.0}),
    '4h_vol_ratio': ('Momentum', {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),
    # Layer 3 — KEY LEVELS (30M)
    '30m_rsi':    ('Momentum',   {'strong': 0.8, 'weak': 1.0, 'ranging': 1.2}),
    '30m_macd':   ('Momentum',   {'strong': 1.0, 'weak': 1.0, 'ranging': 0.5}),
    '30m_macd_h': ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 0.5}),
    '30m_adx':    ('Trend',      {'strong': 1.1, 'weak': 1.0, 'ranging': 0.4}),
    '30m_bb':     ('Momentum',   {'strong': 0.6, 'weak': 0.9, 'ranging': 1.2}),  # BB position = mean-reversion
    '30m_sma':    ('Trend',      {'strong': 0.9, 'weak': 1.0, 'ranging': 0.6}),
    '30m_volume': ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),
    # v36.1: OBV — macro volume accumulation/distribution (v20.0 indicator)
    '30m_obv':    ('Momentum',   {'strong': 0.7, 'weak': 0.9, 'ranging': 1.0}),
    '4h_obv':     ('Momentum',   {'strong': 0.8, 'weak': 1.0, 'ranging': 1.0}),
    '1d_obv':     ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 0.8}),
    # v36.1: Missing 1D/4H volume ratio citation patterns
    '1d_volume':  ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 1.0}),
    '4h_volume':  ('Momentum',   {'strong': 0.9, 'weak': 1.0, 'ranging': 1.1}),
}


def _get_multiplier(key: str, adx_1d: float) -> tuple:
    """Return (nature, multiplier, tier) for a given annotation key and ADX.

    v18.1: Replaces _signal_tag(). Used by _format_technical_report() to
    group indicators by reliability tier instead of inline annotations.
    """
    info = _SIGNAL_ANNOTATIONS.get(key)
    if not info:
        return ('N/A', 1.0, 'std')
    nature, multipliers = info
    if adx_1d >= 40:
        m = multipliers['strong']
    elif adx_1d >= 25:
        m = multipliers['weak']
    else:
        m = multipliers['ranging']
    if m >= 1.2:
        tier = 'high'
    elif m >= 0.8:
        tier = 'std'
    elif m >= 0.5:
        tier = 'low'
    else:
        tier = 'skip'
    return (nature, m, tier)


# =============================================================================
# v27.0: Feature-Driven Architecture — Schemas, Tags, and Versioning
# =============================================================================

import hashlib

# --- Version Constants ---
SCHEMA_VERSION = "28.0"        # Output schema structure version (v28.0: reasoning + knowledge brief)
FEATURE_VERSION = "1.0"        # Input feature schema version
# MODEL_VERSION read from config at runtime (self.model)


def compute_prompt_version(prompt_text: str) -> str:
    """Deterministic hash of prompt text content."""
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:12]


# =============================================================================
# INDICATOR_KNOWLEDGE_BRIEF — Condensed Domain Knowledge for Structured Prompts
# =============================================================================
# Extracted from INDICATOR_DEFINITIONS (4K tokens) + SIGNAL_CONFIDENCE_MATRIX
# (5K tokens). Only the regime-aware interpretation rules that LLMs cannot
# infer from raw feature values alone. ~500 tokens injected into all 5 agents.
#
# v28.0: Addresses the "classification vs reasoning" gap where feature-driven
# prompts lost the domain knowledge that text-path prompts provided.
# =============================================================================
INDICATOR_KNOWLEDGE_BRIEF = """
=== INDICATOR INTERPRETATION RULES ===
Use these rules when analyzing features. They override common assumptions.

1. RSI CARDWELL RANGES: In strong trends (ADX>40), RSI normal range shifts.
   Uptrend: 40-80 (pullbacks to 40-50 = entries, 80 = strong momentum).
   Downtrend: 20-60 (rallies to 50-60 = entries, 20 = strong momentum).
   Traditional 30/70 only applies in RANGING markets (ADX<20).
   ⚠️ Buying RSI<30 in downtrend = most common retail mistake.

2. MACD RELIABILITY BY REGIME: In ranging markets (ADX<25), MACD crosses
   have 74-97% false positive rate — nearly useless. SKIP as primary signal.
   Only trust MACD in trending markets. Histogram direction > crossovers.

3. EXTENSION IN STRONG TRENDS: ADX>40 + Extension 3-5 ATR is COMMON and
   SUSTAINABLE — NOT a reversal signal. Only >5 ATR (EXTREME) warrants caution.
   ADX<20: Even 2 ATR extension is significant (mean-reversion is the edge).

4. S/R vs TREND: ADX>40 → S/R bounce rate drops to ~25%. Breakouts dominate.
   ADX<20 → S/R bounce rate ~70%. Mean-reversion at zones is the edge.
   Do NOT treat S/R as hard barriers in strong trends.

5. OBV / DIVERGENCE CONFLUENCE: Any single divergence (RSI, MACD, OBV, CVD)
   alone has 40-60% false positive rate. REQUIRE 2+ divergences agreeing
   (confluence) before treating as actionable signal.

6. FUNDING RATE CONTEXT: |FR| 0.01-0.03% in bull market is NORMAL, not bearish.
   Only |FR|>0.05% is crowded. |FR|>0.10% = extreme, reversal probability rises.
   Persistent same-sign FR (>3 settlements) = established positioning.

7. INDICATOR DIMENSIONS & REGIME-DEPENDENT WEIGHTING (v41.0):
   Each indicator belongs to one functional dimension. Weights are REGIME-DEPENDENT:
   - Trend (趋势确认): SMA200, ADX/DI, MACD cross, SMA/EMA cross — highest certainty,
     confirms established direction. Most reliable when ADX≥40.
   - Momentum (动量): RSI, MACD histogram, BB position, OBV, Volume ratio, divergences —
     measures speed and acceleration. Divergences are reversal warnings (require 2+ confluence).
   - Order Flow (订单流): CVD-Price cross, CVD trend, OBI, Taker ratio — highest
     information density, earliest directional signal. Most reliable in TRANSITIONING.
   - Volatility (波动率): ATR, Extension Ratio, BB Width, Volatility Regime — risk
     sizing signal, NOT directional. Affects position size and stop width.
   - Risk (风险环境): FR, OI, Liquidation, Sentiment, Spread/Slippage — risk assessment,
     can veto trades but does NOT drive direction.
   - Structure (价格结构): S/R zones, Price vs H/L — reference levels for SL/TP placement.
   - Context (背景): 24h Volume/Price — environment awareness, neither directional nor risk.
   REGIME-DEPENDENT PRIORITY (check _scores.regime_transition):
   - TRANSITIONING (order_flow ≠ trend): order_flow 2x weight — new direction forming.
   - ADX≥40 STRONG TREND: trend 1.5x — confirmed direction is most reliable signal.
   - ADX<20 RANGING: order_flow 1.5x — micro-structure dominates, trend signals are noise.
   - WEAK TREND (20≤ADX<40): equal weights — no single dimension dominates.
   ⚠️ The old static "1D > 4H > 30M" hierarchy is WRONG in transitioning markets.

8. VOLUME CONFIRMATION: Rising price + rising volume = genuine move.
   Rising price + falling volume = suspect (weak rally). Low-volume moves
   are unreliable regardless of direction.
"""

# --- Feature Schema (82 typed features) ---
# All agents receive one unified feature_dict instead of text reports.
# Each feature maps to an exact key in existing raw data dicts.

FEATURE_SCHEMA = {
    # ── 30M Execution Layer (from technical_manager.get_technical_data()) ──
    "price":                    {"type": "float", "source": "technical_data['price']"},
    "rsi_30m":                  {"type": "float", "source": "technical_data['rsi']"},
    "macd_30m":                 {"type": "float", "source": "technical_data['macd']"},
    "macd_signal_30m":          {"type": "float", "source": "technical_data['macd_signal']"},
    "macd_histogram_30m":       {"type": "float", "source": "technical_data['macd_histogram']"},
    "adx_30m":                  {"type": "float", "source": "technical_data['adx']"},
    "di_plus_30m":              {"type": "float", "source": "technical_data['di_plus']"},
    "di_minus_30m":             {"type": "float", "source": "technical_data['di_minus']"},
    "bb_position_30m":          {"type": "float", "source": "technical_data['bb_position']"},
    "bb_upper_30m":             {"type": "float", "source": "technical_data['bb_upper']"},
    "bb_lower_30m":             {"type": "float", "source": "technical_data['bb_lower']"},
    "sma_5_30m":                {"type": "float", "source": "technical_data['sma_5']"},   # v36.0 FIX: 30M has sma_periods=[5,20]
    "sma_20_30m":               {"type": "float", "source": "technical_data['sma_20']"},
    "volume_ratio_30m":         {"type": "float", "source": "technical_data['volume_ratio']"},
    "atr_pct_30m":              {"type": "float", "source": "technical_data['atr_pct']"},
    "ema_12_30m":               {"type": "float", "source": "technical_data['ema_12']"},  # base indicator_manager: ema_periods=[macd_fast=12, macd_slow=26]
    "ema_26_30m":               {"type": "float", "source": "technical_data['ema_26']"},

    # ── 4H Decision Layer (from technical_data['mtf_decision_layer']) ──
    "rsi_4h":                   {"type": "float", "source": "mtf_decision_layer['rsi']"},
    "macd_4h":                  {"type": "float", "source": "mtf_decision_layer['macd']"},
    "macd_signal_4h":           {"type": "float", "source": "mtf_decision_layer['macd_signal']"},
    "macd_histogram_4h":        {"type": "float", "source": "mtf_decision_layer['macd_histogram']"},
    "adx_4h":                   {"type": "float", "source": "mtf_decision_layer['adx']"},
    "di_plus_4h":               {"type": "float", "source": "mtf_decision_layer['di_plus']"},
    "di_minus_4h":              {"type": "float", "source": "mtf_decision_layer['di_minus']"},
    "bb_position_4h":           {"type": "float", "source": "mtf_decision_layer['bb_position']"},
    "bb_upper_4h":              {"type": "float", "source": "mtf_decision_layer['bb_upper']"},
    "bb_lower_4h":              {"type": "float", "source": "mtf_decision_layer['bb_lower']"},
    "sma_20_4h":                {"type": "float", "source": "mtf_decision_layer['sma_20']"},
    "sma_50_4h":                {"type": "float", "source": "mtf_decision_layer['sma_50']"},
    "volume_ratio_4h":          {"type": "float", "source": "mtf_decision_layer['volume_ratio']"},
    "atr_4h":                   {"type": "float", "source": "mtf_decision_layer['atr']"},
    "atr_pct_4h":               {"type": "float", "source": "mtf_decision_layer['atr_pct']"},
    "ema_12_4h":                {"type": "float", "source": "mtf_decision_layer['ema_12']"},
    "ema_26_4h":                {"type": "float", "source": "mtf_decision_layer['ema_26']"},
    "extension_ratio_4h":       {"type": "float", "source": "mtf_decision_layer['extension_ratio_sma_20']"},
    "extension_regime_4h":      {"type": "enum",  "values": ["NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"]},
    "volatility_regime_4h":     {"type": "enum",  "values": ["LOW", "NORMAL", "HIGH", "EXTREME"]},
    "volatility_percentile_4h": {"type": "float", "source": "mtf_decision_layer['volatility_percentile']"},

    # ── 1D Trend Layer (from technical_data['mtf_trend_layer']) ──
    "adx_1d":                   {"type": "float", "source": "mtf_trend_layer['adx']"},
    "di_plus_1d":               {"type": "float", "source": "mtf_trend_layer['di_plus']"},
    "di_minus_1d":              {"type": "float", "source": "mtf_trend_layer['di_minus']"},
    "rsi_1d":                   {"type": "float", "source": "mtf_trend_layer['rsi']"},
    "macd_1d":                  {"type": "float", "source": "mtf_trend_layer['macd']"},
    "macd_signal_1d":           {"type": "float", "source": "mtf_trend_layer['macd_signal']"},
    "macd_histogram_1d":        {"type": "float", "source": "mtf_trend_layer['macd_histogram']"},
    "sma_200_1d":               {"type": "float", "source": "mtf_trend_layer['sma_200']"},
    "bb_position_1d":           {"type": "float", "source": "mtf_trend_layer['bb_position']"},
    "volume_ratio_1d":          {"type": "float", "source": "mtf_trend_layer['volume_ratio']"},
    "atr_1d":                   {"type": "float", "source": "mtf_trend_layer['atr']"},
    "atr_pct_1d":               {"type": "float", "source": "mtf_trend_layer['atr_pct']"},
    "ema_12_1d":                {"type": "float", "source": "mtf_trend_layer['ema_12']"},
    "ema_26_1d":                {"type": "float", "source": "mtf_trend_layer['ema_26']"},
    "extension_ratio_1d":       {"type": "float", "source": "mtf_trend_layer['extension_ratio_sma_200']"},
    "extension_regime_1d":      {"type": "enum",  "values": ["NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"]},
    "volatility_regime_1d":     {"type": "enum",  "values": ["LOW", "NORMAL", "HIGH", "EXTREME"]},
    "volatility_percentile_1d": {"type": "float", "source": "mtf_trend_layer['volatility_percentile']"},

    # ── Risk Context (30M, renamed from unsuffixed to match 4H/1D convention) ──
    "extension_ratio_30m":      {"type": "float", "source": "technical_data['extension_ratio_sma_20']"},
    "extension_regime_30m":     {"type": "enum",  "values": ["NORMAL", "EXTENDED", "OVEREXTENDED", "EXTREME"]},
    "volatility_regime_30m":    {"type": "enum",  "values": ["LOW", "NORMAL", "HIGH", "EXTREME"]},
    "volatility_percentile_30m": {"type": "float", "source": "technical_data['volatility_percentile']"},
    "atr_30m":                  {"type": "float", "source": "technical_data['atr']"},

    # ── Market Regime (pre-computed) ──
    "market_regime":            {"type": "enum",  "values": ["STRONG_TREND", "WEAK_TREND", "RANGING"]},
    "adx_direction_1d":         {"type": "enum",  "values": ["BULLISH", "BEARISH", "NEUTRAL"]},  # v36.2: NEUTRAL when DI+ == DI-

    # ── Pre-computed Categorical (v31.0: LLM-friendly labels from raw numerics) ──
    "macd_cross_30m":           {"type": "enum",  "values": ["BULLISH", "BEARISH", "NEUTRAL"]},
    "macd_cross_4h":            {"type": "enum",  "values": ["BULLISH", "BEARISH", "NEUTRAL"]},
    "macd_cross_1d":            {"type": "enum",  "values": ["BULLISH", "BEARISH", "NEUTRAL"]},
    "di_direction_30m":         {"type": "enum",  "values": ["BULLISH", "BEARISH"]},
    "di_direction_4h":          {"type": "enum",  "values": ["BULLISH", "BEARISH"]},
    "rsi_zone_30m":             {"type": "enum",  "values": ["OVERSOLD", "NEUTRAL", "OVERBOUGHT"]},
    "rsi_zone_4h":              {"type": "enum",  "values": ["OVERSOLD", "NEUTRAL", "OVERBOUGHT"]},
    "rsi_zone_1d":              {"type": "enum",  "values": ["OVERSOLD", "NEUTRAL", "OVERBOUGHT"]},
    "fr_direction":             {"type": "enum",  "values": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},

    # ── Divergences (pre-computed by _detect_divergences()) ──
    "rsi_divergence_4h":        {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},
    "macd_divergence_4h":       {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},
    "obv_divergence_4h":        {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},
    "rsi_divergence_30m":       {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},
    "macd_divergence_30m":      {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},
    "obv_divergence_30m":       {"type": "enum",  "values": ["BULLISH", "BEARISH", "NONE"]},

    # ── Order Flow (from order_flow_report) ──
    "cvd_trend_30m":            {"type": "enum",  "values": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},
    "buy_ratio_30m":            {"type": "float", "source": "order_flow_report['buy_ratio']"},
    "cvd_cumulative_30m":       {"type": "float", "source": "order_flow_report['cvd_cumulative']"},
    "cvd_price_cross_30m":      {"type": "enum",  "values": ["ACCUMULATION", "DISTRIBUTION", "CONFIRMED_SELL", "ABSORPTION_BUY", "ABSORPTION_SELL", "NONE"]},

    # ── 4H CVD (from order_flow_4h) ──
    "cvd_trend_4h":             {"type": "enum",  "values": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},
    "buy_ratio_4h":             {"type": "float", "source": "order_flow_4h['buy_ratio']"},
    "cvd_price_cross_4h":       {"type": "enum",  "values": ["ACCUMULATION", "DISTRIBUTION", "CONFIRMED_SELL", "ABSORPTION_BUY", "ABSORPTION_SELL", "NONE"]},

    # ── Derivatives (from derivatives_report) ──
    "funding_rate_pct":         {"type": "float", "source": "funding_rate['current_pct']"},
    "funding_rate_trend":       {"type": "enum",  "values": ["RISING", "FALLING", "STABLE"]},
    "oi_trend":                 {"type": "enum",  "values": ["RISING", "FALLING", "STABLE"]},
    "liquidation_bias":         {"type": "enum",  "values": ["LONG_DOMINANT", "SHORT_DOMINANT", "BALANCED", "NONE"]},
    "premium_index":            {"type": "float", "source": "funding_rate['premium_index']"},

    # ── Orderbook (from orderbook_report) ──
    "obi_weighted":             {"type": "float", "source": "orderbook['obi']['weighted']"},
    "obi_change_pct":           {"type": "float", "source": "orderbook['dynamics']['obi_change_pct']"},
    "bid_volume_usd":           {"type": "float", "source": "orderbook['obi']['bid_volume_usd']"},
    "ask_volume_usd":           {"type": "float", "source": "orderbook['obi']['ask_volume_usd']"},

    # ── Sentiment (from sentiment_report) ──
    "long_ratio":               {"type": "float", "source": "sentiment['positive_ratio']"},
    "short_ratio":              {"type": "float", "source": "sentiment['negative_ratio']"},
    "sentiment_degraded":       {"type": "bool",  "source": "sentiment['degraded']"},

    # ── Top Traders (from binance_derivatives_report) ──
    "top_traders_long_ratio":   {"type": "float", "source": "binance_derivatives['top_traders']"},
    "taker_buy_ratio":          {"type": "float", "source": "binance_derivatives['taker_ratio']"},

    # ── S/R Zones (from sr_zones calculation) ──
    "nearest_support_price":    {"type": "float"},
    "nearest_support_strength": {"type": "enum",  "values": ["HIGH", "MEDIUM", "LOW", "NONE"]},
    "nearest_support_dist_atr": {"type": "float"},
    "nearest_resist_price":     {"type": "float"},
    "nearest_resist_strength":  {"type": "enum",  "values": ["HIGH", "MEDIUM", "LOW", "NONE"]},
    "nearest_resist_dist_atr":  {"type": "float"},

    # ── Position Context (from current_position + account_context) ──
    # v31.4: Source comments match production field names:
    #   position_pnl_pct ← current_position['pnl_percentage']
    #   position_size_pct ← current_position['margin_used_pct']
    #   liquidation_buffer_pct ← account_context['liquidation_buffer_portfolio_min_pct']
    "position_side":            {"type": "enum",  "values": ["LONG", "SHORT", "FLAT"]},
    "position_pnl_pct":         {"type": "float", "source": "current_position['pnl_percentage']"},
    "position_size_pct":        {"type": "float", "source": "current_position['margin_used_pct']"},
    "account_equity_usdt":      {"type": "float", "source": "account_context['equity']"},
    "liquidation_buffer_pct":   {"type": "float", "source": "account_context['liquidation_buffer_portfolio_min_pct']"},
    "leverage":                 {"type": "int",   "source": "account_context['leverage']"},

    # ── FR Block Context (v21.0) ──
    "fr_consecutive_blocks":    {"type": "int",   "source": "fr_block_context['consecutive_blocks']"},
    "fr_blocked_direction":     {"type": "enum",  "values": ["LONG", "SHORT", "NONE"]},

    # ── Trend Time Series (1D, last 5 bars summary) ──
    "adx_1d_trend_5bar":        {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},
    "di_spread_1d_trend_5bar":  {"type": "enum",  "values": ["WIDENING", "NARROWING", "FLAT"]},
    "rsi_1d_trend_5bar":        {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},
    "price_1d_change_5bar_pct": {"type": "float"},

    # ── 4H Time Series (last 5 bars summary, Entry Timing Agent key input) ──
    "rsi_4h_trend_5bar":            {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},
    "macd_histogram_4h_trend_5bar": {"type": "enum",  "values": ["EXPANDING", "CONTRACTING", "FLAT"]},
    "adx_4h_trend_5bar":            {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},
    "price_4h_change_5bar_pct":     {"type": "float"},
    "bb_width_4h_trend_5bar":       {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},  # v36.0

    # ── 30M Time Series (last 5 bars summary, execution layer momentum) ──
    "momentum_shift_30m":           {"type": "enum",  "values": ["ACCELERATING", "DECELERATING", "STABLE"]},
    "price_30m_change_5bar_pct":    {"type": "float"},
    "rsi_30m_trend_5bar":           {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},
    "bb_width_30m_trend_5bar":      {"type": "enum",  "values": ["RISING", "FALLING", "FLAT"]},  # v36.0

    # ── Data Availability Flags (v34.1) ──
    "_avail_order_flow":            {"type": "bool",  "source": "order_flow_data is not None"},
    "_avail_derivatives":           {"type": "bool",  "source": "derivatives_data is not None"},
    "_avail_binance_derivatives":   {"type": "bool",  "source": "binance_derivatives_data is not None"},
    "_avail_orderbook":             {"type": "bool",  "source": "orderbook_data is not None"},
    "_avail_mtf_4h":                {"type": "bool",  "source": "mtf_4h is not None"},
    "_avail_mtf_1d":                {"type": "bool",  "source": "mtf_1d is not None"},
    "_avail_account":               {"type": "bool",  "source": "account_context is not None"},
    "_avail_sr_zones":              {"type": "bool",  "source": "sr_zones is not None"},
    "_avail_sentiment":             {"type": "bool",  "source": "sentiment_data is not None and not degraded"},
}
# Total: ~110 features (numeric + categorical) — v29.2: full indicator×timeframe coverage


# --- Reason Tags (86 tags) ---
# Predefined vocabulary. Agents can ONLY reference these tags, never free text.

REASON_TAGS = {
    # ── Trend (Layer 1: 1D) ──
    "TREND_1D_BULLISH",         # Price > SMA200 + DI+ > DI-
    "TREND_1D_BEARISH",         # Price < SMA200 + DI- > DI+
    "TREND_1D_NEUTRAL",         # No clear direction
    "STRONG_TREND_ADX40",       # ADX_1D >= 40
    "WEAK_TREND_ADX_LOW",       # ADX_1D < 25
    "TREND_EXHAUSTION",         # ADX falling from peak
    "DI_BULLISH_CROSS",         # DI+ crossing above DI-
    "DI_BEARISH_CROSS",         # DI- crossing above DI+

    # ── Momentum (Layer 2: 4H) ──
    "MOMENTUM_4H_BULLISH",     # 4H momentum bias bullish (≥2 of: MACD>Signal, DI+>DI-, RSI>50)
    "MOMENTUM_4H_BEARISH",     # 4H momentum bias bearish (≥2 of: MACD<Signal, DI->DI+, RSI<50)
    "RSI_OVERBOUGHT",           # RSI > 70
    "RSI_OVERSOLD",             # RSI < 30
    "RSI_CARDWELL_BULL",        # RSI in 40-80 uptrend zone
    "RSI_CARDWELL_BEAR",        # RSI in 20-60 downtrend zone
    "MACD_BULLISH_CROSS",       # MACD crossing above signal
    "MACD_BEARISH_CROSS",       # MACD crossing below signal
    "MACD_HISTOGRAM_EXPANDING", # |histogram| increasing
    "MACD_HISTOGRAM_CONTRACTING",  # |histogram| decreasing
    "BB_UPPER_ZONE",            # BB position > 0.8
    "BB_LOWER_ZONE",            # BB position < 0.2
    "BB_SQUEEZE",               # BB width at local minimum
    "BB_EXPANSION",             # BB width expanding

    # ── Divergences ──
    "RSI_BULLISH_DIV_4H",
    "RSI_BEARISH_DIV_4H",
    "MACD_BULLISH_DIV_4H",
    "MACD_BEARISH_DIV_4H",
    "OBV_BULLISH_DIV_4H",
    "OBV_BEARISH_DIV_4H",
    "RSI_BULLISH_DIV_30M",
    "RSI_BEARISH_DIV_30M",
    "MACD_BULLISH_DIV_30M",
    "MACD_BEARISH_DIV_30M",
    "OBV_BULLISH_DIV_30M",      # v29.2: 30M OBV divergence
    "OBV_BEARISH_DIV_30M",      # v29.2: 30M OBV divergence

    # ── Order Flow ──
    "CVD_POSITIVE",             # CVD trend positive
    "CVD_NEGATIVE",             # CVD trend negative
    "CVD_ACCUMULATION",         # Price falling + CVD positive
    "CVD_DISTRIBUTION",         # Price rising + CVD negative
    "CVD_ABSORPTION_BUY",       # CVD negative + price flat = passive buying
    "CVD_ABSORPTION_SELL",      # CVD positive + price flat = passive selling
    "BUY_RATIO_HIGH",           # buy_ratio > 0.55
    "BUY_RATIO_LOW",            # buy_ratio < 0.45
    "OBI_BUY_PRESSURE",         # OBI weighted > 0.2
    "OBI_SELL_PRESSURE",        # OBI weighted < -0.2
    "OBI_BALANCED",             # |OBI| <= 0.2, neutral orderbook pressure
    "OBI_SHIFTING_BULLISH",     # OBI change > +20% (significant bullish shift)
    "OBI_SHIFTING_BEARISH",     # OBI change < -20% (significant bearish shift)
    "VOLUME_SURGE",             # Volume ratio > 1.5 (high relative volume)
    "VOLUME_DRY",               # Volume ratio < 0.5 (low relative volume)
    "SMA_BULLISH_CROSS_30M",    # 30M SMA20 > SMA50
    "SMA_BEARISH_CROSS_30M",    # 30M SMA20 < SMA50
    "SMA_BULLISH_CROSS_4H",    # v29.2: 4H SMA20 > SMA50
    "SMA_BEARISH_CROSS_4H",    # v29.2: 4H SMA20 < SMA50
    "EMA_BULLISH_CROSS_4H",    # v29.2: 4H EMA12 > EMA26
    "EMA_BEARISH_CROSS_4H",    # v29.2: 4H EMA12 < EMA26
    "MACD_1D_BULLISH",         # v29.2: 1D MACD > Signal
    "MACD_1D_BEARISH",         # v29.2: 1D MACD < Signal
    "TAKER_BUY_DOMINANT",       # Taker buy ratio > 0.55
    "TAKER_SELL_DOMINANT",      # Taker buy ratio < 0.45

    # ── Derivatives ──
    "FR_FAVORABLE_LONG",        # FR negative (pays longs)
    "FR_FAVORABLE_SHORT",       # FR positive (pays shorts)
    "FR_ADVERSE_LONG",          # FR > 0.01% (costs longs)
    "FR_ADVERSE_SHORT",         # FR < -0.01% (costs shorts)
    "FR_EXTREME",               # |FR| > 0.05%
    "FR_TREND_RISING",          # Funding rate trend rising
    "FR_TREND_FALLING",         # Funding rate trend falling
    "PREMIUM_POSITIVE",         # Futures premium > 0.05% (bullish demand)
    "PREMIUM_NEGATIVE",         # Futures discount < -0.05% (bearish demand)
    "OI_LONG_OPENING",          # OI rising + CVD positive
    "OI_SHORT_OPENING",         # OI rising + CVD negative
    "OI_LONG_CLOSING",          # OI falling + CVD negative
    "OI_SHORT_CLOSING",         # OI falling + CVD positive
    "LIQUIDATION_CASCADE_LONG", # Long liquidations dominant
    "LIQUIDATION_CASCADE_SHORT",  # Short liquidations dominant
    "TOP_TRADERS_LONG_BIAS",    # Top traders L/S > 0.55
    "TOP_TRADERS_SHORT_BIAS",   # Top traders L/S < 0.45

    # ── S/R Zones ──
    "NEAR_STRONG_SUPPORT",      # Within 3 ATR of support zone
    "NEAR_STRONG_RESISTANCE",   # Within 3 ATR of resistance zone
    "SR_BREAKOUT_POTENTIAL",    # Price testing S/R with momentum
    "SR_REJECTION",             # Price rejected at S/R
    "SR_TRAPPED",               # Between S and R with < 2 ATR spread
    "SR_CLEAR_SPACE",           # Far from both S and R

    # ── Risk Signals ──
    "EXTENSION_NORMAL",         # Extension ratio within normal range (NORMAL/EXTENDED)
    "EXTENSION_OVEREXTENDED",   # 30M: 3-5 ATR from SMA
    "EXTENSION_EXTREME",        # 30M: >5 ATR from SMA
    "EXTENSION_4H_OVEREXTENDED",  # v29.2: 4H 3-5 ATR from SMA
    "EXTENSION_4H_EXTREME",      # v29.2: 4H >5 ATR from SMA
    "EXTENSION_1D_OVEREXTENDED",  # v29.2: 1D 3-5 ATR from SMA200
    "EXTENSION_1D_EXTREME",      # v29.2: 1D >5 ATR from SMA200
    "VOL_EXTREME",              # 30M: >90th percentile volatility
    "VOL_HIGH",                 # 30M: >70th percentile volatility
    "VOL_LOW",                  # 30M: <30th percentile volatility
    "VOL_4H_HIGH",              # v29.2: 4H >70th percentile volatility
    "VOL_4H_EXTREME",           # v29.2: 4H >90th percentile volatility
    "VOL_4H_LOW",               # v29.2: 4H <30th percentile volatility
    "VOL_1D_HIGH",              # v29.2: 1D >70th percentile volatility
    "VOL_1D_EXTREME",           # v29.2: 1D >90th percentile volatility
    "VOL_1D_LOW",               # v29.2: 1D <30th percentile volatility
    "LIQUIDITY_THIN",           # Slippage > 50bps or thin orderbook
    "LIQUIDATION_BUFFER_LOW",   # Buffer 5-10%
    "LIQUIDATION_BUFFER_CRITICAL",  # Buffer < 5%
    "SLIPPAGE_HIGH",            # Expected slippage elevated

    # ── Sentiment ──
    "SENTIMENT_CROWDED_LONG",   # Long ratio > 0.60
    "SENTIMENT_CROWDED_SHORT",  # Short ratio > 0.60
    "SENTIMENT_EXTREME",        # Either ratio > 0.70
    "SENTIMENT_NEUTRAL",        # Both ratios <= 0.60, balanced sentiment

    # ── Memory Lesson Tags (used in _memory[].key_lesson_tags) ──
    "LATE_ENTRY",               # Entered after optimal timing window
    "EARLY_ENTRY",              # Entered before confirmation
    "TREND_ALIGNED",            # Trade was aligned with 1D trend
    "COUNTER_TREND_WIN",        # Counter-trend trade that succeeded
    "COUNTER_TREND_LOSS",       # Counter-trend trade that failed
    "SL_TOO_TIGHT",             # Stop loss triggered prematurely
    "SL_TOO_WIDE",              # Stop loss allowed excessive loss
    "TP_TOO_GREEDY",            # Take profit never reached, reversed
    "WRONG_DIRECTION",          # Fundamentally wrong direction call
    "CORRECT_THESIS",           # Analysis was correct, execution good
    "OVEREXTENDED_ENTRY",       # Entered at extension extreme
    "FR_IGNORED",               # Ignored funding rate pressure
    "LOW_VOLUME_ENTRY",         # Entered on thin volume/liquidity
    "DIVERGENCE_CONFIRMED",     # Divergence signal confirmed by price
}

# Direction-specific tag subsets for debate integrity validation.
# Used to detect when Bear agent copies Bull output (or vice versa).
BULLISH_EVIDENCE_TAGS = {
    "TREND_1D_BULLISH", "DI_BULLISH_CROSS", "TREND_ALIGNED",
    "FR_FAVORABLE_LONG", "MACD_BULLISH_CROSS", "RSI_CARDWELL_BULL",
    "MOMENTUM_4H_BULLISH",
    "RSI_BULLISH_DIV_4H", "RSI_BULLISH_DIV_30M",
    "MACD_BULLISH_DIV_4H", "MACD_BULLISH_DIV_30M",
    "OBV_BULLISH_DIV_4H", "OBV_BULLISH_DIV_30M",
    "CVD_POSITIVE", "CVD_ACCUMULATION",
    "BUY_RATIO_HIGH", "OBI_BUY_PRESSURE", "OBI_SHIFTING_BULLISH",
    "OI_LONG_OPENING", "TOP_TRADERS_LONG_BIAS", "TAKER_BUY_DOMINANT",
    "NEAR_STRONG_SUPPORT", "SMA_BULLISH_CROSS_30M", "SMA_BULLISH_CROSS_4H",
    "EMA_BULLISH_CROSS_4H", "MACD_1D_BULLISH", "PREMIUM_POSITIVE",
}

BEARISH_EVIDENCE_TAGS = {
    "TREND_1D_BEARISH", "DI_BEARISH_CROSS",
    "FR_FAVORABLE_SHORT", "MACD_BEARISH_CROSS", "RSI_CARDWELL_BEAR",
    "MOMENTUM_4H_BEARISH",
    "RSI_BEARISH_DIV_4H", "RSI_BEARISH_DIV_30M",
    "MACD_BEARISH_DIV_4H", "MACD_BEARISH_DIV_30M",
    "OBV_BEARISH_DIV_4H", "OBV_BEARISH_DIV_30M",
    "CVD_NEGATIVE", "CVD_DISTRIBUTION",
    "BUY_RATIO_LOW", "OBI_SELL_PRESSURE", "OBI_SHIFTING_BEARISH",
    "OI_SHORT_OPENING", "TOP_TRADERS_SHORT_BIAS", "TAKER_SELL_DOMINANT",
    "NEAR_STRONG_RESISTANCE", "SMA_BEARISH_CROSS_30M", "SMA_BEARISH_CROSS_4H",
    "EMA_BEARISH_CROSS_4H", "MACD_1D_BEARISH", "PREMIUM_NEGATIVE",
}


# --- Output Schemas (Dual-Channel: tags for machine + free-text for human) ---

BULL_SCHEMA = {
    "required_keys": {
        "reasoning":      str,    # Chain-of-thought analysis BEFORE selecting tags (audit trail)
        "evidence":       list,   # List of REASON_TAGS supporting LONG
        "risk_flags":     list,   # List of REASON_TAGS threatening LONG thesis
        "conviction":     float,  # 0.0-1.0, overall bull conviction
        "summary":        str,    # 1-2 sentence human-readable argument (for debate_summary)
    },
    "valid_values": {
        "evidence":       REASON_TAGS,
        "risk_flags":     REASON_TAGS,
    },
    "constraints": {
        "conviction":     {"min": 0.0, "max": 1.0},
        "evidence":       {"min_items": 1, "max_items": 10},
        "risk_flags":     {"min_items": 0, "max_items": 5},
        "reasoning":      {"max_length": 1500},
        "summary":        {"max_length": 800},
    },
}

BEAR_SCHEMA = {
    "required_keys": {
        "reasoning":      str,    # Chain-of-thought analysis BEFORE selecting tags (audit trail)
        "evidence":       list,   # List of REASON_TAGS supporting SHORT/caution
        "risk_flags":     list,   # List of REASON_TAGS threatening bear thesis
        "conviction":     float,  # 0.0-1.0, overall bear conviction
        "summary":        str,    # 1-2 sentence human-readable argument (for debate_summary)
    },
    "valid_values": {
        "evidence":       REASON_TAGS,
        "risk_flags":     REASON_TAGS,
    },
    "constraints": {
        "conviction":     {"min": 0.0, "max": 1.0},
        "evidence":       {"min_items": 1, "max_items": 10},
        "risk_flags":     {"min_items": 0, "max_items": 5},
        "reasoning":      {"max_length": 1500},
        "summary":        {"max_length": 800},
    },
}

JUDGE_SCHEMA = {
    "required_keys": {
        "reasoning":          str,  # Chain-of-thought: confluence analysis before decision
        "confluence": {
            "trend_1d":       str,  # BULLISH|BEARISH|NEUTRAL
            "momentum_4h":    str,
            "levels_30m":     str,
            "derivatives":    str,
            "aligned_layers": int,  # 0-4
        },
        "decision":           str,  # LONG|SHORT|HOLD
        "winning_side":       str,  # BULL|BEAR|TIE
        "confidence":         str,  # HIGH|MEDIUM|LOW
        "decisive_reasons":   list,  # Top REASON_TAGS that drove decision (machine)
        "acknowledged_risks": list,  # Top risk REASON_TAGS (machine)
        "rationale":          str,  # 2-4 sentence explanation (human — Web API, RM prompt, memory)
        "strategic_actions":  list,  # 1-3 brief actions (human — RM prompt, logging)
    },
    "valid_values": {
        "decision":           {"LONG", "SHORT", "HOLD"},
        "confidence":         {"HIGH", "MEDIUM", "LOW"},
        "winning_side":       {"BULL", "BEAR", "TIE"},
        "decisive_reasons":   REASON_TAGS,
        "acknowledged_risks": REASON_TAGS,
        # Nested dict enum validation for confluence sub-fields
        "confluence": {
            "trend_1d":       {"BULLISH", "BEARISH", "NEUTRAL"},
            "momentum_4h":    {"BULLISH", "BEARISH", "NEUTRAL"},
            "levels_30m":     {"BULLISH", "BEARISH", "NEUTRAL"},
            "derivatives":    {"BULLISH", "BEARISH", "NEUTRAL"},
        },
    },
    "constraints": {
        "confluence":         {"aligned_layers": {"min": 0, "max": 4}},
        "decisive_reasons":   {"min_items": 1, "max_items": 5},
        "acknowledged_risks": {"min_items": 1, "max_items": 5},
        "reasoning":          {"max_length": 1500},
        "rationale":          {"max_length": 800},
        "strategic_actions":  {"min_items": 1, "max_items": 3, "item_max_length": 100},
    },
}

ENTRY_TIMING_SCHEMA = {
    "required_keys": {
        "reasoning":            str,  # Chain-of-thought: 4-dimension timing evaluation
        "timing_verdict":       str,  # ENTER|REJECT
        "timing_quality":       str,  # OPTIMAL|GOOD|FAIR|POOR
        "adjusted_confidence":  str,  # HIGH|MEDIUM|LOW (can only decrease)
        "counter_trend_risk":   str,  # NONE|LOW|HIGH|EXTREME
        "alignment":            str,  # STRONG|MODERATE|WEAK
        "decisive_reasons":     list,  # REASON_TAGS driving verdict (machine)
        "reason":               str,  # 1-2 sentence explanation (human — _timing_assessment, logging)
    },
    "valid_values": {
        "timing_verdict":       {"ENTER", "REJECT"},
        "timing_quality":       {"OPTIMAL", "GOOD", "FAIR", "POOR"},
        "adjusted_confidence":  {"HIGH", "MEDIUM", "LOW"},
        "counter_trend_risk":   {"NONE", "LOW", "HIGH", "EXTREME"},
        "alignment":            {"STRONG", "MODERATE", "WEAK"},
        "decisive_reasons":     REASON_TAGS,
    },
    "constraints": {
        "decisive_reasons":     {"min_items": 1, "max_items": 5},
        "reasoning":            {"max_length": 1500},
        "reason":               {"max_length": 800},
    },
}

RISK_SCHEMA = {
    "required_keys": {
        "reasoning":            str,  # Chain-of-thought: risk assessment before decision
        "signal":               str,  # LONG|SHORT|CLOSE|HOLD|REDUCE
        "risk_appetite":        str,  # AGGRESSIVE|NORMAL|CONSERVATIVE
        "position_risk":        str,  # FULL_SIZE|REDUCED|MINIMAL|REJECT
        "market_structure_risk": str,  # NORMAL|ELEVATED|HIGH|EXTREME
        "risk_factors":         list,  # REASON_TAGS for active risks (machine)
        "reason":               str,  # 2-3 sentence explanation (human — Telegram, logging)
    },
    "valid_values": {
        "signal":               {"LONG", "SHORT", "CLOSE", "HOLD", "REDUCE"},
        "risk_appetite":        {"AGGRESSIVE", "NORMAL", "CONSERVATIVE"},
        "position_risk":        {"FULL_SIZE", "REDUCED", "MINIMAL", "REJECT"},
        "market_structure_risk": {"NORMAL", "ELEVATED", "HIGH", "EXTREME"},
        "risk_factors":         REASON_TAGS,
    },
    "constraints": {
        "reasoning":            {"max_length": 1500},
        "reason":               {"max_length": 800},
    },
}


# --- Prompt Registry (for AB Testing) ---
# Each entry is a partial dict — only override agents being tested.
# analyze_from_features(prompt_version="v27.1-shorter-judge") merges with current.

PROMPT_REGISTRY = {
    # "current" = baseline reference.  Empty dict means use live
    # _build_*_feature_system_prompt() methods (same as no override).
    "current": {},
    #
    # "v27.0-baseline" = frozen reference of v27.0 prompts.
    # Empty dict means "use live builders" — the hash of the source code
    # at v27.0 release serves as the identity.  To actually freeze prompt
    # TEXT for cross-version comparison, populate the keys below with the
    # full system prompt strings.
    #
    # Keys used by analyze_from_features():
    #   bull_system, bear_system, judge_system,
    #   entry_timing_system, risk_system
    "v27.0-baseline": {},
    #
    # To run AB test:
    #   python3 scripts/replay_ab_compare.py \
    #       --snapshot data/feature_snapshots/2026-03-06T12-00-00.json \
    #       --version-a current --version-b v27.0-baseline \
    #       --seed 42
    #
    # To register a new variant with actual prompt overrides:
    #   "v28.0-experiment": {
    #       "bull_system": "You are a Bull Analyst (v28 revised)...",
    #       "judge_system": "You are the Judge (v28 revised)...",
    #   }
}


def get_prompt_version_hash(version_key: str = "current") -> str:
    """Compute a deterministic hash for a registered prompt version.

    For 'current' or missing keys, returns a hash of the prompt builder
    source code (proxy for the live prompts).
    """
    if version_key in PROMPT_REGISTRY and PROMPT_REGISTRY[version_key]:
        # Hash the overridden prompt strings
        parts = "".join(sorted(
            f"{k}:{v}" for k, v in PROMPT_REGISTRY[version_key].items()
        ))
        return compute_prompt_version(parts)
    # Hash the source code of the build functions (proxy for "current")
    import inspect
    # Lazy import to avoid circular dependency
    try:
        from agents.multi_agent_analyzer import MultiAgentAnalyzer
        src = "".join(
            inspect.getsource(getattr(MultiAgentAnalyzer, f"_build_{n}_feature_system_prompt"))
            for n in ("bull", "bear", "judge", "et", "risk")
        )
        return compute_prompt_version(src)
    except Exception:
        return "unknown"
