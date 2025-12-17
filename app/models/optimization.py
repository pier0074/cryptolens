"""
Optimization models: OptimizationJob, OptimizationRun
For automated parameter sweep and backtesting optimization
"""
import json
from datetime import datetime, timezone
from app import db


# Status constants
OPTIMIZATION_STATUSES = ['pending', 'running', 'completed', 'failed', 'cancelled']

# Default parameter grids
DEFAULT_PARAMETER_GRID = {
    'rr_target': [1.5, 2.0, 2.5, 3.0],
    'sl_buffer_pct': [5, 10, 15, 20],
    'min_zone_pct': [0.1, 0.15, 0.2],
    'tp_method': ['fixed_rr'],
    'entry_method': ['zone_edge'],
    'use_overlap': [True]
}

QUICK_PARAMETER_GRID = {
    'rr_target': [2.0, 2.5, 3.0],
    'sl_buffer_pct': [10, 15],
    'min_zone_pct': [0.15],
    'tp_method': ['fixed_rr'],
    'entry_method': ['zone_edge'],
    'use_overlap': [True]
}


class OptimizationJob(db.Model):
    """Tracks a batch of optimization runs"""
    __tablename__ = 'optimization_jobs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')

    # Scope (JSON arrays)
    symbols = db.Column(db.Text, nullable=False)
    timeframes = db.Column(db.Text, nullable=False)
    pattern_types = db.Column(db.Text, nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)

    # Parameter grid (JSON)
    parameter_grid = db.Column(db.Text, nullable=False)

    # Progress
    total_runs = db.Column(db.Integer, default=0)
    completed_runs = db.Column(db.Integer, default=0)
    failed_runs = db.Column(db.Integer, default=0)

    # Best results (JSON)
    best_params_json = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    runs = db.relationship('OptimizationRun', backref='job', lazy='dynamic',
                          cascade='all, delete-orphan')

    def __repr__(self):
        return f'<OptimizationJob {self.id} {self.name} ({self.status})>'

    @property
    def symbols_list(self):
        """Get symbols as list"""
        return json.loads(self.symbols) if self.symbols else []

    @symbols_list.setter
    def symbols_list(self, value):
        self.symbols = json.dumps(value)

    @property
    def timeframes_list(self):
        """Get timeframes as list"""
        return json.loads(self.timeframes) if self.timeframes else []

    @timeframes_list.setter
    def timeframes_list(self, value):
        self.timeframes = json.dumps(value)

    @property
    def pattern_types_list(self):
        """Get pattern_types as list"""
        return json.loads(self.pattern_types) if self.pattern_types else []

    @pattern_types_list.setter
    def pattern_types_list(self, value):
        self.pattern_types = json.dumps(value)

    @property
    def parameter_grid_dict(self):
        """Get parameter_grid as dict"""
        return json.loads(self.parameter_grid) if self.parameter_grid else {}

    @parameter_grid_dict.setter
    def parameter_grid_dict(self, value):
        self.parameter_grid = json.dumps(value)

    @property
    def best_params(self):
        """Get best_params as dict"""
        return json.loads(self.best_params_json) if self.best_params_json else None

    @best_params.setter
    def best_params(self, value):
        self.best_params_json = json.dumps(value) if value else None

    @property
    def progress_pct(self):
        """Get progress percentage"""
        if self.total_runs == 0:
            return 0
        return round((self.completed_runs + self.failed_runs) / self.total_runs * 100, 1)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'symbols': self.symbols_list,
            'timeframes': self.timeframes_list,
            'pattern_types': self.pattern_types_list,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'parameter_grid': self.parameter_grid_dict,
            'total_runs': self.total_runs,
            'completed_runs': self.completed_runs,
            'failed_runs': self.failed_runs,
            'progress_pct': self.progress_pct,
            'best_params': self.best_params,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class OptimizationRun(db.Model):
    """Individual backtest run with specific parameters"""
    __tablename__ = 'optimization_runs'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('optimization_jobs.id'), nullable=False)

    # Scope
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    pattern_type = db.Column(db.String(30), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)

    # Parameters tested
    rr_target = db.Column(db.Float, nullable=False)
    sl_buffer_pct = db.Column(db.Float, nullable=False)
    tp_method = db.Column(db.String(20), nullable=False, default='fixed_rr')
    entry_method = db.Column(db.String(20), nullable=False, default='zone_edge')
    min_zone_pct = db.Column(db.Float, nullable=False, default=0.15)
    use_overlap = db.Column(db.Boolean, default=True)

    # Results
    status = db.Column(db.String(20), default='pending')
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    avg_rr = db.Column(db.Float, default=0.0)
    total_profit_pct = db.Column(db.Float, default=0.0)
    max_drawdown = db.Column(db.Float, default=0.0)
    sharpe_ratio = db.Column(db.Float, default=0.0)
    profit_factor = db.Column(db.Float, default=0.0)
    avg_trade_duration = db.Column(db.Float, default=0.0)

    # Detailed results (JSON)
    results_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Indexes for fast queries
    __table_args__ = (
        db.Index('idx_opt_run_job', 'job_id'),
        db.Index('idx_opt_run_symbol_pattern', 'symbol', 'pattern_type'),
        db.Index('idx_opt_run_results', 'win_rate', 'total_profit_pct'),
    )

    def __repr__(self):
        return f'<OptimizationRun {self.id} {self.symbol} {self.pattern_type} RR={self.rr_target}>'

    @property
    def results(self):
        """Get detailed results as dict"""
        return json.loads(self.results_json) if self.results_json else None

    @results.setter
    def results(self, value):
        self.results_json = json.dumps(value) if value else None

    @property
    def params_dict(self):
        """Get all parameters as dict"""
        return {
            'rr_target': self.rr_target,
            'sl_buffer_pct': self.sl_buffer_pct,
            'tp_method': self.tp_method,
            'entry_method': self.entry_method,
            'min_zone_pct': self.min_zone_pct,
            'use_overlap': self.use_overlap,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'pattern_type': self.pattern_type,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'params': self.params_dict,
            'status': self.status,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'avg_rr': self.avg_rr,
            'total_profit_pct': self.total_profit_pct,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'profit_factor': self.profit_factor,
            'avg_trade_duration': self.avg_trade_duration,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
