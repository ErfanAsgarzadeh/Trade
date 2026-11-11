FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lbank_bot.py strategy_archetypes.py dashboard_server.py config.json c3_sleeve.py c3_config.json shared_paper_account.py pa_sleeve.py pa_config.json lbank_candles.py fetch_funding.py performance.py momentum.py lbank_account.py exchanges.py live_mirror.py ttt_stop_audit.py ttt_one_time_tpsl.py ttt_account_audit.py ttt_protection_readback.py ttt_live_readiness.py ttt_live_certify.py live_risk.py paper_forward_audit.py ./
COPY license_access.py capital_plans.py signal_feed.py deployment_security.py customer_entrypoint.py ./
COPY lbank_official_candles.py ./
COPY frontend/public/portal-assets/titanium.css frontend/public/portal-assets/appearance.js ./frontend/public/portal-assets/
RUN mkdir -p /app/runtime
CMD ["python", "-u", "lbank_bot.py"]
