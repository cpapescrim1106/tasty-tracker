#!/usr/bin/env python3
"""
Allocation Rules Manager
Manages portfolio allocation rules and compliance monitoring
"""

import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

class RuleType(Enum):
    ASSET = "asset"
    DURATION = "duration" 
    STRATEGY = "strategy"

class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"  
    VIOLATION = "violation"

@dataclass
class AllocationRule:
    """Individual allocation rule definition"""
    rule_type: RuleType
    category: str  # 'equities', 'bullish', '45_dte', etc.
    target_pct: float
    min_pct: float = 0.0
    max_pct: float = 100.0
    tolerance_pct: float = 2.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class ComplianceCheck:
    """Results of compliance checking"""
    rule: AllocationRule
    current_pct: float
    target_pct: float
    deviation_pct: float
    status: ComplianceStatus
    message: str

@dataclass
class AllocationGap:
    """Identified gap in portfolio allocation"""
    rule_type: RuleType
    category: str
    current_pct: float
    target_pct: float
    gap_pct: float
    required_allocation_dollars: float
    priority: int  # 1=highest, 5=lowest

class AllocationRulesManager:
    """Manages portfolio allocation rules and compliance"""
    
    def __init__(self, db_path: str = "allocation_rules.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._initialize_database()
        self._load_default_rules()
        
    def _initialize_database(self):
        """Initialize the allocation rules database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create allocation rules table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS allocation_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    max_pct REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(rule_type, category)
                )
            ''')
            
            # Create compliance history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS compliance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rule_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    current_pct REAL NOT NULL,
                    max_pct REAL NOT NULL,
                    deviation_pct REAL NOT NULL,
                    status TEXT NOT NULL,
                    total_portfolio_value REAL
                )
            ''')
            
            conn.commit()
            conn.close()
            self.logger.info("✅ Allocation rules database initialized")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize allocation rules database: {e}")
            
    def _load_default_rules(self):
        """Load default allocation rules if none exist"""
        try:
            if not self.get_all_rules():
                default_rules = [
                    # Asset Allocation
                    AllocationRule(RuleType.ASSET, "equities", target_pct=60.0, min_pct=55.0, max_pct=65.0, tolerance_pct=2.0),
                    AllocationRule(RuleType.ASSET, "non_equities", target_pct=40.0, min_pct=35.0, max_pct=45.0, tolerance_pct=2.0),
                    AllocationRule(RuleType.ASSET, "max_sector", target_pct=10.0, min_pct=0.0, max_pct=10.0, tolerance_pct=1.0),
                    
                    # Duration Diversification
                    AllocationRule(RuleType.DURATION, "0_dte", target_pct=5.0, min_pct=0.0, max_pct=8.0, tolerance_pct=1.0),
                    AllocationRule(RuleType.DURATION, "7_dte", target_pct=10.0, min_pct=5.0, max_pct=15.0, tolerance_pct=2.0),
                    AllocationRule(RuleType.DURATION, "14_dte", target_pct=15.0, min_pct=10.0, max_pct=20.0, tolerance_pct=2.0),
                    AllocationRule(RuleType.DURATION, "45_dte", target_pct=70.0, min_pct=65.0, max_pct=80.0, tolerance_pct=3.0),
                    
                    # Strategy Diversification  
                    AllocationRule(RuleType.STRATEGY, "bullish", target_pct=50.0, min_pct=40.0, max_pct=60.0, tolerance_pct=3.0),
                    AllocationRule(RuleType.STRATEGY, "neutral", target_pct=35.0, min_pct=25.0, max_pct=45.0, tolerance_pct=3.0),
                    AllocationRule(RuleType.STRATEGY, "bearish", target_pct=15.0, min_pct=10.0, max_pct=25.0, tolerance_pct=3.0)
                ]
                
                for rule in default_rules:
                    self.save_rule(rule)
                    
                self.logger.info("✅ Default allocation rules loaded")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to load default rules: {e}")
            
    def save_rule(self, rule: AllocationRule) -> bool:
        """Save or update an allocation rule"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO allocation_rules 
                (rule_type, category, target_pct, min_pct, max_pct, tolerance_pct, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                rule.rule_type.value,
                rule.category,
                rule.target_pct,
                rule.min_pct,
                rule.max_pct,
                rule.tolerance_pct,
                datetime.now()
            ))
            
            conn.commit()
            conn.close()
            self.logger.info(f"✅ Saved allocation rule: {rule.rule_type.value}/{rule.category}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to save allocation rule: {e}")
            return False
            
    def get_all_rules(self) -> List[AllocationRule]:
        """Get all allocation rules"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT rule_type, category, target_pct, min_pct, max_pct, tolerance_pct, created_at, updated_at
                FROM allocation_rules
                ORDER BY rule_type, max_pct DESC
            ''')
            
            rules = []
            for row in cursor.fetchall():
                rule = AllocationRule(
                    rule_type=RuleType(row[0]),
                    category=row[1],
                    target_pct=row[2],
                    min_pct=row[3],
                    max_pct=row[4],
                    tolerance_pct=row[5],
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                    updated_at=datetime.fromisoformat(row[7]) if row[7] else None
                )
                rules.append(rule)
                
            conn.close()
            return rules
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get allocation rules: {e}")
            return []
            
    def get_rules_by_type(self, rule_type: RuleType) -> List[AllocationRule]:
        """Get rules by specific type"""
        return [rule for rule in self.get_all_rules() if rule.rule_type == rule_type]
        
    def check_compliance(self, current_allocations: Dict[str, Any], 
                        total_portfolio_value: float) -> List[ComplianceCheck]:
        """Check current portfolio compliance against all rules"""
        compliance_results = []
        
        try:
            all_rules = self.get_all_rules()
            
            # Special case: If portfolio value is 0 (no rebalanceable positions), 
            # mark all rules as compliant since there's nothing to violate
            if total_portfolio_value == 0:
                self.logger.info("📊 No rebalanceable positions - marking all rules as compliant")
                for rule in all_rules:
                    check = ComplianceCheck(
                        rule=rule,
                        current_pct=0.0,
                        target_pct=rule.target_pct,
                        deviation_pct=-rule.target_pct,
                        status=ComplianceStatus.COMPLIANT,
                        message="No rebalanceable positions"
                    )
                    compliance_results.append(check)
                    self._save_compliance_check(check, total_portfolio_value)
                return compliance_results
            
            for rule in all_rules:
                # Get current percentage for this rule category
                current_pct = self._get_current_allocation_pct(
                    current_allocations, rule.rule_type, rule.category
                )
                
                # Calculate deviation
                deviation = current_pct - rule.target_pct
                
                # Determine compliance status
                if current_pct < rule.min_pct or current_pct > rule.max_pct:
                    status = ComplianceStatus.VIOLATION
                    message = f"Outside limits ({rule.min_pct:.1f}%-{rule.max_pct:.1f}%)"
                elif abs(deviation) > rule.tolerance_pct:
                    status = ComplianceStatus.WARNING
                    message = f"Outside tolerance (±{rule.tolerance_pct:.1f}%)"
                else:
                    status = ComplianceStatus.COMPLIANT
                    message = "Within tolerance"
                
                check = ComplianceCheck(
                    rule=rule,
                    current_pct=current_pct,
                    target_pct=rule.target_pct,
                    deviation_pct=deviation,
                    status=status,
                    message=message
                )
                
                compliance_results.append(check)
                
                # Save to compliance history
                self._save_compliance_check(check, total_portfolio_value)
                
            return compliance_results
            
        except Exception as e:
            self.logger.error(f"❌ Failed to check compliance: {e}")
            return []
            
    def identify_allocation_gaps(self, current_allocations: Dict[str, Any],
                               total_portfolio_value: float,
                               available_buying_power: float) -> List[AllocationGap]:
        """Identify gaps that need to be filled for compliance"""
        gaps = []
        
        try:
            compliance_checks = self.check_compliance(current_allocations, total_portfolio_value)
            
            for check in compliance_checks:
                if check.status in [ComplianceStatus.WARNING, ComplianceStatus.VIOLATION]:
                    # Calculate required allocation change
                    gap_pct = check.target_pct - check.current_pct
                    
                    # Create gaps for both over and under allocations (lower threshold)
                    if abs(gap_pct) > 0.5:  # Lower threshold to 0.5% for testing
                        if gap_pct > 0:
                            # Underallocated - need to open positions
                            required_dollars = (gap_pct / 100.0) * total_portfolio_value
                            required_dollars = min(required_dollars, available_buying_power)
                        else:
                            # Overallocated - need to close positions 
                            required_dollars = abs(gap_pct / 100.0) * total_portfolio_value
                        
                        # Determine priority based on severity
                        if check.status == ComplianceStatus.VIOLATION:
                            priority = 1
                        elif abs(gap_pct) > 5.0:
                            priority = 2
                        elif abs(gap_pct) > 3.0:
                            priority = 3
                        else:
                            priority = 4
                            
                        gap = AllocationGap(
                            rule_type=check.rule.rule_type,
                            category=check.rule.category,
                            current_pct=check.current_pct,
                            target_pct=check.target_pct,
                            gap_pct=gap_pct,
                            required_allocation_dollars=required_dollars,
                            priority=priority
                        )
                        
                        gaps.append(gap)
                        
                        self.logger.info(f"📊 Gap identified: {check.rule.rule_type.value}/{check.rule.category} - " +
                                       f"Current: {check.current_pct:.1f}%, Target: {check.target_pct:.1f}%, " +
                                       f"Gap: {gap_pct:+.1f}%, ${required_dollars:.0f} {'needed' if gap_pct > 0 else 'excess'}")
                        
            # Sort by priority (highest first)
            gaps.sort(key=lambda x: x.priority)
            return gaps
            
        except Exception as e:
            self.logger.error(f"❌ Failed to identify allocation gaps: {e}")
            return []
            
    def _get_current_allocation_pct(self, allocations: Dict[str, Any], 
                                  rule_type: RuleType, category: str) -> float:
        """Get current allocation percentage for a specific rule category"""
        try:
            if rule_type == RuleType.ASSET:
                asset_allocations = allocations.get('asset_allocation', {})
                return asset_allocations.get(category, 0.0)
                
            elif rule_type == RuleType.DURATION:
                duration_allocations = allocations.get('duration_allocation', {})
                return duration_allocations.get(category, 0.0)
                
            elif rule_type == RuleType.STRATEGY:
                strategy_allocations = allocations.get('strategy_allocation', {})
                return strategy_allocations.get(category, 0.0)
                
            return 0.0
            
        except Exception as e:
            self.logger.error(f"❌ Error getting current allocation: {e}")
            return 0.0
            
    def _save_compliance_check(self, check: ComplianceCheck, portfolio_value: float):
        """Save compliance check to history"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO compliance_history 
                (rule_type, category, current_pct, target_pct, deviation_pct, status, total_portfolio_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                check.rule.rule_type.value,
                check.rule.category,
                check.current_pct,
                check.target_pct,
                check.deviation_pct,
                check.status.value,
                portfolio_value
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"❌ Failed to save compliance check: {e}")
            
    def get_compliance_summary(self) -> Dict[str, Any]:
        """Get summary of current compliance status"""
        try:
            rules = self.get_all_rules()
            
            summary = {
                'total_rules': len(rules),
                'by_type': {
                    'asset': len([r for r in rules if r.rule_type == RuleType.ASSET]),
                    'duration': len([r for r in rules if r.rule_type == RuleType.DURATION]),
                    'strategy': len([r for r in rules if r.rule_type == RuleType.STRATEGY])
                },
                'last_updated': max([r.updated_at for r in rules if r.updated_at]).isoformat() if rules else None
            }
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get compliance summary: {e}")
            return {}