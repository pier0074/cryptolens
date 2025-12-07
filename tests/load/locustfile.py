"""
Load Testing for CryptoLens API

Usage:
    # Install locust
    pip install locust

    # Run load test (web UI)
    locust -f tests/load/locustfile.py --host=http://localhost:5000

    # Run headless (CLI)
    locust -f tests/load/locustfile.py --host=http://localhost:5000 \
        --users 100 --spawn-rate 10 --run-time 60s --headless

    # Run with specific user class
    locust -f tests/load/locustfile.py --host=http://localhost:5000 \
        -u 50 -r 5 -t 30s --headless APIUser

Configuration:
    - Set API_KEY environment variable for authenticated endpoints
    - Adjust wait_time for different load patterns
"""
import os
import random
from locust import HttpUser, task, between, tag


# Configuration
API_KEY = os.getenv('API_KEY', '')
SYMBOLS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT']
TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']


class APIUser(HttpUser):
    """
    Simulates API consumers accessing public endpoints.
    High frequency, read-only operations.
    """
    wait_time = between(0.5, 2)  # 0.5-2 seconds between requests
    weight = 3  # 3x more likely than other user types

    @task(10)
    @tag('public', 'health')
    def health_check(self):
        """Health check endpoint - very frequent"""
        self.client.get('/api/health')

    @task(5)
    @tag('public', 'symbols')
    def get_symbols(self):
        """Get list of symbols"""
        self.client.get('/api/symbols')

    @task(8)
    @tag('public', 'patterns')
    def get_patterns(self):
        """Get patterns with various filters"""
        params = {}
        if random.random() > 0.5:
            params['symbol'] = random.choice(SYMBOLS)
        if random.random() > 0.5:
            params['timeframe'] = random.choice(TIMEFRAMES)
        if random.random() > 0.3:
            params['limit'] = random.choice([10, 25, 50, 100])

        self.client.get('/api/patterns', params=params)

    @task(6)
    @tag('public', 'signals')
    def get_signals(self):
        """Get trading signals"""
        params = {'limit': random.choice([10, 25, 50])}
        if random.random() > 0.5:
            params['direction'] = random.choice(['bullish', 'bearish'])

        self.client.get('/api/signals', params=params)

    @task(4)
    @tag('public', 'candles')
    def get_candles(self):
        """Get candle data for a symbol"""
        symbol = random.choice(SYMBOLS)
        timeframe = random.choice(TIMEFRAMES)
        limit = random.choice([50, 100, 200])

        self.client.get(f'/api/candles/{symbol}/{timeframe}',
                        params={'limit': limit})

    @task(7)
    @tag('public', 'matrix')
    def get_matrix(self):
        """Get pattern matrix - cached endpoint"""
        self.client.get('/api/matrix')

    @task(2)
    @tag('public', 'scheduler')
    def get_scheduler_status(self):
        """Get scheduler status"""
        self.client.get('/api/scheduler/status')


class AuthenticatedAPIUser(HttpUser):
    """
    Simulates authenticated API users with API keys.
    Lower frequency, includes write operations.
    """
    wait_time = between(5, 15)  # 5-15 seconds between requests
    weight = 1

    def on_start(self):
        """Set up authentication"""
        self.api_key = API_KEY
        if not self.api_key:
            # Skip authenticated tests if no API key
            self.environment.runner.quit()

    @task(3)
    @tag('authenticated', 'scan')
    def trigger_scan(self):
        """Trigger a pattern scan (rate limited: 1/min)"""
        if not self.api_key:
            return

        headers = {'X-API-Key': self.api_key}
        with self.client.post('/api/scan', headers=headers,
                              catch_response=True) as response:
            if response.status_code == 429:
                response.success()  # Rate limited is expected
            elif response.status_code in [200, 401, 503]:
                response.success()

    @task(2)
    @tag('authenticated', 'fetch')
    def trigger_fetch(self):
        """Trigger data fetch (rate limited: 5/min)"""
        if not self.api_key:
            return

        headers = {'X-API-Key': self.api_key}
        data = {
            'symbol': random.choice(SYMBOLS).replace('-', '/'),
            'timeframe': random.choice(TIMEFRAMES)
        }
        with self.client.post('/api/fetch', headers=headers, json=data,
                              catch_response=True) as response:
            if response.status_code == 429:
                response.success()  # Rate limited is expected
            elif response.status_code in [200, 400, 401, 503]:
                response.success()


class WebUser(HttpUser):
    """
    Simulates web browser users navigating the site.
    Includes page loads and static assets.
    """
    wait_time = between(3, 10)  # 3-10 seconds between page views
    weight = 2

    @task(5)
    @tag('web', 'landing')
    def view_landing(self):
        """View landing page"""
        self.client.get('/')

    @task(3)
    @tag('web', 'login')
    def view_login(self):
        """View login page"""
        self.client.get('/auth/login')

    @task(2)
    @tag('web', 'pricing')
    def view_pricing(self):
        """View pricing page"""
        self.client.get('/pricing')

    @task(1)
    @tag('web', 'docs')
    def view_api_docs(self):
        """View API documentation"""
        self.client.get('/api/docs')


class MetricsUser(HttpUser):
    """
    Simulates Prometheus scraping metrics endpoint.
    Regular interval polling.
    """
    wait_time = between(14, 16)  # ~15 second scrape interval
    weight = 1

    @task
    @tag('metrics')
    def scrape_metrics(self):
        """Scrape Prometheus metrics"""
        self.client.get('/metrics')


# Combined user for realistic traffic mix
class MixedTrafficUser(HttpUser):
    """
    Combined user that mixes different types of requests.
    Realistic traffic pattern for load testing.
    """
    wait_time = between(1, 5)

    @task(10)
    def api_health(self):
        self.client.get('/api/health')

    @task(5)
    def api_matrix(self):
        self.client.get('/api/matrix')

    @task(4)
    def api_patterns(self):
        self.client.get('/api/patterns', params={'limit': 50})

    @task(3)
    def api_signals(self):
        self.client.get('/api/signals', params={'limit': 25})

    @task(2)
    def api_symbols(self):
        self.client.get('/api/symbols')

    @task(2)
    def api_candles(self):
        symbol = random.choice(SYMBOLS)
        tf = random.choice(TIMEFRAMES)
        self.client.get(f'/api/candles/{symbol}/{tf}', params={'limit': 100})

    @task(3)
    def web_landing(self):
        self.client.get('/')

    @task(1)
    def metrics(self):
        self.client.get('/metrics')


# Event hooks for custom reporting
from locust import events


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Log slow requests"""
    if response_time > 1000:  # More than 1 second
        print(f"SLOW: {request_type} {name} took {response_time:.0f}ms")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Print test configuration at start"""
    print(f"\n{'='*60}")
    print("CryptoLens Load Test Starting")
    print(f"Target: {environment.host}")
    print(f"API Key configured: {'Yes' if API_KEY else 'No'}")
    print(f"{'='*60}\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary at end"""
    print(f"\n{'='*60}")
    print("Load Test Complete")
    stats = environment.stats
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Failures: {stats.total.num_failures}")
    print(f"Median response time: {stats.total.median_response_time:.0f}ms")
    print(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.0f}ms")
    print(f"{'='*60}\n")
