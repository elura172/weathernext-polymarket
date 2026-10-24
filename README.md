# WeatherNext Polymarket: Probabilistic Pricing & Depth-Aware Execution

An institutional-grade quantitative forecasting and execution engine built for prediction market weather derivatives (Polymarket), combining **Google DeepMind's WeatherNext 3** foundation model with real-time **ICAO METAR sensor fusion** and an uncompromising **depth-aware orderbook simulation** designed to eliminate phantom maker profits.

---

## 1. Executive Summary & The Quantitative Audit

Most algorithmic prediction market strategies fail not in statistical forecasting, but in **execution modeling**. 

During the initial deployment of this platform, an unconstrained paper trading engine reported **$2,420,153.37 in simulated profit** across 108 buy and 22 sell maker orders over a 6-hour window. A rigorous quantitative audit ([`AUDIT.md`](AUDIT.md)) revealed the entire profit was a mathematical hallucination:

1. **The Phantom Maker Fill Flaw:** The naive simulator assumed maker limit orders filled immediately at the quote without consuming opposing orderbook depth or competing for queue priority. In thin prediction markets, quoting passive liquidity at 94–95¢ often encounters zero real buyer interest.
2. **Mark-to-Market Mirage:** Unfillable positions were marked at midpoints or last traded prices rather than actual executable bid liquidation value. An ask without bids has **zero liquidation value**.
3. **The Solution:** We stripped down the execution architecture and rebuilt it around strict orderbook depth-crossing:
   * **Full-Depth Book Traversal:** A simulated fill requires walking the actual snapshot of opposing resting orders. Partial fills consume available quantity at each level; remaining volume sits unfilled.
   * **Conservative Liquidation Marks:** Open inventory is marked against real bid depth. If no bids exist, positions are marked to **$0.00**.
   * **Single-Batch Asynchronous Throttling:** Strict per-cycle capital hurdles ($5 entry caps, city concentration constraints, and settlement verification against official token resolution rather than model reanalysis).

See the full post-mortem and verification records in **[`AUDIT.md`](AUDIT.md)**.

---

## 2. Quantitative Architecture

```
                       Google Earth Engine API
                                  │
                                  ▼
                     Google DeepMind WeatherNext 3
                     - 5km Hourly Surface Temp
                     - Ensemble Variance & Spread
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │               Statistical Forecasting & Sensor Fusion           │
 │  ┌─────────────────────────┐       ┌─────────────────────────┐  │
 │  │    WeatherNext 3 EE     │       │   Real-Time ICAO METAR  │  │
 │  │    (Synoptic Ensemble)  │       │   (Local Ground Truth)  │  │
 │  └────────────┬────────────┘       └────────────┬────────────┘  │
 │               │                                 │               │
 │               ▼                                 ▼               │
 │       Gaussian Mixture & Non-Stationary Shift Fitting           │
 │       - Target Day High/Low Probability Distribution            │
 │       - Dynamic Peak Offset Calibration (°F / °C)               │
 └────────────────────────────────┬────────────────────────────────┘
                                  │ Calibrated Probability Density
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │                      Strategy & Pricing Engine                  │
 │  - Integral over contract bracket $[T_{min}, T_{max}]$          │
 │  - Edge Hurdle ($\Delta P \ge 5\%$) & Minimum EV ($\ge \$0.05$) │
 │  - Fractional Kelly Position Sizing ($f^* = 0.25$)              │
 └────────────────────────────────┬────────────────────────────────┘
                                  │ Validated Orders
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │            Execution & Risk Layer (Dual-Broker Architecture)     │
 │  ┌─────────────────────────────────┐ ┌────────────────────────┐ │
 │  │  `PaperBroker` (Depth Crossing) │ │ `LiveBroker` (Polygon) │ │
 │  │  - Walks live CLOB orderbook    │ │ - Py-CLOB signing      │ │
 │  │  - Consumes depth level by level│ │ - Polygon mainnet RPC  │ │
 │  │  - Zero mark for illiquidity    │ │ - Non-custodial signer │ │
 │  └─────────────────────────────────┘ └────────────────────────┘ │
 └─────────────────────────────────────────────────────────────────┘
```

---

## 3. Mathematical Foundations

### 3.1 Probability Bracket Pricing
Polymarket weather contracts settle on whether an official airport weather station's maximum observed temperature falls into discrete intervals $[T_a, T_b]$:

$$P(\text{Token} = \text{YES}) = \int_{T_a}^{T_b} \mathcal{N}\left(t \;\middle|\; \mu_{\text{calibrated}}, \sigma_{\text{ensemble}}^2\right) dt$$

