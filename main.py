name: Telegram RSS Feed Automation

on:
  schedule:
    - cron: "*/5 * * * *"  # Runs every 5 minutes
  workflow_dispatch:  # Allows manual trigger from GitHub

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout repository
      uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: "3.12"

    - name: Install dependencies
      run: |
        pip install flask telethon feedgen waitress google-cloud-storage

    - name: Run Telegram RSS Feed Script
      env:
        TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
        TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
        TELEGRAM_STRING_SESSION: ${{ secrets.TELEGRAM_STRING_SESSION }}
        GCP_SERVICE_ACCOUNT_JSON: ${{ secrets.GCP_SERVICE_ACCOUNT_JSON }}
      run: python main.py
