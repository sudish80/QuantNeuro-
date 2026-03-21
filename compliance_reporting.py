"""
PHASE 4 MODULE 9: Compliance & Regulatory Reporting
===================================================

SEC Form 4/13F reporting, Dodd-Frank compliance, best execution monitoring,
and immutable audit trail generation for institutional trading.

Author: QuantNeuro Trading System
Version: 4.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, date
from enum import Enum
import json
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class TransactionType(Enum):
    """SEC Form 4 transaction types"""
    OPEN_MARKET_PURCHASE = "P"  # Open market purchase
    OPEN_MARKET_SALE = "S"  # Open market sale
    OPTION_GRANT = "M"  # Option grant
    OPTION_EXERCISE = "X"  # Option exercise
    DERIVATIVE_GRANT = "D"  # Derivative grant
    OTHER = "?  "  # Other


class ReportingStatus(Enum):
    """Regulatory reporting status"""
    NOT_REQUIRED = "not_required"
    DRAFT = "draft"
    READY_FOR_FILING = "ready"
    FILED = "filed"
    AMENDED = "amended"


@dataclass
class Trade:
    """Trade record for compliance reporting"""
    trade_id: str
    symbol: str
    qty: int
    price: float
    direction: str  # BUY or SELL
    timestamp: datetime
    order_id: str
    broker_code: str
    execution_price: float
    execution_venue: str
    order_type: str  # MARKET, LIMIT, etc.
    limit_price: Optional[float] = None
    arrival_price: Optional[float] = None


@dataclass
class Position:
    """Position for Form 13F reporting"""
    symbol: str
    cusip: str
    quantity: int
    market_value: float
    price_per_share: float
    reporting_date: date


@dataclass
class BestExecutionAnalysis:
    """Best execution analysis for each trade"""
    trade_id: str
    symbol: str
    direction: str
    qty: int
    order_price: float
    execution_price: float
    arrival_price: float
    price_improvement: float  # Positive = better execution
    price_improvement_pct: float
    vs_vwap: float  # vs volume-weighted avg price
    vs_twap: float  # vs time-weighted avg price
    market_condition: str
    order_complexity: str
    passing: bool  # Meets best execution standard?


@dataclass
class ComplianceViolation:
    """Detected compliance violation"""
    violation_id: str
    violation_type: str  # "concentration", "leverage", "position_limit", etc.
    severity: str  # "info", "warning", "critical"
    symbol: Optional[str]
    value: float
    limit: float
    current_timestamp: datetime
    description: str


@dataclass
class AuditEntry:
    """Immutable audit trail entry"""
    entry_id: str
    timestamp: datetime
    user_id: str
    action: str
    entity_type: str  # "trade", "position", "order", "setting", etc.
    entity_id: str
    old_value: Optional[str]
    new_value: Optional[str]
    reason: str  # Why the change
    ip_address: str
    system: str  # "TradingEngine", "PortfolioManager", etc.
    hash_previous: str  # Hash chain for immutability
    hash_self: str  # SHA256 hash of this record


# ============================================================================
# FORM 4 REPORTING (INSIDER TRADING)
# ============================================================================

class Form4Reporter:
    """
    SEC Form 4 reporting for insider trading disclosure.
    Reports officers/directors/major shareholders (>10% ownership).
    """
    
    FORM4_FIELDS = [
        "cik", "entityName", "tradingSymbol", "transactionDate",
        "transactionType", "shares", "pricePerShare", "totalValue"
    ]
    
    def __init__(self, firm_cik: str, firm_name: str):
        self.firm_cik = firm_cik
        self.firm_name = firm_name
        self.filings: List[Dict] = []
    
    def report_transaction(self, insiders: List[Dict], trades: List[Trade],
                          acquisition_date: date) -> Dict:
        """
        Generate Form 4 filing for insider transaction
        
        Args:
            insiders: List of {"name": str, "cik": str, "title": str, "ownership_pct": float}
            trades: List of Trade objects
            acquisition_date: Date of acquisition
        
        Returns:
            Form 4 filing dict ready for SEC submission
        """
        filing = {
            "form_type": "4",
            "firm_cik": self.firm_cik,
            "firm_name": self.firm_name,
            "acquisition_date": acquisition_date.isoformat(),
            "submitted_date": datetime.now().isoformat(),
            "insiders": [],
            "transactions": []
        }
        
        # Add insider information
        for insider in insiders:
            filing["insiders"].append({
                "name": insider["name"],
                "cik": insider["cik"],
                "title": insider["title"],
                "ownership_before": insider.get("ownership_pct", 0),
                "reporting_required": insider.get("ownership_pct", 0) >= 5.0
            })
        
        # Add transactions
        for trade in trades:
            # Determine transaction type
            if trade.direction == "BUY":
                txn_type = TransactionType.OPEN_MARKET_PURCHASE
            else:
                txn_type = TransactionType.OPEN_MARKET_SALE
            
            filing["transactions"].append({
                "symbol": trade.symbol,
                "transaction_type": txn_type.value,
                "quantity": trade.qty,
                "price_per_share": trade.price,
                "total_value": trade.qty * trade.price,
                "execution_price": trade.execution_price,
                "broker_code": trade.broker_code,
                "timestamp": trade.timestamp.isoformat()
            })
        
        self.filings.append(filing)
        logger.info(f"Form 4 filing generated: {len(filing['transactions'])} transactions")
        return filing


# ============================================================================
# FORM 13F REPORTING (INSTITUTIONAL HOLDINGS)
# ============================================================================

class Form13FReporter:
    """
    SEC Form 13F reporting for institutional investment managers.
    Required for firms with >$100M in assets under management.
    """
    
    REQUIRED_FOR_AUM = 100_000_000  # $100M threshold
    
    def __init__(self, firm_cik: str, firm_name: str, aum: float):
        self.firm_cik = firm_cik
        self.firm_name = firm_name
        self.aum = aum
        self.reporting_required = aum >= self.REQUIRED_FOR_AUM
        self.filings: List[Dict] = []
    
    def generate_13f(self, positions: List[Position], quarter_end: date) -> Optional[Dict]:
        """
        Generate Form 13F filing
        
        Args:
            positions: List of Position objects
            quarter_end: Quarter-end date (03-31, 06-30, 09-30, 12-31)
        
        Returns:
            Form 13F filing dict or None if not required
        """
        if not self.reporting_required:
            logger.warning("Form 13F not required - AUM below $100M threshold")
            return None
        
        filing = {
            "form_type": "13F",
            "firm_cik": self.firm_cik,
            "firm_name": self.firm_name,
            "quarter_end": quarter_end.isoformat(),
            "submitted_date": datetime.now().isoformat(),
            "aum": self.aum,
            "positions": [],
            "summary": {}
        }
        
        # Add positions
        total_value = 0
        symbols_held = set()
        
        for position in sorted(positions, key=lambda x: x.market_value, reverse=True):
            if position.market_value >= 200_000:  # SEC filing threshold
                filing["positions"].append({
                    "symbol": position.symbol,
                    "cusip": position.cusip,
                    "quantity": position.quantity,
                    "market_value": position.market_value,
                    "price_per_share": position.price_per_share,
                    "pct_of_portfolio": position.market_value / total_value if total_value > 0 else 0
                })
                total_value += position.market_value
                symbols_held.add(position.symbol)
        
        # Summary
        filing["summary"] = {
            "total_positions": len(filing["positions"]),
            "total_market_value": total_value,
            "avg_position_size": total_value / len(filing["positions"]) if filing["positions"] else 0,
            "top_3_positions": [p["symbol"] for p in filing["positions"][:3]],
            "portfolio_concentration": sum([p["market_value"]**2 for p in filing["positions"]]) / (total_value**2) if total_value > 0 else 0
        }
        
        self.filings.append(filing)
        logger.info(f"Form 13F generated: {len(filing['positions'])} positions, ${total_value:,.0f} value")
        return filing


# ============================================================================
# DODD-FRANK COMPLIANCE
# ============================================================================

class DoddFrankCompliance:
    """
    Dodd-Frank Act compliance monitoring:
    - Volcker Rule: Proprietary trading prohibitions
    - Position limits: Enforcement
    - Leverage limits: Monitor capital adequacy
    - Conflicts of interest: Track and disclose
    """
    
    def __init__(self):
        self.violations: List[ComplianceViolation] = []
        self.position_history: Dict[str, List[Tuple[date, int]]] = defaultdict(list)
        
        # Compliance limits
        self.POSITION_LIMIT_PCT = 0.10  # 10% of outstanding shares
        self.LEVERAGE_LIMIT = 3.0  # 3x leverage max
        self.SECTOR_CONCENTRATION_LIMIT = 0.30  # 30% max in one sector
    
    def check_position_limits(self, symbol: str, qty: int, total_outstanding: int,
                             sector: str, sector_value: float, total_portfolio: float) -> bool:
        """
        Check if position violates SEC position limits
        
        Returns:
            True if compliant, False if violation
        """
        position_pct = qty / total_outstanding if total_outstanding > 0 else 0
        sector_pct = sector_value / total_portfolio if total_portfolio > 0 else 0
        
        violations = []
        
        if position_pct > self.POSITION_LIMIT_PCT:
            violations.append(ComplianceViolation(
                violation_id=f"POS_{symbol}_{datetime.now().timestamp()}",
                violation_type="position_limit",
                severity="critical",
                symbol=symbol,
                value=qty,
                limit=int(total_outstanding * self.POSITION_LIMIT_PCT),
                current_timestamp=datetime.now(),
                description=f"Position exceeds {self.POSITION_LIMIT_PCT:.1%} limit: {position_pct:.2%}"
            ))
        
        if sector_pct > self.SECTOR_CONCENTRATION_LIMIT:
            violations.append(ComplianceViolation(
                violation_id=f"SEC_{sector}_{datetime.now().timestamp()}",
                violation_type="sector_concentration",
                severity="warning",
                symbol=sector,
                value=sector_value,
                limit=total_portfolio * self.SECTOR_CONCENTRATION_LIMIT,
                current_timestamp=datetime.now(),
                description=f"Sector concentration exceeds {self.SECTOR_CONCENTRATION_LIMIT:.1%}: {sector_pct:.2%}"
            ))
        
        self.violations.extend(violations)
        return len(violations) == 0
    
    def check_leverage(self, equity: float, liabilities: float) -> bool:
        """Check leverage ratio"""
        leverage = (equity + liabilities) / equity if equity > 0 else 0
        
        if leverage > self.LEVERAGE_LIMIT:
            self.violations.append(ComplianceViolation(
                violation_id=f"LEV_{datetime.now().timestamp()}",
                violation_type="leverage_limit",
                severity="critical",
                symbol=None,
                value=leverage,
                limit=self.LEVERAGE_LIMIT,
                current_timestamp=datetime.now(),
                description=f"Leverage ratio {leverage:.2f}x exceeds {self.LEVERAGE_LIMIT:.1f}x limit"
            ))
            return False
        return True


# ============================================================================
# BEST EXECUTION MONITORING
# ============================================================================

class BestExecutionMonitor:
    """
    Monitor best execution requirements:
    - Execution quality vs. arrival price
    - Price improvement tracking
    - Venue analysis
    - Market condition categorization
    """
    
    # Price improvement thresholds (bps = basis points)
    MIN_IMPROVEMENT_BPS = 1.0  # Expecting at least 1bp improvement
    VWAP_TOLERANCE_BPS = 2.0  # 2bp tolerance vs VWAP
    
    def __init__(self):
        self.analyses: List[BestExecutionAnalysis] = []
    
    def analyze_execution(self, trade: Trade, market_benchmarks: Dict[str, float]) -> BestExecutionAnalysis:
        """
        Analyze execution quality
        
        Args:
            trade: Trade object
            market_benchmarks: {"arrival_price": float, "vwap": float, "twap": float}
        
        Returns:
            BestExecutionAnalysis
        """
        arrival_price = market_benchmarks.get("arrival_price", trade.order_type)
        vwap = market_benchmarks.get("vwap", trade.execution_price)
        twap = market_benchmarks.get("twap", trade.execution_price)
        
        # Calculate price improvement
        if trade.direction == "BUY":
            improvement = arrival_price - trade.execution_price
            vs_vwap = vwap - trade.execution_price
            vs_twap = twap - trade.execution_price
        else:  # SELL
            improvement = trade.execution_price - arrival_price
            vs_vwap = trade.execution_price - vwap
            vs_twap = trade.execution_price - twap
        
        improvement_pct = improvement / arrival_price if arrival_price > 0 else 0
        
        # Determine if execution passes best execution standard
        passing = improvement_pct >= (self.MIN_IMPROVEMENT_BPS / 10000) or abs(vs_vwap) <= (self.VWAP_TOLERANCE_BPS / 10000)
        
        analysis = BestExecutionAnalysis(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            direction=trade.direction,
            qty=trade.qty,
            order_price=trade.limit_price or arrival_price,
            execution_price=trade.execution_price,
            arrival_price=arrival_price,
            price_improvement=improvement,
            price_improvement_pct=improvement_pct,
            vs_vwap=vs_vwap,
            vs_twap=vs_twap,
            market_condition="normal",  # Can be categorized from market data
            order_complexity="standard",
            passing=passing
        )
        
        self.analyses.append(analysis)
        return analysis


# ============================================================================
# IMMUTABLE AUDIT TRAIL
# ============================================================================

class AuditTrail:
    """
    Immutable audit trail for all trading and compliance decisions.
    Uses hash chain for tamper-evidence.
    """
    
    def __init__(self):
        self.entries: List[AuditEntry] = []
        self.last_hash = "GENESIS"
    
    def add_entry(self, entry_id: str, user_id: str, action: str,
                 entity_type: str, entity_id: str, new_value: str,
                 reason: str, ip_address: str = "127.0.0.1",
                 system: str = "TradingEngine",
                 old_value: Optional[str] = None) -> AuditEntry:
        """
        Add entry to immutable audit trail
        
        Returns:
            AuditEntry added
        """
        import hashlib
        
        # Create entry
        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=datetime.now(),
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            ip_address=ip_address,
            system=system,
            hash_previous=self.last_hash,
            hash_self=""  # Will be calculated
        )
        
        # Calculate hash
        entry_str = f"{entry.timestamp}{entry.user_id}{entry.action}{entry.entity_type}{entry.new_value}{self.last_hash}"
        entry.hash_self = hashlib.sha256(entry_str.encode()).hexdigest()
        
        self.entries.append(entry)
        self.last_hash = entry.hash_self
        
        logger.info(f"Audit: {action} on {entity_type} {entity_id} by {user_id}")
        return entry
    
    def verify_integrity(self) -> bool:
        """Verify audit trail integrity (hash chain unbroken)"""
        if not self.entries:
            return True
        
        current_hash = "GENESIS"
        for entry in self.entries:
            if entry.hash_previous != current_hash:
                logger.error(f"Audit trail integrity compromised at {entry.entry_id}")
                return False
            current_hash = entry.hash_self
        
        return True
    
    def get_entry_history(self, entity_type: str, entity_id: str) -> List[AuditEntry]:
        """Get audit history for specific entity"""
        return [e for e in self.entries 
                if e.entity_type == entity_type and e.entity_id == entity_id]


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Form 4 reporting
    form4 = Form4Reporter(cik="0001018724", firm_name="QuantNeuro Trading")
    
    trades = [
        Trade(
            trade_id="T1", symbol="AAPL", qty=10000, price=175.50,
            direction="BUY", timestamp=datetime.now(),
            order_id="O1", broker_code="GS",
            execution_price=175.48, execution_venue="NYSE"
        )
    ]
    
    filing = form4.report_transaction(
        insiders=[{"name": "John Doe", "cik": "123456", "title": "CEO", "ownership_pct": 5.5}],
        trades=trades,
        acquisition_date=date.today()
    )
    print("Form 4 Filing Generated:")
    print(f"  Transactions: {len(filing['transactions'])}")
    print()
    
    # Form 13F reporting
    form13f = Form13FReporter(cik="0001018724", firm_name="QuantNeuro Trading", aum=500_000_000)
    
    positions = [
        Position(symbol="AAPL", cusip="037833100", quantity=500000, market_value=87_500_000,
                price_per_share=175.00, reporting_date=date(2024, 3, 31)),
        Position(symbol="MSFT", cusip="594918104", quantity=300000, market_value=105_000_000,
                price_per_share=350.00, reporting_date=date(2024, 3, 31))
    ]
    
    filing13f = form13f.generate_13f(positions, date(2024, 3, 31))
    if filing13f:
        print("Form 13F Filing Generated:")
        print(f"  Positions: {len(filing13f['positions'])}")
        print(f"  Total Value: ${filing13f['summary']['total_market_value']:,.0f}")
        print()
    
    # Dodd-Frank compliance
    dodd_frank = DoddFrankCompliance()
    compliant = dodd_frank.check_position_limits(
        symbol="AAPL", qty=500000, total_outstanding=16_000_000_000,
        sector="Technology", sector_value=200_000_000, total_portfolio=500_000_000
    )
    print(f"Position Limits Compliance: {'PASS' if compliant else 'FAIL'}")
    print()
    
    # Best execution
    best_exec = BestExecutionMonitor()
    analysis = best_exec.analyze_execution(
        trade=trades[0],
        market_benchmarks={"arrival_price": 175.50, "vwap": 175.49, "twap": 175.48}
    )
    print("Best Execution Analysis:")
    print(f"  Price Improvement: ${analysis.price_improvement:.4f} ({analysis.price_improvement_pct:.2%})")
    print(f"  Passing: {analysis.passing}")
    print()
    
    # Audit trail
    audit = AuditTrail()
    audit.add_entry(
        entry_id="AUD1",
        user_id="trader_001",
        action="TRADE_EXECUTED",
        entity_type="trade",
        entity_id="T1",
        new_value="AAPL 10000@175.48",
        reason="Signal from momentum model",
        system="TradingEngine"
    )
    print(f"Audit Trail Integrity: {'VALID' if audit.verify_integrity() else 'COMPROMISED'}")
    print(f"Audit Entries: {len(audit.entries)}")