Where:
* $\mu_{\text{calibrated}} = \mu_{\text{WeatherNext}} + \Delta_{\text{METAR}} + \delta_{\text{peak}}$
* $\Delta_{\text{METAR}}$ is the empirical Kalman or exponential nowcast bias against the physical ground station over the preceding 6 hours.
* $\sigma_{\text{ensemble}}$ combines WeatherNext 3 ensemble variance with localized micro-climate uncertainty bounds.

### 3.2 Kelly Sizing with Fractional Attenuation
To protect against model miscalibration and non-Gaussian tail risk, order sizing is governed by quarter-fractional Kelly:

$$f^* = \lambda \cdot \frac{p \cdot b - q}{b}$$

Where $b = \frac{1 - \text{Ask}}{\text{Ask}}$, $p$ is the model probability, $q = 1 - p$, and $\lambda = 0.25$. 
Hard risk invariants are enforced:
* Maximum 15% single-contract exposure
* Maximum 25% single-city exposure
* 20% minimum cash liquidity reserve

---

## 4. Test Suite & Empirical Verification

The engine includes **37 unit and integration tests** verifying orderbook reconstruction, depth crossing, and execution safety invariants:

```bash
uv run pytest tests/
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.1.1, pluggy-1.6.0
rootdir: /path/to/weathernext-polymarket
collected 37 items

tests/test_backtest.py .                                                 [  2%]
tests/test_convergence.py ..                                             [  8%]
tests/test_execution_safety.py ....................                      [ 62%]
tests/test_exit.py ..                                                    [ 67%]
tests/test_nowcasting.py ....                                            [ 78%]
tests/test_paper_broker.py .                                             [ 81%]
tests/test_parser.py ..                                                  [ 86%]
tests/test_pricer.py ..                                                  [ 91%]
tests/test_resolver.py ...                                               [100%]

============================== 37 passed in 3.20s ==============================
```

Key invariant tests in [`tests/test_execution_safety.py`](tests/test_execution_safety.py):
* `test_phantom_maker_profit_eliminated`: Verifies passive maker orders cannot generate uncrossed fills.
* `test_empty_bids_marked_at_zero`: Ensures illiquid assets mark to $0.00 liquidation value.
* `test_depth_exhaustion_partial_fill`: Proves orders truncate when available book depth is consumed.
* `test_wrong_day_forecast_rejected`: Blocks execution on misaligned target date predictions.

---

## 5. Repository Structure

```
├── AUDIT.md                 # Quantitative audit post-mortem on maker fill anomalies
├── config.py                # Centralized risk parameters & environment validation
├── models.py                # Typed dataclasses for forecasts, books, and orders
├── daemon.py                # Main orchestration loop and cron scheduler
├── runner.py                # Batch execution harness
├── backtest.py              # Historical simulation runner with book reconstruction
├── forecast/
│   ├── weathernext.py       # Google Earth Engine WeatherNext 3 interface
│   ├── nowcasting.py        # ICAO METAR station parser and ground-truth bias estimator
│   ├── calibrator.py        # Gaussian mixture and bracket probability pricer
│   └── public_fallback.py   # Deterministic fallback forecast provider
├── polymarket/
│   ├── clob_client.py       # Polymarket Central Limit Order Book (CLOB) client
│   ├── gamma_client.py      # Polymarket Gamma API metadata client
│   └── parser.py            # Market schema and token bracket deserializer
├── execution/
│   ├── base_broker.py       # Abstract broker interface
│   ├── paper_broker.py      # Depth-crossing simulator with zero-marking
│   ├── live_broker.py       # On-chain / CLOB order signer and gas manager
│   └── resolver.py          # Settlement verification against final token payouts
├── strategy/
│   ├── pricer.py            # Expected value and margin-of-safety calculator
│   ├── edge.py              # Statistical edge calculation
│   ├── risk.py              # Fractional Kelly allocation and concentration caps
│   ├── convergence.py       # Time-decay spread convergence logic
│   └── exit.py              # Dynamic position liquidation and take-profit logic
├── registry/
│   └── stations.py          # Canonical mapping: City <-> Polymarket ID <-> ICAO station
└── tests/                   # 37 comprehensive unit & integration tests
```

---

## 6. Quickstart

### Installation
```bash
git clone https://github.com/elura172/weathernext-polymarket.git
cd weathernext-polymarket

# Using uv (recommended)
uv sync

# Or with standard pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running Tests
```bash
uv run pytest
```

### Running Forward Simulation
```bash
# Runs paper evaluation in depth-crossing mode
uv run python runner.py --mode PAPER
```

---

## 7. License & Attribution

Apache-2.0. Research and implementation by **[elura172](https://github.com/elura172)**. Weather models powered by Google DeepMind WeatherNext 3 via Google Earth Engine and NOAA METAR station feeds.
