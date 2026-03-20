"""
PHASE 3 DEPLOYMENT GUIDE
Complete setup for production deployment (monitoring → features → portfolio → ML Ops)

TIMELINE: 2-3 hours for complete setup
DEPENDENCIES: Docker, Prometheus, Grafana, Redis, PostgreSQL

═══════════════════════════════════════════════════════════════════════════════
1. PRE-DEPLOYMENT VALIDATION (15 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 1.1: Verify Python environment
  Command:
    python --version  # Should be 3.10+
    pip list | grep -E "prometheus|scipy|numpy"

□ STEP 1.2: Check dependencies installed
  Command:
    pip install -r requirements-phase3.txt
  
  Contents (requirements-phase3.txt):
    prometheus-client==0.19.0
    grafana-api==1.0.3
    fastapi==0.104.1
    uvicorn==0.24.0
    numpy==1.24.0
    scipy==1.11.0
    scikit-learn==1.3.0
    pandas==2.0.0
    sqlalchemy==2.0.0
    redis==5.0.0

□ STEP 1.3: Verify Docker running
  Command:
    docker --version
    docker ps  # Should show running containers

□ STEP 1.4: Check required services ready
  Command:
    redis-cli ping          # Should return PONG
    psql -U postgres -d trading_system -c "SELECT 1"  # Should work

═══════════════════════════════════════════════════════════════════════════════
2. INFRASTRUCTURE SETUP (45 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 2.1: Start Prometheus container
  Command:
    docker run -d \
      --name prometheus \
      -p 9090:9090 \
      -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
      -v $(pwd)/alerts.yml:/etc/prometheus/alerts.yml \
      prom/prometheus:latest \
      --config.file=/etc/prometheus/prometheus.yml
  
  Verify:
    curl http://localhost:9090
    # Should return Prometheus UI

□ STEP 2.2: Create prometheus.yml config
  File: prometheus.yml
  Content:
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
    
    alerting:
      alertmanagers:
        - static_configs:
            - targets: ['localhost:9093']
    
    rule_files:
      - 'alerts.yml'
    
    scrape_configs:
      - job_name: 'trading-api'
        static_configs:
          - targets: ['localhost:8000']
      - job_name: 'prometheus'
        static_configs:
          - targets: ['localhost:9090']
      - job_name: 'node-exporter'
        static_configs:
          - targets: ['localhost:9100']

□ STEP 2.3: Generate alerts.yml from monitoring_dashboards.py
  Command:
    python -c "
    from monitoring_dashboards import GrafanaDashboardBuilder
    builder = GrafanaDashboardBuilder()
    builder.export_prometheus_rules('alerts.yml')
    print('Alerts exported to alerts.yml')
    "

□ STEP 2.4: Start Grafana container
  Command:
    docker run -d \
      --name grafana \
      -p 3000:3000 \
      -e GF_SECURITY_ADMIN_PASSWORD=admin \
      grafana/grafana:latest
  
  Verify:
    curl http://localhost:3000
    # Login at http://localhost:3000 (admin/admin)

□ STEP 2.5: Add Prometheus data source to Grafana
  Steps:
    1. Go to http://localhost:3000
    2. Settings → Data Sources → Add
    3. Name: "Prometheus"
    4. URL: http://localhost:9090
    5. Save & Test

□ STEP 2.6: Start Redis container
  Command:
    docker run -d \
      --name redis \
      -p 6379:6379 \
      redis:latest
  
  Verify:
    redis-cli ping  # Should return PONG

□ STEP 2.7: Create PostgreSQL database
  Command:
    psql -U postgres << EOF
    CREATE DATABASE trading_system;
    CREATE USER trading WITH PASSWORD 'secure_password';
    GRANT ALL PRIVILEGES ON DATABASE trading_system TO trading;
    EOF
  
  Verify:
    psql -U trading -d trading_system -c "SELECT 1"

═══════════════════════════════════════════════════════════════════════════════
3. MODULE INITIALIZATION (30 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 3.1: Initialize monitoring dashboards
  Python:
    from monitoring_dashboards import GrafanaDashboardBuilder
    
    builder = GrafanaDashboardBuilder()
    
    # Export dashboards as JSON
    dashboards = builder.create_all_dashboards()
    builder.export_dashboards_to_json('./dashboards')
    print("✓ Exported 6 dashboards")
    
    # Export alert rules
    builder.export_prometheus_rules('./alerts.yml')
    print("✓ Exported 18 Prometheus alert rules")

□ STEP 3.2: Import dashboards into Grafana
  Command (via curl):
    for dashboard in dashboards/*.json; do
      curl -X POST \
        -H "Content-Type: application/json" \
        -d @$dashboard \
        http://admin:admin@localhost:3000/api/dashboards/db
    done

□ STEP 3.3: Initialize portfolio optimizer
  Python:
    from portfolio_optimization import PortfolioOptimizer, create_standard_portfolio
    
    optimizer = PortfolioOptimizer(
        initial_capital=1000000,
        rebalance_threshold=0.05,
        max_drawdown_limit=0.20
    )
    print("✓ Portfolio optimizer initialized")
    
    # Load benchmark assets
    assets_config = {
        "AAPL": {"sector": "Technology", "beta": 1.2},
        "GOOGL": {"sector": "Technology", "beta": 1.1},
        "JNJ": {"sector": "Healthcare", "beta": 0.9},
        "MSFT": {"sector": "Technology", "beta": 1.0},
    }
    
    for ticker, config in assets_config.items():
        optimizer.add_asset(ticker, **config)
    
    print(f"✓ Added {len(assets_config)} assets")

□ STEP 3.4: Initialize ML Ops framework
  Python:
    from ml_ops_framework import MLOpsFramework
    
    mlops = MLOpsFramework()
    print("✓ ML Ops framework initialized")
    
    # Verify retraining triggers
    triggers = ["SCHEDULED", "DRIFT_DETECTED", "PERFORMANCE_DROP", "NEW_DATA_AVAILABLE"]
    print(f"✓ Available retraining triggers: {triggers}")

□ STEP 3.5: Initialize feature pipeline
  Python:
    from real_time_features import RealTimeFeaturePipeline, create_standard_feature_pipeline
    
    feature_pipeline = create_standard_feature_pipeline()
    print("✓ Feature pipeline initialized")
    
    # Verify features registered
    print(f"✓ Registered features: {list(feature_pipeline.features.keys())}")

═══════════════════════════════════════════════════════════════════════════════
4. API SERVER STARTUP (15 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 4.1: Create environment configuration
  File: .env
  Content:
    # Database
    DATABASE_URL=postgresql://trading:secure_password@localhost:5432/trading_system
    
    # Redis
    REDIS_URL=redis://localhost:6379/0
    
    # Prometheus
    PROMETHEUS_URL=http://localhost:9090
    PROMETHEUS_PUSHGATEWAY=localhost:9091
    
    # Initial capital
    INITIAL_CAPITAL=1000000
    
    # Model paths
    MODEL_CHAMPION=/models/champion.pkl
    MODEL_CHALLENGER=/models/challenger.pkl

□ STEP 4.2: Start API server
  Command:
    python api_server_enhanced.py --host 0.0.0.0 --port 8000
  
  Expected output:
    INFO:     Uvicorn running on http://0.0.0.0:8000
    INFO:     Application startup complete
    ✓ All 14 API endpoints ready

□ STEP 4.3: Verify API health
  Command:
    curl http://localhost:8000/health
  
  Expected response:
    {"status": "healthy", "version": "3.0"}

□ STEP 4.4: Verify all endpoints
  Python:
    import requests
    
    endpoints = [
        "/api/monitoring/dashboards",
        "/api/portfolio/metrics",
        "/api/mlops/status",
        "/api/features/consistency"
    ]
    
    for endpoint in endpoints:
        r = requests.get(f"http://localhost:8000{endpoint}")
        assert r.status_code in [200, 201], f"Failed: {endpoint}"
        print(f"✓ {endpoint}")

═══════════════════════════════════════════════════════════════════════════════
5. DATA INGESTION (20 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 5.1: Ingest market data stream
  Python:
    from real_time_features import RealTimeFeaturePipeline
    from datetime import datetime
    import random
    
    pipeline = RealTimeFeaturePipeline()
    
    tickers = ["AAPL", "GOOGL", "MSFT", "JNJ"]
    base_price = {"AAPL": 150, "GOOGL": 120, "MSFT": 140, "JNJ": 160}
    
    for _ in range(100):  # Simulate 100 ticks
        for ticker in tickers:
            price = base_price[ticker] + random.uniform(-1, 1)
            volume = random.randint(1000000, 5000000)
            
            pipeline.ingest_market_data(
                ticker=ticker,
                timestamp=datetime.now(),
                price=price,
                volume=volume
            )
    
    print("✓ Ingested 400 market data points")

□ STEP 5.2: Compute online features
  Python:
    from real_time_features import RealTimeFeaturePipeline
    
    pipeline = RealTimeFeaturePipeline()
    
    for ticker in ["AAPL", "GOOGL", "MSFT", "JNJ"]:
        features = pipeline.compute_online_features(
            ticker=ticker,
            timestamp=datetime.now(),
            feature_names=["sma_20", "rsi", "macd"]
        )
        print(f"{ticker}: {features.features}")
    
    print("✓ Computed online features for 4 tickers")

□ STEP 5.3: Compute offline batch features
  Python:
    from real_time_features import RealTimeFeaturePipeline
    from datetime import date, timedelta
    
    pipeline = RealTimeFeaturePipeline()
    
    start_date = date.today() - timedelta(days=30)
    end_date = date.today()
    
    offline_features = pipeline.compute_offline_features(
        tickers=["AAPL", "GOOGL", "MSFT", "JNJ"],
        date_range=(start_date, end_date),
        batch_size=100
    )
    
    print("✓ Computed offline features for 30 days")

□ STEP 5.4: Check consistency
  Python:
    from real_time_features import RealTimeFeaturePipeline, FeatureConsistencyMonitor
    
    pipeline = RealTimeFeaturePipeline()
    monitor = FeatureConsistencyMonitor(pipeline)
    
    consistency = monitor.check_all_features(
        tickers=["AAPL", "GOOGL"],
        date_=date.today()
    )
    
    print(f"Consistency: {consistency}")

═══════════════════════════════════════════════════════════════════════════════
6. FUNCTIONAL TESTS (20 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 6.1: Test portfolio optimization endpoint
  Command:
    curl -X POST http://localhost:8000/api/portfolio/optimize \
      -H "Content-Type: application/json" \
      -d '{
        "method": "risk_parity",
        "lookback_days": 30
      }'
  
  Expected:
    {"weights": {...}, "sharpe_ratio": 1.23, ...}

□ STEP 6.2: Test A/B test creation endpoint
  Command:
    curl -X POST http://localhost:8000/api/mlops/start-abtest \
      -H "Content-Type: application/json" \
      -d '{
        "champion": "model_v1.pkl",
        "challenger": "model_v2.pkl",
        "traffic_split": 0.5,
        "duration": 14,
        "min_sample": 1000
      }'
  
  Expected:
    {"test_id": "test_abc123", "status": "RUNNING", ...}

□ STEP 6.3: Test feature computation endpoint
  Command:
    curl -X POST http://localhost:8000/api/features/compute-online \
      -H "Content-Type: application/json" \
      -d '{
        "ticker": "AAPL",
        "feature_names": ["sma_20", "rsi", "macd"]
      }'
  
  Expected:
    {"features": {"sma_20": 150.5, "rsi": 55.2, "macd": 0.8}, ...}

□ STEP 6.4: Test dashboard export endpoint
  Command:
    curl http://localhost:8000/api/monitoring/export-grafana > dashboards.zip
    unzip dashboards.zip
    ls dashboards/  # Should have 6 JSON files
  
  Expected:
    system_health.json
    trading_performance.json
    risk_management.json
    model_performance.json
    resource_utilization.json
    alerts.json

□ STEP 6.5: Run integration test suite
  Command:
    pytest tests/test_phase3_integration.py -v --tb=short
  
  Expected output:
    test_dashboard_creation PASSED
    test_ab_test_routing PASSED
    test_online_feature_latency PASSED
    test_risk_parity_allocation PASSED
    ...
    === 20 passed in 2.34s ===

═══════════════════════════════════════════════════════════════════════════════
7. MONITORING VERIFICATION (15 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 7.1: Check Prometheus metrics
  UI: http://localhost:9090
  Verify:
    - Targets: All 3 should be "UP"
      * trading-api
      * prometheus (self)
      * node-exporter
    - Graph: Query "up" → should show 3 series

□ STEP 7.2: Verify dashboards in Grafana
  UI: http://localhost:3000
  Steps:
    1. Login: admin / admin
    2. Navigate to "System Health" dashboard
    3. Verify panels show data (not red errors)
    4. Repeat for remaining 5 dashboards

□ STEP 7.3: Check alert rules loaded
  Command:
    curl http://localhost:9090/api/v1/rules | jq '.data.groups[] | .rules[] | .alert'
  
  Expected:
    18 alert names (APILatencyHigh, DatabaseConnectionsFull, etc.)

□ STEP 7.4: Generate test alert
  Python:
    import requests
    
    # Trigger a metric that fires an alert
    requests.post("http://localhost:8000/api/test/trigger-alert", 
      json={"alert_name": "APILatencyHigh", "value": 600})
    
    # Wait 30 seconds for evaluation
    # Check Prometheus alerts: http://localhost:9090/alerts

═══════════════════════════════════════════════════════════════════════════════
8. CANARY DEPLOYMENT (Gradual Rollout - 30 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 8.1: Start with 1% traffic
  Config (config.yaml):
    deployment:
      canary:
        enabled: true
        phase_3_traffic_percent: 1
        duration_minutes: 10
  
  Verify:
    - 99% traffic → old version
    - 1% traffic → Phase 3 system
    - Monitor error rates (should remain <0.1%)

□ STEP 8.2: Increase to 10% after 10 minutes
  Update config:
    phase_3_traffic_percent: 10
    duration_minutes: 10
  
  Verify no new error patterns
  Check Phase 3 dashboards for anomalies

□ STEP 8.3: Increase to 50% after 20 minutes
  Update config:
    phase_3_traffic_percent: 50
    duration_minutes: 10
  
  Verify:
    - Feature pipeline latency <50ms
    - Portfolio optimization <1s
    - A/B test routing <5ms per prediction

□ STEP 8.4: Full rollout (100%) after 30 minutes
  Update config:
    phase_3_traffic_percent: 100
  
  Final verification:
    - All 14 endpoints responding
    - All 6 dashboards populating
    - All 18 alerts configured
    - No errors in logs

═══════════════════════════════════════════════════════════════════════════════
9. PRODUCTION HARDENING (30 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 9.1: Enable monitoring alerts
  In Grafana:
    - Enable notification channels for PagerDuty, Slack, etc.
    - Set escalation policies:
      * API alerts → on-call engineer (2 min)
      * Risk alerts → risk team (immediate)
      * ML alerts → ML team (5 min)

□ STEP 9.2: Set up logging aggregation
  Command:
    # Configure centralized logging (ELK, Datadog, etc.)
    docker run -d --name logstash -e "ELASTICSEARCH_HOST=localhost" logstash:latest

□ STEP 9.3: Add rate limiting to API
  Code (api_server_enhanced.py):
    from slowapi import Limiter
    
    limiter = Limiter(key_func=get_remote_address)
    
    @app.post("/api/portfolio/optimize")
    @limiter.limit("100/minute")
    def optimize_portfolio():
        ...

□ STEP 9.4: Configure database backups
  Command:
    # Daily backups
    0 1 * * * pg_dump trading_system | gzip > /backups/trading_$(date +\%Y\%m\%d).sql.gz

□ STEP 9.5: Set up disaster recovery
  Procedure:
    1. Backup all dashboards (Grafana export)
    2. Document alert rules (in git)
    3. Backup ML model files
    4. Backup feature cache (Redis RDB)
    5. Document recovery procedures

═══════════════════════════════════════════════════════════════════════════════
10. GO-LIVE VALIDATION (15 minutes)
═══════════════════════════════════════════════════════════════════════════════

□ STEP 10.1: Sanity checks
  ✓ All 14 API endpoints responding (200 OK)
  ✓ All 6 dashboards have real data
  ✓ All 18 alerts configured and evaluating
  ✓ Feature latency <50ms
  ✓ Portfolio optimization <1s
  ✓ A/B test routing active
  ✓ No critical errors in logs (last 1 hour)
  ✓ Database connectivity verified
  ✓ Redis cache operational
  ✓ Model files accessible

□ STEP 10.2: User acceptance testing
  Stakeholders:
    [ ] Risk team: Verify risk dashboard accuracy
    [ ] Trading team: Verify portfolio optimization results
    [ ] ML team: Verify A/B test framework
    [ ] Ops team: Verify monitoring dashboards
    [ ] Engineering: Verify API performance

□ STEP 10.3: Sign-off
  [ ] Risk team sign-off: _______________
  [ ] Trading team sign-off: _______________
  [ ] ML team sign-off: _______________
  [ ] Operations sign-off: _______________
  [ ] Engineering sign-off: _______________

□ STEP 10.4: Document final state
  Create deployment manifest:
    Version: 3.0
    Deployment date: 2024-01-XX
    Modules deployed: 14 (6 Phase 1 + 4 Phase 2 + 4 Phase 3)
    API endpoints: 14 active
    Dashboards: 6 (48 panels)
    Alerts: 18 configured
    Features registered: 8+
    Rollback plan: Ready (old version on standby)

═══════════════════════════════════════════════════════════════════════════════
ROLLBACK PROCEDURE (Emergency Only)
═══════════════════════════════════════════════════════════════════════════════

If critical issues arise:

1. Scale Phase 3 to 0%:
   config:
     phase_3_traffic_percent: 0
   All traffic routes to previous version

2. Stop API server:
   kill $(lsof -ti:8000)

3. Restore old configuration:
   cp config.backup.yml config.yml

4. Investigate in staging:
   docker-compose -f docker-compose.staging.yml up

5. Once fixed, re-deploy

═══════════════════════════════════════════════════════════════════════════════
POST-DEPLOYMENT MONITORING (Ongoing)
═══════════════════════════════════════════════════════════════════════════════

Monitor these metrics daily:

Dashboard Health:
  □ API latency p99 < 500ms
  □ Error rate < 0.1%
  □ Database query latency p95 < 5s

Portfolio Health:
  □ Rebalancing triggered as expected
  □ Regime detection accuracy >90%
  □ Risk metrics not exceeding limits

ML Health:
  □ Prediction latency <1s
  □ Feature drift KS < 0.15
  □ Model accuracy stable (±2%)

Feature Health:
  □ Online latency <50ms
  □ Online/offline consistency >95%
  □ Cache hit rate >80%

Resource Health:
  □ CPU usage <70%
  □ Memory usage <60%
  □ Disk usage <80%

═══════════════════════════════════════════════════════════════════════════════
TROUBLESHOOTING DURING DEPLOYMENT
═══════════════════════════════════════════════════════════════════════════════

Issue: Prometheus targets showing "DOWN"
  → Verify Docker container is running: docker ps | grep prometheus
  → Check logs: docker logs prometheus
  → Verify prometheus.yml has correct scrape configs

Issue: Grafana dashboards showing no data
  → Verify data source connectivity: Grafana → Settings → Data Sources → Test
  → Check Prometheus has metrics: http://localhost:9090/graph
  → Verify API is exporting metrics (check /metrics endpoint)

Issue: API endpoints return 500 errors
  → Check logs: tail -f logs/api.log
  → Verify database connectivity: psql connection test
  → Verify Redis connection: redis-cli ping
  → Check required libraries installed: pip list | grep -E "sqlalchemy|redis"

Issue: Feature latency >50ms
  → Profile computation: Add timing logs to feature pipeline
  → Check if using full history instead of recent window
  → Consider caching SMA/RSI values
  → Check system CPU/disk bottlenecks (iostat, top)

Issue: A/B test not routing traffic
  → Verify MLOpsFramework initialized: check logs for "ML Ops framework initialized"
  → Check traffic_split parameter (default 0.5)
  → Verify test duration hasn't expired
  → Check min_sample_size hasn't been reached without conclusion

═══════════════════════════════════════════════════════════════════════════════
END OF DEPLOYMENT GUIDE
═══════════════════════════════════════════════════════════════════════════════
"""
