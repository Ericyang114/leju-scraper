"""
獨立執行爬蟲腳本，供 Windows 工作排程器呼叫。
用法：python run_scraper.py
"""
import logging
import sys
from pathlib import Path

# 確保工作目錄在腳本所在資料夾，讓 leju.db 產生在正確位置
sys.path.insert(0, str(Path(__file__).parent))
import os
os.chdir(Path(__file__).parent)

from scraper import scrape

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("scraper.log", encoding="utf-8"),
        ],
    )
    success = scrape()
    sys.exit(0 if success else 1)
