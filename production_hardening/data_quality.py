"""
Data quality layer with validation, outlier detection, and quality scoring.

Provides:
- Schema validation for market data
- Outlier detection (statistical and domain-based)
- Missing data policies
- Market hours sanity checks
- Data quality scoring per ticker
- Quality gates for inference blocking
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================


class DataQualityStatus(str, Enum):
    """Data quality status."""
    GOOD = "GOOD"
    WARN = "WARN"
    POOR = "POOR"
    BLOCKED = "BLOCKED"


@dataclass
class DataQualityReport:
    """Report on data quality for a ticker."""
    ticker: str
    status: DataQualityStatus
    quality_score: float  # 0-100
    num_records: int
    missing_pct: float
    outlier_count: int
    outlier_pct: float
    violations: List[str]
    timestamp: datetime


# ============================================================================
# SCHEMA DEFINITION
# ============================================================================

MARKET_DATA_SCHEMA = {
    "timestamp": {"type": "datetime", "required": True},
    "ticker": {"type": "str", "required": True, "pattern": r"^[A-Z0-9]{1,5}$"},
    "open": {"type": "float", "required": True, "min": 0.0},
    "high": {"type": "float", "required": True, "min": 0.0},
    "low": {"type": "float", "required": True, "min": 0.0},
    "close": {"type": "float", "required": True, "min": 0.0},
    "volume": {"type": "int", "required": True, "min": 0},
    "adj_close": {"type": "float", "required": False, "min": 0.0},
}

TRADE_DATA_SCHEMA = {
    "timestamp": {"type": "datetime", "required": True},
    "ticker": {"type": "str", "required": True},
    "side": {"type": "str", "required": True, "allowed": ["BUY", "SELL"]},
    "quantity": {"type": "float", "required": True, "min": 0.0},
    "price": {"type": "float", "required": True, "min": 0.0},
    "fee": {"type": "float", "required": False, "min": 0.0},
}


# ============================================================================
# VALIDATION ENGINE
# ============================================================================


class SchemaValidator:
    """Validates data against defined schemas."""

    def __init__(self, schema: Dict):
        self.schema = schema

    def validate_record(self, record: Dict) -> Tuple[bool, List[str]]:
        """
        Validate a single record against schema.
        Returns (is_valid, violations).
        """
        violations = []

        for field, rules in self.schema.items():
            value = record.get(field)

            # Check required fields
            if rules.get("required", False) and value is None:
                violations.append(f"Missing required field: {field}")
                continue

            if value is None and not rules.get("required", False):
                continue

            # Type checking
            expected_type = rules.get("type")
            if expected_type == "datetime":
                if not isinstance(value, (pd.Timestamp, datetime)):
                    violations.append(f"{field}: expected datetime, got {type(value)}")
            elif expected_type == "float":
                try:
                    float(value)
                except (ValueError, TypeError):
                    violations.append(f"{field}: expected float, got {value}")
            elif expected_type == "int":
                try:
                    int(value)
                except (ValueError, TypeError):
                    violations.append(f"{field}: expected int, got {value}")
            elif expected_type == "str":
                if not isinstance(value, str):
                    violations.append(f"{field}: expected str, got {type(value)}")

            # Min/max validation
            if isinstance(value, (int, float)):
                if "min" in rules and value < rules["min"]:
                    violations.append(
                        f"{field}: {value} < min {rules['min']}"
                    )
                if "max" in rules and value > rules["max"]:
                    violations.append(
                        f"{field}: {value} > max {rules['max']}"
                    )

            # Pattern validation (regex)
            if "pattern" in rules:
                import re
                if not re.match(rules["pattern"], str(value)):
                    violations.append(
                        f"{field}: {value} does not match pattern {rules['pattern']}"
                    )

            # Allowed values
            if "allowed" in rules and value not in rules["allowed"]:
                violations.append(
                    f"{field}: {value} not in allowed {rules['allowed']}"
                )

        return len(violations) == 0, violations

    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, Dict[str, List[str]]]:
        """Validate all records in dataframe."""
        all_violations = {}

        for idx, row in df.iterrows():
            is_valid, violations = self.validate_record(row.to_dict())
            if not is_valid:
                all_violations[idx] = violations

        return len(all_violations) == 0, all_violations


# ============================================================================
# OUTLIER DETECTION
# ============================================================================


class OutlierDetector:
    """Detects outliers using statistical and domain methods."""

    def __init__(self, z_score_threshold: float = 3.0, iqr_multiplier: float = 1.5):
        self.z_score_threshold = z_score_threshold
        self.iqr_multiplier = iqr_multiplier

    def detect_statistical_outliers(self, series: pd.Series) -> np.ndarray:
        """
        Detect outliers using Z-score method.
        Returns array of boolean indices.
        """
        if len(series) < 3:
            return np.zeros(len(series), dtype=bool)

        z_scores = np.abs((series - series.mean()) / series.std())
        return z_scores > self.z_score_threshold

    def detect_iqr_outliers(self, series: pd.Series) -> np.ndarray:
        """
        Detect outliers using Interquartile Range method.
        Returns array of boolean indices.
        """
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1

        lower_bound = Q1 - self.iqr_multiplier * IQR
        upper_bound = Q3 + self.iqr_multiplier * IQR

        return (series < lower_bound) | (series > upper_bound)

    def detect_price_outliers(self, df: pd.DataFrame) -> List[int]:
        """
        Detect price outliers (high/low should be between open/close bounds).
        """
        outliers = []

        for idx, row in df.iterrows():
            open_price = row.get("open")
            high_price = row.get("high")
            low_price = row.get("low")
            close_price = row.get("close")

            # Validate OHLC relationships
            if high_price < max(open_price, close_price):
                outliers.append(idx)
            if low_price > min(open_price, close_price):
                outliers.append(idx)

        return outliers

    def detect_volume_spike(self, series: pd.Series, threshold: float = 2.0) -> np.ndarray:
        """
        Detect volume spikes (volume > mean + threshold * std).
        """
        if len(series) < 2:
            return np.zeros(len(series), dtype=bool)

        mean_vol = series.mean()
        std_vol = series.std()
        spike_threshold = mean_vol + (threshold * std_vol)

        return series > spike_threshold

    def detect_gap(self, df: pd.DataFrame, threshold_pct: float = 0.05) -> List[int]:
        """
        Detect price gaps between consecutive days > threshold %.
        """
        gaps = []

        for idx in range(1, len(df)):
            prev_close = df.iloc[idx - 1]["close"]
            curr_open = df.iloc[idx]["open"]

            gap_pct = abs(curr_open - prev_close) / prev_close

            if gap_pct > threshold_pct:
                gaps.append(idx)

        return gaps


# ============================================================================
# MISSING DATA HANDLING
# ============================================================================


class MissingDataPolicy:
    """Defines policies for handling missing data."""

    @staticmethod
    def forward_fill(df: pd.DataFrame, max_fill_periods: int = 3) -> pd.DataFrame:
        """Forward fill missing values up to max_fill_periods."""
        return df.fillna(method="ffill", limit=max_fill_periods)

    @staticmethod
    def interpolate(df: pd.DataFrame, method: str = "linear") -> pd.DataFrame:
        """Interpolate missing values."""
        return df.interpolate(method=method)

    @staticmethod
    def drop_missing(df: pd.DataFrame, threshold: float = 0.1) -> pd.DataFrame:
        """
        Drop rows with missing data.
        threshold: drop column if > threshold missing fraction.
        """
        # Drop columns
        df = df.dropna(thresh=len(df) * (1 - threshold), axis=1)
        # Drop rows
        df = df.dropna(axis=0)
        return df

    @staticmethod
    def report_missing(df: pd.DataFrame) -> Dict[str, float]:
        """Report missing data percentage per column."""
        return (df.isnull().sum() / len(df)).to_dict()


# ============================================================================
# MARKET HOURS VALIDATION
# ============================================================================


class MarketHoursValidator:
    """Validates data respects market trading hours."""

    # US market hours (EST)
    US_MARKET_OPEN = time(9, 30)
    US_MARKET_CLOSE = time(16, 0)
    US_PREMARKET_OPEN = time(4, 0)
    US_AFTERHOURS_CLOSE = time(20, 0)

    # Holiday list (simplified)
    US_HOLIDAYS = {
        "2024-01-01",  # New Year
        "2024-07-04",  # Independence Day
        "2024-12-25",  # Christmas
    }

    @classmethod
    def is_market_hours(cls, timestamp: datetime) -> bool:
        """Check if timestamp falls within normal market hours."""
        ts_time = timestamp.time()
        ts_date = timestamp.date().isoformat()

        # Check holidays
        if ts_date in cls.US_HOLIDAYS:
            return False

        # Check weekends
        if timestamp.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Check time
        return cls.US_MARKET_OPEN <= ts_time <= cls.US_MARKET_CLOSE

    @classmethod
    def is_extended_hours(cls, timestamp: datetime) -> bool:
        """Check if timestamp is in pre-market or after-hours."""
        ts_time = timestamp.time()
        return (
            cls.US_PREMARKET_OPEN <= ts_time < cls.US_MARKET_OPEN
            or cls.US_MARKET_CLOSE <= ts_time < cls.US_AFTERHOURS_CLOSE
        )

    @classmethod
    def validate_timestamps(
        cls, df: pd.DataFrame, allow_extended: bool = False
    ) -> List[int]:
        """Find timestamps outside market hours."""
        violations = []

        for idx, ts in enumerate(df.get("timestamp", [])):
            if allow_extended:
                if not (cls.is_market_hours(ts) or cls.is_extended_hours(ts)):
                    violations.append(idx)
            else:
                if not cls.is_market_hours(ts):
                    violations.append(idx)

        return violations


# ============================================================================
# DATA QUALITY SCORING
# ============================================================================


class DataQualityScorer:
    """Computes overall quality score for a dataset."""

    def __init__(
        self,
        max_missing_pct: float = 0.05,
        max_outlier_pct: float = 0.02,
        min_records: int = 50,
    ):
        self.max_missing_pct = max_missing_pct
        self.max_outlier_pct = max_outlier_pct
        self.min_records = min_records

    def compute_quality_score(
        self,
        num_records: int,
        missing_pct: float,
        outlier_pct: float,
        violations: List[str],
    ) -> float:
        """
        Compute quality score (0-100).
        Based on missing data, outliers, and violations.
        """
        score = 100.0

        # Penalize missing data
        if missing_pct > 0:
            score -= min(50, missing_pct * 500)  # Lose up to 50 points

        # Penalize outliers
        if outlier_pct > 0:
            score -= min(30, outlier_pct * 300)  # Lose up to 30 points

        # Penalize violations
        score -= len(violations) * 2  # 2 points per violation

        # Penalize insufficient data
        if num_records < self.min_records:
            score -= 10

        return max(0.0, min(100.0, score))

    def get_status(self, score: float) -> DataQualityStatus:
        """Map score to status."""
        if score >= 90.0:
            return DataQualityStatus.GOOD
        elif score >= 70.0:
            return DataQualityStatus.WARN
        elif score >= 50.0:
            return DataQualityStatus.POOR
        else:
            return DataQualityStatus.BLOCKED

    def should_block_inference(self, status: DataQualityStatus) -> bool:
        """Determine if data quality is too poor for inference."""
        return status == DataQualityStatus.BLOCKED


# ============================================================================
# DATA QUALITY GATE
# ============================================================================


class DataQualityGate:
    """Comprehensive data quality validation and gating."""

    def __init__(self):
        self.schema_validator = SchemaValidator(MARKET_DATA_SCHEMA)
        self.outlier_detector = OutlierDetector()
        self.market_hours_validator = MarketHoursValidator()
        self.quality_scorer = DataQualityScorer()
        self.ticker_quality_cache = {}

    def validate_market_data(self, df: pd.DataFrame) -> DataQualityReport:
        """
        Comprehensive market data quality check.
        Returns detailed report.
        """
        ticker = df.iloc[0].get("ticker", "unknown") if len(df) > 0 else "unknown"
        violations = []

        # 1. Schema validation
        _, schema_violations = self.schema_validator.validate_dataframe(df)
        violations.extend(
            [v for vlist in schema_violations.values() for v in vlist]
        )

        # 2. Missing data analysis
        missing_report = MissingDataPolicy.report_missing(df)
        missing_pct = np.mean(list(missing_report.values()))

        # 3. Market hours validation
        market_hours_violations = self.market_hours_validator.validate_timestamps(df)
        violations.extend(
            [f"Data outside market hours: row {idx}" for idx in market_hours_violations]
        )

        # 4. Outlier detection
        outlier_indices = set()
        
        if "close" in df.columns:
            outlier_indices.update(self.outlier_detector.detect_statistical_outliers(df["close"]))
        
        if "volume" in df.columns:
            outlier_indices.update(self.outlier_detector.detect_volume_spike(df["volume"]))
        
        price_outliers = self.outlier_detector.detect_price_outliers(df)
        outlier_indices.update(price_outliers)

        gaps = self.outlier_detector.detect_gap(df)
        outlier_indices.update(gaps)

        outlier_count = len(outlier_indices)
        outlier_pct = outlier_count / len(df) if len(df) > 0 else 0.0

        # 5. Compute quality score
        quality_score = self.quality_scorer.compute_quality_score(
            num_records=len(df),
            missing_pct=missing_pct,
            outlier_pct=outlier_pct,
            violations=violations,
        )

        status = self.quality_scorer.get_status(quality_score)

        report = DataQualityReport(
            ticker=ticker,
            status=status,
            quality_score=quality_score,
            num_records=len(df),
            missing_pct=missing_pct,
            outlier_count=outlier_count,
            outlier_pct=outlier_pct,
            violations=violations if violations else ["None"],
            timestamp=datetime.utcnow(),
        )

        self.ticker_quality_cache[ticker] = report
        return report

    def should_block_inference(self, ticker: str) -> bool:
        """Check if ticker's data quality is too poor."""
        if ticker not in self.ticker_quality_cache:
            return False

        report = self.ticker_quality_cache[ticker]
        return self.quality_scorer.should_block_inference(report.status)

    def get_quality_report(self, ticker: str) -> Optional[DataQualityReport]:
        """Get cached quality report for ticker."""
        return self.ticker_quality_cache.get(ticker)

    def generate_quality_summary(self) -> str:
        """Generate human-readable summary."""
        summary = "DATA QUALITY SUMMARY\n"
        summary += "=" * 60 + "\n"

        for ticker, report in self.ticker_quality_cache.items():
            status_icon = {
                DataQualityStatus.GOOD: "✅",
                DataQualityStatus.WARN: "⚠️",
                DataQualityStatus.POOR: "❌",
                DataQualityStatus.BLOCKED: "🔴",
            }.get(report.status, "?")

            summary += f"\n{status_icon} {ticker:6} | Score: {report.quality_score:5.1f} | "
            summary += f"Records: {report.num_records:4} | "
            summary += f"Missing: {report.missing_pct:5.1%} | "
            summary += f"Outliers: {report.outlier_pct:5.1%}\n"

            if report.violations and report.violations != ["None"]:
                for violation in report.violations[:3]:  # Show first 3
                    summary += f"    • {violation}\n"

        return summary


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

data_quality_gate = DataQualityGate()
