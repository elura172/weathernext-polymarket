"""
Probabilistic Bracket Pricer.
Integrates continuous Gaussian probability distributions across discrete contract brackets,
incorporating station microclimates and real-time METAR nowcasting constraints.
"""
import math
from typing import List, Optional
from scipy.stats import norm
from models import WeatherContract, Bracket, MetricType, HourlyForecast
from registry.stations import resolve_station
from forecast.calibrator import ForecastCalibrator
from forecast.nowcasting import StationNowcast, MetarNowcaster

class BracketPricer:
    @staticmethod
    def price_contract_brackets(
        contract: WeatherContract,
        forecast: HourlyForecast,
        nowcast: Optional[StationNowcast] = None
    ) -> List[Bracket]:
        """
        Computes fair model probability for every bracket in the contract.
        Incorporate station microclimates, METAR nowcasts, and physical boundary pruning.
        Ensures probabilities integrate to 1.0.
        """
        station = resolve_station(contract.station_icao) or resolve_station(contract.city)

        mu, sigma = ForecastCalibrator.calibrate_target_distribution(
            forecast, contract.metric, contract.unit, station=station, nowcast=nowcast
        )

        raw_probs = []
        for b in contract.brackets:
            # Lower & upper CDF
            p_low = 0.0 if math.isinf(b.min_temp) and b.min_temp < 0 else norm.cdf(b.min_temp, loc=mu, scale=sigma)
            p_high = 1.0 if math.isinf(b.max_temp) and b.max_temp > 0 else norm.cdf(b.max_temp, loc=mu, scale=sigma)
            prob = max(0.0, float(p_high - p_low))

            # Apply METAR physical boundary check
            if nowcast:
                is_valid, veto_msg = MetarNowcaster.evaluate_bracket_validity(contract, b, nowcast)
                if not is_valid:
                    prob = 0.0
                    b.veto_reason = veto_msg
                else:
                    b.veto_reason = None
            else:
                b.veto_reason = None

            raw_probs.append(prob)

        # Normalize so sum(P) == 1.0
        total = sum(raw_probs)
        if total > 0:
            norm_probs = [p / total for p in raw_probs]
        else:
            norm_probs = [1.0 / len(raw_probs)] * len(raw_probs)

        for b, p in zip(contract.brackets, norm_probs):
            b.model_prob = p

        return contract.brackets

